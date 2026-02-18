from __future__ import annotations

import argparse
import math
import os
from typing import Callable

import numpy as np
import felupe as fe

from src.mesh_gen.core_mesh import create_quarter_ogrid_xz
from src.mesh_gen.utils import (
    _snap_near_axis_points,
    canonical_permutation_for_target_axis,
    fix_inverted_hexes_inplace,
    orient_quads_ccw,
    rotate_about_canonical_y,
    save_mesh_with_optional_quadratic,
    snap_interface_nodes_by_theta_layers,
    stitch_core_ring_conformal,
)

from .config import ExperimentalMeshGenConfig
from .geometry import analyze_geometry_and_split


def _axis_aware_core_radial_layers(
    *,
    cfg: ExperimentalMeshGenConfig,
    r_core: float,
) -> int:
    """Choose radial layers with extra resolution near axis for core sweep stability."""
    annulus_width = max(0.0, float(r_core) * (1.0 - float(cfg.core_inner_ratio)))
    auto_layers = max(2, int(math.ceil(annulus_width / max(cfg.mesh_size, 1e-12))))
    base_layers = int(cfg.core_radial_layers) if cfg.core_radial_layers > 0 else auto_layers

    # Axis-near safeguard: keep at least a few layers even when annulus_width is small.
    # This reduces high-aspect cells around the inner core where sweep distortion accumulates.
    min_layers = max(
        4,
        int(math.ceil(max(annulus_width, cfg.mesh_size * 0.5) / max(cfg.mesh_size * 0.35, 1e-12))),
    )
    return max(base_layers, min_layers)


def _axis_aware_core_radial_beta(
    *,
    cfg: ExperimentalMeshGenConfig,
    r_core: float,
    n_radial: int,
) -> float:
    """Choose beta so core radial spacing is not over-clustered at outer interface."""
    raw_beta = float(cfg.radial_mapping_beta)
    if raw_beta <= 0.0:
        raw_beta = 1.0
    n = max(1, int(n_radial))
    if n <= 1:
        return min(raw_beta, 1.0)

    annulus_width = max(0.0, float(r_core) * (1.0 - float(cfg.core_inner_ratio)))
    if annulus_width <= 1e-12:
        return min(raw_beta, 1.0)

    # Keep the first radial layer around axis reasonably thin.
    target_first = min(
        annulus_width * 0.35,
        max(cfg.mesh_size * 0.6, annulus_width / (2.5 * n)),
    )
    q = min(0.95, max(0.05, target_first / annulus_width))
    beta_cap = math.log(1.0 / float(n)) / math.log(q)

    # For axis robustness, avoid beta>1 (which clusters too strongly near the outer side).
    beta_eff = min(raw_beta, beta_cap, 1.0)
    return max(0.35, float(beta_eff))


def _outer_boundary_mask(core_xz: np.ndarray, r_nodes: np.ndarray, r_core: float) -> np.ndarray:
    """Select only true outer boundary nodes (avoid snapping near-boundary interior nodes)."""
    strict_tol = max(1e-10, abs(float(r_core)) * 1e-8)
    mask = np.abs(r_nodes - float(r_core)) <= strict_tol
    if int(np.count_nonzero(mask)) >= 4:
        return mask

    # Fallback: per-theta farthest node (robust even if floating-point noise is larger).
    theta = np.arctan2(core_xz[:, 1], core_xz[:, 0])
    key = np.round(theta / 1e-6).astype(np.int64)
    best: dict[int, int] = {}
    for idx, k in enumerate(key.tolist()):
        prev = best.get(k)
        if prev is None or r_nodes[idx] > r_nodes[prev]:
            best[k] = idx
    mask = np.zeros(len(core_xz), dtype=bool)
    if best:
        mask[np.array(list(best.values()), dtype=int)] = True
    return mask


def _extrude_core_to_3d_axis_safe(
    *,
    core_xz: np.ndarray,
    core_quads: np.ndarray,
    a_interface: np.ndarray,
    r_core: float,
    a_bot: Callable[[np.ndarray], np.ndarray],
    a_top: Callable[[np.ndarray], np.ndarray],
) -> fe.Mesh:
    """Structured core extrusion with stricter boundary handling around axis."""
    core_xz = np.asarray(core_xz, dtype=float)
    core_quads = np.asarray(core_quads, dtype=np.int64)
    a_interface = np.asarray(a_interface, dtype=float)

    a_bot_ref = float(a_bot(np.array([r_core]))[0])
    a_top_ref = float(a_top(np.array([r_core]))[0])
    h_ref = a_top_ref - a_bot_ref
    if abs(h_ref) < 1e-12:
        etas = np.linspace(0.0, 1.0, len(a_interface))
    else:
        etas = (a_interface - a_bot_ref) / h_ref

    r_nodes = np.hypot(core_xz[:, 0], core_xz[:, 1])
    a_bot_nodes = a_bot(r_nodes)
    a_top_nodes = a_top(r_nodes)

    is_boundary = _outer_boundary_mask(core_xz, r_nodes, r_core)
    if int(np.count_nonzero(is_boundary)) < 4:
        raise RuntimeError(
            "Failed to identify enough core outer-boundary nodes for axis-safe extrusion."
        )

    theta_boundary = np.arctan2(core_xz[is_boundary, 1], core_xz[is_boundary, 0])
    core_xz_corrected = core_xz.copy()
    core_xz_corrected[is_boundary, 0] = float(r_core) * np.cos(theta_boundary)
    core_xz_corrected[is_boundary, 1] = float(r_core) * np.sin(theta_boundary)

    points_layers: list[np.ndarray] = []
    for eta in etas:
        a_layer = a_bot_nodes + float(eta) * (a_top_nodes - a_bot_nodes)
        pts = np.column_stack([core_xz_corrected[:, 0], a_layer, core_xz_corrected[:, 1]])
        points_layers.append(pts)

    points3d = np.vstack(points_layers)

    n_layer_nodes = core_xz.shape[0]
    hexes: list[list[int]] = []
    for k in range(len(etas) - 1):
        off0 = k * n_layer_nodes
        off1 = (k + 1) * n_layer_nodes
        for q in core_quads:
            n0, n1, n2, n3 = map(int, q)
            hexes.append(
                [
                    off0 + n0,
                    off0 + n1,
                    off0 + n2,
                    off0 + n3,
                    off1 + n0,
                    off1 + n1,
                    off1 + n2,
                    off1 + n3,
                ]
            )

    return fe.Mesh(points3d, np.asarray(hexes, dtype=np.int64), "hexahedron")


def generate_adaptive_mesh(config_path: str, stp_path: str, output_path: str | None = None) -> None:
    cfg = ExperimentalMeshGenConfig.from_yaml(config_path)

    if output_path is None:
        name = os.path.splitext(os.path.basename(config_path))[0]
        output_path = f"output/{name}_o_grid_exp.vtk"

    split = analyze_geometry_and_split(stp_path=stp_path, cfg=cfg)

    print(
        "Detected axes: radial_dim=%d, axial_dim=%d, normal_dim=%d"
        % (split.axes.radial_dim, split.axes.axial_dim, split.axes.normal_dim)
    )
    print(f"R_core={split.R_core:.6g}")

    rd, ad = split.axes.radial_dim, split.axes.axial_dim
    ring_ra = split.ring_points_3d[:, [rd, ad]].astype(float)
    ring_ra[:, 0] = np.abs(ring_ra[:, 0])

    ring_quads_ccw = orient_quads_ccw(ring_ra, split.ring_quads)
    mesh_ring_2d = fe.Mesh(ring_ra, ring_quads_ccw, "quad")
    mesh_ring_3d = mesh_ring_2d.revolve(
        n=int(cfg.revolve_layers),
        phi=float(cfg.revolve_angle),
        axis=1,
    )
    fix_inverted_hexes_inplace(mesh_ring_3d, label="ring_3d_exp")

    tol = max(1e-6, cfg.mesh_size * 0.05)
    ring_pts_3d = mesh_ring_3d.points
    r_ring_3d = np.hypot(ring_pts_3d[:, 0], ring_pts_3d[:, 2])
    mask_boundary = np.abs(r_ring_3d - split.R_core) < tol

    if np.count_nonzero(mask_boundary) < 2:
        raise RuntimeError(
            "Failed to locate interface nodes at R=R_core in ring_3d mesh. "
            f"(found {np.count_nonzero(mask_boundary)} nodes, tol={tol})"
        )

    y_boundary = ring_pts_3d[mask_boundary, 1]
    y_unique = np.unique(np.round(y_boundary, decimals=4))
    a_interface = np.sort(y_unique)

    if len(a_interface) > 1:
        min_dist = max(1e-6, cfg.mesh_size * 0.05)
        keep_mask = np.ones(len(a_interface), dtype=bool)
        last_val = a_interface[0]
        for i in range(1, len(a_interface)):
            if (a_interface[i] - last_val) < min_dist:
                keep_mask[i] = False
            else:
                last_val = a_interface[i]

        n_dropped = len(a_interface) - np.count_nonzero(keep_mask)
        if n_dropped > 0:
            print(f"Refined a_interface: dropped {n_dropped} ghost layers (min_dist={min_dist:.6f})")
            a_interface = a_interface[keep_mask]

    print(f"Interface axial nodes: {len(a_interface)}")

    if abs(cfg.revolve_angle - 90.0) > 1e-6:
        raise NotImplementedError("Structured core currently supports revolve_angle=90 only.")

    core_theta_divs = max(1, int(cfg.revolve_layers) - 1)
    n0_45 = core_theta_divs // 2
    n45_90 = core_theta_divs - n0_45

    a_bot_core = float(split.a_bot(np.array([split.R_core]))[0])
    a_top_core = float(split.a_top(np.array([split.R_core]))[0])
    h_ref = a_top_core - a_bot_core
    flip_winding = not (h_ref > 0)
    print(f"DEBUG: Core Height H_ref={h_ref:.6f}. Flip winding? {flip_winding}")

    n_radial = _axis_aware_core_radial_layers(cfg=cfg, r_core=split.R_core)
    radial_beta = _axis_aware_core_radial_beta(cfg=cfg, r_core=split.R_core, n_radial=n_radial)
    print(
        "[mesh-exp] core radial layers (axis-aware): requested=%d effective=%d"
        % (int(cfg.core_radial_layers), int(n_radial))
    )
    print(
        "[mesh-exp] core radial beta (axis-aware): requested=%.4g effective=%.4g"
        % (float(cfg.radial_mapping_beta), float(radial_beta))
    )

    core_xz, core_quads = create_quarter_ogrid_xz(
        split.R_core,
        n_theta0_45=n0_45,
        n_theta45_90=n45_90,
        phi_deg=cfg.revolve_angle,
        inner_ratio=cfg.core_inner_ratio,
        n_radial=n_radial,
        radial_beta=radial_beta,
        flip_winding=flip_winding,
    )

    mesh_core = _extrude_core_to_3d_axis_safe(
        core_xz=core_xz,
        core_quads=core_quads,
        a_interface=a_interface,
        r_core=split.R_core,
        a_bot=split.a_bot,
        a_top=split.a_top,
    )

    core_theta_offset_deg = float(os.environ.get("CORE_THETA_OFFSET_DEG", "-90.0"))
    if abs(core_theta_offset_deg) > 1e-12:
        mesh_core.points[:] = rotate_about_canonical_y(mesh_core.points, core_theta_offset_deg)

    fix_inverted_hexes_inplace(mesh_core, label="core_3d_exp")

    snap_interface_nodes_by_theta_layers(
        mesh_core=mesh_core,
        mesh_ring_3d=mesh_ring_3d,
        R_core=split.R_core,
        revolve_angle_deg=cfg.revolve_angle,
        revolve_layers_hint=int(cfg.revolve_layers),
        tol_r=max(1e-4, cfg.mesh_size * 1e-3),
    )

    merged = stitch_core_ring_conformal(
        mesh_core=mesh_core,
        mesh_ring_3d=mesh_ring_3d,
        R_core=split.R_core,
        tol_r=max(1e-4, cfg.mesh_size * 1e-3),
    )

    _snap_near_axis_points(merged, tol=max(1e-12, cfg.mesh_size * 1e-6))

    perm = canonical_permutation_for_target_axis(cfg.revolve_axis)
    if perm != (0, 1, 2):
        merged.points[:] = merged.points[:, list(perm)].copy()

    fix_inverted_hexes_inplace(merged, label="final_exp")

    print(f"Final mesh: nodes={len(merged.points)}, elements={len(merged.cells)}")

    save_mesh_with_optional_quadratic(
        merged,
        output_path,
        element_order=int(cfg.mesh_dimension),
    )

    msh_output = os.path.splitext(output_path)[0] + ".msh"
    if msh_output != output_path:
        print(f"Adding .msh version: {msh_output}")
        save_mesh_with_optional_quadratic(
            merged,
            msh_output,
            element_order=int(cfg.mesh_dimension),
        )


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Experimental robust mesh generator (non-production)",
    )
    parser.add_argument("config")
    parser.add_argument("stp_file")
    parser.add_argument("-o", "--output")
    args = parser.parse_args()

    generate_adaptive_mesh(args.config, args.stp_file, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
