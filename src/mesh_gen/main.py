from __future__ import annotations
import argparse
import os
import math
import numpy as np
import felupe as fe

from .config import MeshGenConfig
from .geometry import analyze_geometry_and_split
from .core_mesh import create_quarter_ogrid_xz, extrude_core_to_3d
from .utils import (
    rotate_about_canonical_y,
    permute_xyz,
    canonical_permutation_for_target_axis,
    orient_quads_ccw,
    fix_inverted_hexes_inplace,
    snap_interface_nodes_by_theta_layers,
    stitch_core_ring_conformal,
    _snap_near_axis_points,
    _merge_duplicate_points_with_backoff,
    save_mesh_with_optional_quadratic,
)

def generate_adaptive_mesh(config_path: str, stp_path: str, output_path: str | None = None) -> None:
    cfg = MeshGenConfig.from_yaml(config_path)

    if output_path is None:
        name = os.path.splitext(os.path.basename(config_path))[0]
        output_path = f"output/{name}_o_grid.vtk"

    # 1) Analyze geometry and build 2D quad mesh of the outer ring (in original coordinates)
    split = analyze_geometry_and_split(
        stp_path=stp_path,
        mesh_size=cfg.mesh_size,
        revolve_axis=cfg.revolve_axis,
        core_ratio=cfg.ogrid_core_ratio,
    )

    print(f"Detected axes: radial_dim={split.axes.radial_dim}, axial_dim={split.axes.axial_dim}, normal_dim={split.axes.normal_dim}")
    print(f"R_core={split.R_core:.6g}")

    # 2) Build 2D ring mesh in (R,A) coordinates (canonical: x=R, y=A) and revolve around canonical Y.
    rd, ad = split.axes.radial_dim, split.axes.axial_dim
    ring_RA = split.ring_points_3d[:, [rd, ad]].astype(float)
    ring_RA[:, 0] = np.abs(ring_RA[:, 0])  # ensure non-negative radius

    ring_quads_ccw = orient_quads_ccw(ring_RA, split.ring_quads)
    mesh_ring_2d = fe.Mesh(ring_RA, ring_quads_ccw, "quad")
    mesh_ring_3d = mesh_ring_2d.revolve(n=int(cfg.revolve_layers), phi=float(cfg.revolve_angle), axis=1)
    # Ensure consistent element orientation (prevents local inversions after revolve)
    fix_inverted_hexes_inplace(mesh_ring_3d, label="ring_3d")

    # 3) Extract axial distribution from ring_3d at interface (R ≈ R_core)
    #    IMPORTANT: After revolve, ring_3d has 3D coords: (X, Y, Z) where Y is axial
    #    We extract unique Y values at R ≈ R_core to use as a_interface
    tol = max(1e-6, cfg.mesh_size * 0.05)
    ring_pts_3d = mesh_ring_3d.points
    r_ring_3d = np.hypot(ring_pts_3d[:, 0], ring_pts_3d[:, 2])  # R = sqrt(X^2 + Z^2)
    mask_boundary = np.abs(r_ring_3d - split.R_core) < tol
    
    if np.count_nonzero(mask_boundary) < 2:
        raise RuntimeError(
            "Failed to locate interface nodes at R=R_core in ring_3d mesh. "
            f"(found {np.count_nonzero(mask_boundary)} nodes, tol={tol})"
        )
    
    # Get unique Y values (axial) at the boundary
    y_boundary = ring_pts_3d[mask_boundary, 1]
    # Round to avoid float precision issues and get unique values
    # VEXIS FIX: Relaxed tolerance to 4 decimals (0.1um) to merge close layers (prevents ghost layers)
    y_unique = np.unique(np.round(y_boundary, decimals=4))
    a_interface = np.sort(y_unique)  # sorted axial coordinates
    
    # VEXIS FIX: Filter out layers that are too close (ghost layers)
    if len(a_interface) > 1:
        min_dist = max(1e-6, cfg.mesh_size * 0.05) # 5% of mesh size tolerance
        keep_mask = np.ones(len(a_interface), dtype=bool)
        last_val = a_interface[0]
        for i in range(1, len(a_interface)):
            if (a_interface[i] - last_val) < min_dist:
                keep_mask[i] = False # Drop this layer (too close to previous)
            else:
                last_val = a_interface[i]
        
        n_dropped = len(a_interface) - np.count_nonzero(keep_mask)
        if n_dropped > 0:
            print(f"Refined a_interface: dropped {n_dropped} ghost layers (min_dist={min_dist:.6f})")
            a_interface = a_interface[keep_mask]

    print(f"Interface axial nodes: {len(a_interface)}")

    # 4) Generate structured core O-grid in the wedge and extrude with profile-based A-mapping.
    if abs(cfg.revolve_angle - 90.0) > 1e-6:
        raise NotImplementedError("Structured core currently supports revolve_angle=90 only.")
    # NOTE: felupe.Mesh.revolve(n=...) appears to generate 'n' theta node layers (not n+1).
    # To make the core interface conformal, create (revolve_layers-1) theta divisions => revolve_layers layers.
    core_theta_divs = max(1, int(cfg.revolve_layers) - 1)
    n0_45 = core_theta_divs // 2
    n45_90 = core_theta_divs - n0_45

    # Calculate axial height to determine winding direction
    A_bot_core = float(split.a_bot(np.array([split.R_core]))[0])
    A_top_core = float(split.a_top(np.array([split.R_core]))[0])
    H_ref = A_top_core - A_bot_core
    
    # Default winding (CCW in XZ) produces Normal = -Y.
    # If H_ref > 0 (Extrusion +Y), we need Normal +Y to get Positive Volume.
    # Logic adjustment: It seems our previous assumption was reversed, or creating CW winding works better.
    # Let's try inverting the logic.
    flip_winding = not (H_ref > 0)
    
    print(f"DEBUG: Core Height H_ref={H_ref:.6f}. Flip winding? {flip_winding}")

    # Determine n_radial
    if cfg.core_radial_layers > 0:
        n_radial = cfg.core_radial_layers
    else:
        # Heuristic: fill the annulus (R_core * (1-inner_ratio)) with mesh_size elements
        annulus_width = split.R_core * (1.0 - cfg.core_inner_ratio)
        n_radial = max(2, int(math.ceil(annulus_width / max(cfg.mesh_size, 1e-12))))

    core_xz, core_quads = create_quarter_ogrid_xz(
        split.R_core,
        n_theta0_45=n0_45,
        n_theta45_90=n45_90,
        phi_deg=cfg.revolve_angle,
        inner_ratio=cfg.core_inner_ratio,
        n_radial=n_radial,
        radial_beta=cfg.radial_mapping_beta,
        flip_winding=flip_winding,
    )

    mesh_core = extrude_core_to_3d(
        core_xz=core_xz,
        core_quads=core_quads,
        a_interface=a_interface,
        R_core=split.R_core,
        a_bot=split.a_bot,
        a_top=split.a_top,
    )


    # --- Fix: core circumferential phase alignment ---
    # If the core appears rotated vs the ring by 90°, adjust this value.
    # Reverted to -90.0 as 0.0 caused misalignment.
    core_theta_offset_deg = float(os.environ.get('CORE_THETA_OFFSET_DEG', '-90.0'))
    if abs(core_theta_offset_deg) > 1e-12:
        mesh_core.points[:] = rotate_about_canonical_y(mesh_core.points, core_theta_offset_deg)
    # Ensure consistent element orientation in core mesh
    fix_inverted_hexes_inplace(mesh_core, label="core_3d")

    # Layer-based interface stitching (robust): snap core interface nodes onto ring interface nodes
    snap_interface_nodes_by_theta_layers(
        mesh_core=mesh_core,
        mesh_ring_3d=mesh_ring_3d,
        R_core=split.R_core,
        revolve_angle_deg=cfg.revolve_angle,
        revolve_layers_hint=int(cfg.revolve_layers),
        tol_r=max(1e-4, cfg.mesh_size*1e-3),
    )

    # 5) Stitch meshes in canonical frame (axial=Y) without global point merging
    merged = stitch_core_ring_conformal(
        mesh_core=mesh_core,
        mesh_ring_3d=mesh_ring_3d,
        R_core=split.R_core,
        tol_r=max(1e-4, cfg.mesh_size * 1e-3),
    )
    # Snap near-axis points (canonical: Y axis) onto axis to avoid tiny radii artifacts
    _snap_near_axis_points(merged, tol=max(1e-12, cfg.mesh_size * 1e-6))
    # Merge duplicates robustly (avoid creating degenerate cells by over-rounding)

    # 6) Permute axes to the user-requested target revolve_axis
    perm = canonical_permutation_for_target_axis(cfg.revolve_axis)
    if perm != (0, 1, 2):
        merged.points[:] = merged.points[:, list(perm)].copy()
    # Final safety check: ensure no inverted hexes remain after axis mapping
    fix_inverted_hexes_inplace(merged, label="final")

    print(f"Final mesh: nodes={len(merged.points)}, elements={len(merged.cells)}")

    # 7) Save
    save_mesh_with_optional_quadratic(merged, output_path, element_order=int(cfg.mesh_dimension))
    
    # 8) Also save .msh for interoperability/inspection
    msh_output = os.path.splitext(output_path)[0] + ".msh"
    if msh_output != output_path:
        print(f"Adding .msh version: {msh_output}")
        save_mesh_with_optional_quadratic(merged, msh_output, element_order=int(cfg.mesh_dimension))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("stp_file")
    parser.add_argument("-o", "--output")
    args = parser.parse_args()

    generate_adaptive_mesh(args.config, args.stp_file, args.output)
