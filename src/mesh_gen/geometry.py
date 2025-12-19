from __future__ import annotations
import os
import numpy as np
import gmsh
from scipy.interpolate import interp1d
from dataclasses import dataclass
from typing import Tuple, Sequence, List, Iterable, Callable, Optional

@dataclass(frozen=True)
class AxisInfo:
    """How the imported 2D profile is embedded in 3D coordinates."""
    radial_dim: int   # coordinate in the profile plane representing radius R
    axial_dim: int    # coordinate in the profile plane representing axial coordinate A (rotation axis direction)
    normal_dim: int   # profile plane normal (should have ~zero thickness)

@dataclass(frozen=True)
class SplitResult:
    ring_points_3d: np.ndarray           # (N,3) points used by the ring quad mesh
    ring_quads: np.ndarray               # (M,4) quad connectivity (0-based indices into ring_points_3d)
    R_core: float
    axes: AxisInfo
    a_bot: Callable[[np.ndarray], np.ndarray]  # axial bottom surface function A_bot(R)
    a_top: Callable[[np.ndarray], np.ndarray]  # axial top surface function A_top(R)

def _unique_sorted_xy(x, y, decimals: int = 12):
    """Sort by x and deduplicate near-equal x values by averaging y."""
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if x.size == 0:
        return x, y
    order = np.argsort(x)
    x, y = x[order], y[order]
    xr = np.round(x, int(decimals))
    uniq, inv = np.unique(xr, return_inverse=True)
    y_acc = np.zeros_like(uniq, dtype=float)
    cnt = np.zeros_like(uniq, dtype=int)
    for k, yy in zip(inv, y):
        y_acc[k] += float(yy)
        cnt[k] += 1
    y_acc /= np.maximum(cnt, 1)
    return uniq.astype(float), y_acc.astype(float)

def safe_interp1d(x, y):
    """interp1d wrapper that tolerates duplicate x values and avoids NaN at R≈0."""
    xu, yu = _unique_sorted_xy(x, y, decimals=12)
    if len(xu) == 0:
        return lambda r: np.zeros_like(np.asarray(r, dtype=float).reshape(-1))
    if len(xu) == 1:
        c = float(yu[0])
        return lambda r: np.full_like(np.asarray(r, dtype=float).reshape(-1), c, dtype=float)
    f = interp1d(
        xu, yu, kind="linear",
        bounds_error=False,
        fill_value=(float(yu[0]), float(yu[-1])),
        assume_sorted=True,
    )
    return lambda r: np.asarray(f(np.asarray(r, dtype=float).reshape(-1)), dtype=float).reshape(-1)

def _compute_global_bounds(entities: Sequence[Tuple[int, int]]) -> Tuple[np.ndarray, np.ndarray]:
    """Return (mins, maxs) for x,y,z."""
    mins = np.array([+1e20, +1e20, +1e20], dtype=float)
    maxs = np.array([-1e20, -1e20, -1e20], dtype=float)
    for dim, tag in entities:
        bb = gmsh.model.occ.getBoundingBox(dim, tag)
        mins = np.minimum(mins, np.array(bb[:3], dtype=float))
        maxs = np.maximum(maxs, np.array(bb[3:], dtype=float))
    return mins, maxs

def _detect_profile_axes(mins: np.ndarray, maxs: np.ndarray, revolve_axis: int, eps: float = 1e-6) -> AxisInfo:
    """Detect which coordinate is the profile plane normal, then derive radial/axial dims."""
    ranges = maxs - mins
    normal_dim = int(np.argmin(ranges))
    if ranges[normal_dim] > eps:
        # Not strictly planar -> could still be planar-ish, but much less reliable.
        raise RuntimeError(
            f"STEP profile does not look planar (min range={ranges.min():.3e}). "
            f"Expected one dimension to be ~0. Bounds mins={mins}, maxs={maxs}"
        )

    plane_dims = [0, 1, 2]
    plane_dims.remove(normal_dim)

    if revolve_axis not in plane_dims:
        raise RuntimeError(
            f"revolve_axis={revolve_axis} is not in the detected profile plane dims {plane_dims}. "
            f"Re-check STEP orientation or revolve_axis setting."
        )

    axial_dim = revolve_axis
    plane_dims.remove(axial_dim)
    radial_dim = plane_dims[0]

    return AxisInfo(radial_dim=radial_dim, axial_dim=axial_dim, normal_dim=normal_dim)

def _split_surfaces_by_radius(surfaces_2d: Iterable[int], axes: AxisInfo, R_core: float, tol: float = 1e-5
                             ) -> Tuple[List[int], List[int]]:
    """Classify 2D surfaces into outer (R>=R_core) and inner (R<=R_core)."""
    outer, inner = [], []
    rd = axes.radial_dim
    for s_tag in surfaces_2d:
        bb = gmsh.model.occ.getBoundingBox(2, s_tag)
        r_min = bb[rd]
        r_max = bb[rd + 3]
        if r_max <= R_core + tol:
            inner.append(s_tag)
        elif r_min >= R_core - tol:
            outer.append(s_tag)
        else:
            # Edge case: straddling due to tolerances. Use CoM.
            com = gmsh.model.occ.getCenterOfMass(2, s_tag)
            (outer if com[rd] > R_core else inner).append(s_tag)
    return outer, inner

def _extract_profile_a_of_R(inner_surfaces: Sequence[int], axes: AxisInfo, R_core: float) -> Tuple[interp1d, interp1d]:
    """
    Extract boundary curves for the inner region and build A_top(R), A_bot(R).
    
    Returns interpolation functions A(R) where R is the positive radial distance.
    """
    rd, ad = axes.radial_dim, axes.axial_dim

    # Collect boundary curves of inner surfaces
    curve_tags: set[int] = set()
    for s_tag in inner_surfaces:
        bnd = gmsh.model.getBoundary([(2, s_tag)], combined=False, oriented=False, recursive=False)
        for dim, tag in bnd:
            if dim == 1:
                curve_tags.add(tag)

    # Filter out the interface curve at R=R_core and keep an axis curve at R=0 if present.
    valid_curves: List[int] = []
    axis_curve: int | None = None

    for c_tag in curve_tags:
        bb = gmsh.model.occ.getBoundingBox(1, c_tag)
        r0, r1 = bb[rd], bb[rd + 3]
        
        # Check radius using absolute values (distance from axis)
        # Interface curve: R approx R_core
        if abs(abs(r0) - R_core) < 1e-4 and abs(abs(r1) - R_core) < 1e-4:
            continue
        # Axis curve: R approx 0
        if abs(r0) < 1e-4 and abs(r1) < 1e-4:
            axis_curve = c_tag
            continue
            
        valid_curves.append(c_tag)

    if not valid_curves and axis_curve is None:
        raise RuntimeError("Failed to extract inner profile curves (no valid boundary curves found).")

    samples: List[Tuple[float, float]] = []

    def _sample_curve(c_tag: int, n: int = 41):
        pmin, pmax = gmsh.model.getParametrizationBounds(1, c_tag)
        for i in range(n):
            t = pmin + (pmax - pmin) * i / (n - 1)
            xyz = np.asarray(gmsh.model.getValue(1, c_tag, [float(t)]), dtype=float).reshape(-1)
            # Use abs() for radial coordinate to ensure we map R(distance) -> A(axial)
            samples.append((abs(float(xyz[rd])), float(xyz[ad])))

    for c_tag in valid_curves:
        _sample_curve(c_tag, n=41)

    if axis_curve is not None:
        # Add its endpoints to help interpolation at R=0
        pmin, pmax = gmsh.model.getParametrizationBounds(1, axis_curve)
        xyz0 = np.asarray(gmsh.model.getValue(1, axis_curve, [float(pmin)]), dtype=float).reshape(-1)
        xyz1 = np.asarray(gmsh.model.getValue(1, axis_curve, [float(pmax)]), dtype=float).reshape(-1)
        samples.append((0.0, float(xyz0[ad])))
        samples.append((0.0, float(xyz1[ad])))

    rz = np.array(samples, dtype=float)
    if rz.size == 0:
        raise RuntimeError("Curve sampling produced no points.")

    # Split into top/bottom by mean A
    a_mean = float(np.mean(rz[:, 1]))
    top = rz[rz[:, 1] > a_mean]
    bot = rz[rz[:, 1] <= a_mean]

    if len(top) < 2 or len(bot) < 2:
        raise RuntimeError(
            "Top/bottom curve classification looks degenerate. "
            "Heuristic split by mean axial value failed."
        )

    # Debug output to verify classification
    print(f"DEBUG: Top curves: {len(top)} points, A_mean={np.mean(top[:, 1]):.4f}, A_range=[{np.min(top[:, 1]):.4f}, {np.max(top[:, 1]):.4f}]")
    print(f"DEBUG: Bot curves: {len(bot)} points, A_mean={np.mean(bot[:, 1]):.4f}, A_range=[{np.min(bot[:, 1]):.4f}, {np.max(bot[:, 1]):.4f}]")

    top = top[np.argsort(top[:, 0])]
    bot = bot[np.argsort(bot[:, 0])]

    # Ensure R=0 exists by extrapolation if needed
    def _ensure_r0(arr: np.ndarray) -> np.ndarray:
        if arr[0, 0] <= 1e-8:
            return arr
        r0, r1 = arr[0, 0], arr[1, 0]
        a0, a1 = arr[0, 1], arr[1, 1]
        a_at_0 = a0 + (0.0 - r0) * (a1 - a0) / (r1 - r0)
        return np.vstack([[0.0, a_at_0], arr])

    top = _ensure_r0(top)
    bot = _ensure_r0(bot)

    a_top = safe_interp1d(top[:, 0], top[:, 1])
    a_bot = safe_interp1d(bot[:, 0], bot[:, 1])

    return a_bot, a_top

# Need to import _mesh_outer_ring_quads from ring_mesh to use it in analyze_geometry_and_split?
# No, analyze_geometry_and_split calls _mesh_outer_ring_quads.
# To avoid circular imports, I should probably pass the meshing function or import it inside the function.
# Or better, move analyze_geometry_and_split to main or a higher level controller, OR put _mesh_outer_ring_quads in geometry?
# The user plan said:
# geometry.py: analyze_geometry_and_split
# ring_mesh.py: _mesh_outer_ring_quads
# So analyze_geometry_and_split depends on ring_mesh.
# I will import it inside the function to avoid circular dependency if ring_mesh needs AxisInfo from geometry.

def analyze_geometry_and_split(stp_path: str, mesh_size: float, revolve_axis: int, core_ratio: float) -> SplitResult:
    """High-level wrapper around Gmsh: import -> split -> extract curves -> mesh outer ring."""
    # Import here to avoid circular dependency
    from .ring_mesh import mesh_outer_ring_quads

    if not os.path.exists(stp_path):
        raise FileNotFoundError(stp_path)

    gmsh.initialize()
    gmsh.model.add("adaptive_mesh_gen")
    try:
        shapes = gmsh.model.occ.importShapes(stp_path)
        gmsh.model.occ.synchronize()

        mins, maxs = _compute_global_bounds(shapes)
        axes = _detect_profile_axes(mins, maxs, revolve_axis=revolve_axis)

        rd = axes.radial_dim
        r_min = mins[rd]
        r_max = maxs[rd]
        R_abs_max = max(abs(r_min), abs(r_max))
        R_core = float(R_abs_max * core_ratio)

        # Create cut line at R=R_core spanning the axial extent (+ margin).
        ad = axes.axial_dim
        p1 = [0.0, 0.0, 0.0]
        p2 = [0.0, 0.0, 0.0]
        p1[rd] = R_core
        p2[rd] = R_core

        margin = max(1.0, 0.05 * float(maxs[ad] - mins[ad]))
        p1[ad] = float(mins[ad] - margin)
        p2[ad] = float(maxs[ad] + margin)

        pt1 = gmsh.model.occ.addPoint(*p1)
        pt2 = gmsh.model.occ.addPoint(*p2)
        cut_line = gmsh.model.occ.addLine(pt1, pt2)
        gmsh.model.occ.synchronize()

        frag_out, _ = gmsh.model.occ.fragment(list(shapes), [(1, cut_line)])
        gmsh.model.occ.synchronize()

        surfaces_2d = [tag for dim, tag in frag_out if dim == 2]
        if not surfaces_2d:
            raise RuntimeError("No 2D surfaces found after fragment(). STEP may not define a 2D profile surface.")

        outer_surfaces, inner_surfaces = _split_surfaces_by_radius(surfaces_2d, axes, R_core)
        if not outer_surfaces:
            raise RuntimeError("Failed to identify outer ring surfaces after split.")

        a_bot, a_top = _extract_profile_a_of_R(inner_surfaces, axes, R_core)
        ring_points, ring_quads = mesh_outer_ring_quads(mesh_size, outer_surfaces, axes)

        return SplitResult(
            ring_points_3d=ring_points,
            ring_quads=ring_quads,
            R_core=R_core,
            axes=axes,
            a_bot=a_bot,
            a_top=a_top,
        )
    finally:
        gmsh.finalize()
