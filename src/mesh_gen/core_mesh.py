from __future__ import annotations
import math
import numpy as np
import felupe as fe
from typing import Tuple, List, Callable, Optional

def _enforce_outer_arc_nodes(points_xz: np.ndarray, nx: int, ny: int, R: float, phi_deg: float) -> None:
    """
    Modify points_xz in-place so that the outer arc (r=R) nodes coincide with the same
    angular discretization used by felupe.Mesh.revolve, i.e. uniform theta spacing.
    """
    points_xz[:] = np.asarray(points_xz, dtype=float)
    n = int(nx + ny)
    if n <= 0:
        return
    phi = np.deg2rad(float(phi_deg))
    thetas = np.linspace(0.0, phi, n + 1)

    # Node indexing: id = i + j*(nx+1)
    ids_u1 = [nx + j * (nx + 1) for j in range(ny + 1)]
    ids_v1 = [i + ny * (nx + 1) for i in range(nx - 1, -1, -1)]  # exclude corner i=nx already in ids_u1
    boundary_ids = ids_u1 + ids_v1

    if len(boundary_ids) != len(thetas):
        raise RuntimeError(
            f"Core boundary node count mismatch: boundary_ids={len(boundary_ids)} vs theta={len(thetas)} "
            f"(nx={nx}, ny={ny})"
        )

    for nid, th in zip(boundary_ids, thetas):
        points_xz[nid, 0] = float(R * np.cos(th))
        points_xz[nid, 1] = float(R * np.sin(th))

def create_quarter_ogrid_xz(
    R: float,
    n_theta0_45: int,
    n_theta45_90: int,
    phi_deg: float = 90.0,
    *,
    inner_ratio: float = 0.35,
    n_radial: int | None = None,
    radial_beta: float = 2.0,
    flip_winding: bool = False,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Create a *true O-grid* core 2D mesh in canonical XZ plane.
    If flip_winding is True, reverses the connectivity of quads (CW instead of CCW)
    to produce Normal +Y instead of -Y.
    """
    nx = int(n_theta45_90)
    ny = int(n_theta0_45)

    total_segments = nx + ny
    if total_segments < 1:
        # Degenerate: single quad (very low resolution); keep it robust.
        eps = max(1e-9, float(R) * 1e-9)
        pts = np.asarray([[0.0, 0.0], [float(R), 0.0], [float(R), eps], [0.0, eps]], dtype=float)
        quads = np.asarray([[0, 1, 2, 3]], dtype=np.int64)
        if flip_winding:
             quads = np.asarray([[0, 3, 2, 1]], dtype=np.int64)
        return pts, quads

    phi = math.radians(float(phi_deg))
    thetas = np.linspace(0.0, phi, total_segments + 1, dtype=float)

    # ------------------------------------------------------------
    # Inner block: "rectangle" whose corner ray matches the split index
    # ------------------------------------------------------------
    inner_ratio = float(inner_ratio)
    inner_ratio = max(1e-6, min(inner_ratio, 0.95))
    a_base = inner_ratio * float(R)

    # Ray angle at split index (k = ny). We choose a_x, a_z so that the ray hits the corner.
    k_split = int(np.clip(ny, 0, total_segments))
    theta_split = float(thetas[k_split])
    tan_split = math.tan(theta_split)

    eps = 1e-12
    tan_eff = tan_split
    if abs(tan_eff) < eps:
        tan_eff = 1.0  # near 0°, avoid collapsing the rectangle

    # Keep constant area a_base^2 while adjusting aspect to match the split angle:
    #   a_z / a_x = tan(theta_split),  a_x * a_z = a_base^2.
    tan_eff = max(1e-9, min(tan_eff, 1e9))
    a_x = a_base / math.sqrt(tan_eff)
    a_z = a_base * math.sqrt(tan_eff)

    # Fit strictly inside the circle (safety margin)
    scale = min(0.98 * float(R) / max(a_x, 1e-12), 0.98 * float(R) / max(a_z, 1e-12), 1.0)
    a_x *= scale
    a_z *= scale

    # Boundary nodes that correspond 1:1 with theta layers:
    # Right edge (x=a_x) for k=0..ny, and top edge (z=a_z) for k=ny..Nθ-1.
    z_right = np.zeros(ny + 1, dtype=float)
    for j in range(ny + 1):
        th = float(thetas[j])
        z = a_x * math.tan(th) if abs(math.cos(th)) > 1e-12 else a_z
        z_right[j] = float(np.clip(z, 0.0, a_z))

    x_top = np.zeros(nx + 1, dtype=float)
    for i in range(nx + 1):
        th = float(thetas[total_segments - i])  # reverse so i=0 -> theta=phi
        if abs(math.sin(th)) < 1e-12:
            x = a_x
        else:
            t = math.tan(th)
            if abs(t) < 1e-12:
                x = a_x
            else:
                x = a_z / t
        x_top[i] = float(np.clip(x, 0.0, a_x))

    # Coons patch (transfinite interpolation) to fill the inner block with structured quads
    ncols = nx + 1
    nrows = ny + 1
    inner_pts = np.zeros((ncols * nrows, 2), dtype=float)

    P00 = np.array([0.0, 0.0], dtype=float)
    P10 = np.array([a_x, 0.0], dtype=float)
    P01 = np.array([0.0, a_z], dtype=float)
    P11 = np.array([a_x, a_z], dtype=float)

    for j in range(nrows):
        t = 0.0 if ny == 0 else j / float(ny)
        L = np.array([0.0, a_z * t], dtype=float)
        Rb = np.array([a_x, z_right[j]], dtype=float)
        for i in range(ncols):
            s = 0.0 if nx == 0 else i / float(nx)
            B = np.array([a_x * s, 0.0], dtype=float)
            T = np.array([x_top[i], a_z], dtype=float)

            P = (1 - t) * B + t * T + (1 - s) * L + s * Rb
            P -= (1 - s) * (1 - t) * P00 + s * (1 - t) * P10 + (1 - s) * t * P01 + s * t * P11

            inner_pts[i + j * ncols, :] = P

    inner_quads: List[List[int]] = []
    for j in range(ny):
        for i in range(nx):
            n0 = i + j * ncols
            n1 = (i + 1) + j * ncols
            n2 = (i + 1) + (j + 1) * ncols
            n3 = i + (j + 1) * ncols
            if flip_winding:
                inner_quads.append([n0, n3, n2, n1])
            else:
                inner_quads.append([n0, n1, n2, n3])

    # ------------------------------------------------------------
    # Outer O-grid block: reuse inner boundary nodes (m=0), add m=1..n_radial
    # ------------------------------------------------------------
    if n_radial is None:
        n_radial = max(2, int(round(total_segments / 2)))
    n_radial = int(max(1, n_radial))

    radial_beta = float(radial_beta)
    if radial_beta <= 0:
        radial_beta = 1.0

    def _eta(m: int) -> float:
        # beta>1 clusters nodes toward the outer arc (eta closer to 1)
        p = m / float(n_radial)
        return p ** (1.0 / radial_beta)

    # Map theta layer k -> node id on the inner boundary of the outer block (L-shape)
    outer_ids = -np.ones((total_segments + 1, n_radial + 1), dtype=np.int64)

    # m=0 comes from inner block boundary
    for k in range(total_segments + 1):
        if k <= ny:
            # right edge: i=nx, j=k
            nid = nx + k * ncols
        else:
            # top edge: j=ny, i = (total_segments - k)
            i = total_segments - k
            nid = i + ny * ncols
        outer_ids[k, 0] = int(nid)

    pts_list: List[List[float]] = inner_pts.tolist()
    for k, th in enumerate(thetas):
        outer = np.array([float(R) * math.cos(float(th)), float(R) * math.sin(float(th))], dtype=float)
        inner = inner_pts[int(outer_ids[k, 0])]
        for m in range(1, n_radial + 1):
            eta = _eta(m)
            pnt = (1 - eta) * inner + eta * outer
            outer_ids[k, m] = len(pts_list)
            pts_list.append([float(pnt[0]), float(pnt[1])])

    points = np.asarray(pts_list, dtype=float)

    quads: List[List[int]] = []
    quads.extend(inner_quads)

    for k in range(total_segments):
        for m in range(n_radial):
            n0 = int(outer_ids[k, m])
            n1 = int(outer_ids[k + 1, m])
            n2 = int(outer_ids[k + 1, m + 1])
            n3 = int(outer_ids[k, m + 1])
            if flip_winding:
                quads.append([n0, n3, n2, n1])
            else:
                quads.append([n0, n1, n2, n3])

    return points, np.asarray(quads, dtype=np.int64)

def extrude_core_to_3d(
    core_xz: np.ndarray,
    core_quads: np.ndarray,
    a_interface: np.ndarray,
    R_core: float,
    a_bot: Callable[[np.ndarray], np.ndarray],
    a_top: Callable[[np.ndarray], np.ndarray],
    revolve_angle_deg: float = 90.0,
) -> fe.Mesh:
    """
    Build the inner core hex mesh:
    - 2D points are in XZ plane (radius = hypot(X,Z))
    - axial coordinate is Y
    - axial layers come from the interface nodes at R_core (to match ring's axial spacing)
    - (A_bot(R), A_top(R)) map the core top/bottom to the true profile
    - Outer boundary nodes (R ≈ R_core) are transformed to match ring's revolve coordinates
    """
    core_xz = np.asarray(core_xz, dtype=float)
    core_quads = np.asarray(core_quads, dtype=np.int64)
    a_interface = np.asarray(a_interface, dtype=float)

    # Normalize axial distribution using the interface (R = R_core)
    A_bot_ref = float(a_bot(np.array([R_core]))[0])
    A_top_ref = float(a_top(np.array([R_core]))[0])
    H_ref = A_top_ref - A_bot_ref
    if abs(H_ref) < 1e-12:
        etas = np.linspace(0.0, 1.0, len(a_interface))
    else:
        etas = (a_interface - A_bot_ref) / H_ref

    # Precompute per-node A_bot/A_top for this radius
    r_nodes = np.hypot(core_xz[:, 0], core_xz[:, 1])
    A_bot_nodes = a_bot(r_nodes)
    A_top_nodes = a_top(r_nodes)

    # Identify boundary nodes (R ≈ R_core) that need revolve coordinate transformation
    tol_boundary = max(1e-6, float(R_core) * 0.01)
    is_boundary = np.abs(r_nodes - float(R_core)) < tol_boundary
    
    # For boundary nodes, compute theta from current XZ coordinates
    # Ring uses revolve: (R, A) -> (R*cos(θ), A, R*sin(θ)) where θ ∈ [0, phi]
    # Core 2D is in XZ plane: X = R*cos(θ), Z = R*sin(θ) (but currently Z is just from 2D mesh)
    # We need to ensure boundary nodes have Z = R_core * sin(θ) where θ = atan2(Z, X)
    theta_boundary = np.arctan2(core_xz[is_boundary, 1], core_xz[is_boundary, 0])
    
    # Create corrected 2D coordinates for boundary nodes
    core_xz_corrected = core_xz.copy()
    core_xz_corrected[is_boundary, 0] = float(R_core) * np.cos(theta_boundary)
    core_xz_corrected[is_boundary, 1] = float(R_core) * np.sin(theta_boundary)

    points_layers: List[np.ndarray] = []
    for eta in etas:
        A_layer = A_bot_nodes + float(eta) * (A_top_nodes - A_bot_nodes)  # axial(Y)
        pts = np.column_stack([core_xz_corrected[:, 0], A_layer, core_xz_corrected[:, 1]])  # (X, Y, Z)
        points_layers.append(pts)

    points3d = np.vstack(points_layers)

    n_layer_nodes = core_xz.shape[0]
    hexes: List[List[int]] = []
    for k in range(len(etas) - 1):
        off0 = k * n_layer_nodes
        off1 = (k + 1) * n_layer_nodes
        for q in core_quads:
            n0, n1, n2, n3 = map(int, q)
            hexes.append([off0 + n0, off0 + n1, off0 + n2, off0 + n3,
                          off1 + n0, off1 + n1, off1 + n2, off1 + n3])

    return fe.Mesh(points3d, np.asarray(hexes, dtype=np.int64), "hexahedron")

