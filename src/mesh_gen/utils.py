from __future__ import annotations
import os
import math
import shutil
import numpy as np
import felupe as fe
import meshio
import gmsh
from scipy.spatial import cKDTree
from typing import Tuple, List, Optional

def rotate_about_canonical_y(points: np.ndarray, angle_deg: float) -> np.ndarray:
    """
    Rotate points around the canonical axial axis (+Y) by angle_deg.
    This is applied BEFORE the final axis permutation to match cfg.revolve_axis.

    (x,z) -> ( cos a * x - sin a * z , sin a * x + cos a * z )
    """
    pts = np.asarray(points, dtype=float)
    a = math.radians(float(angle_deg))
    c = math.cos(a)
    s = math.sin(a)
    x = pts[:, 0].copy()
    z = pts[:, 2].copy()
    pts[:, 0] = c * x - s * z
    pts[:, 2] = s * x + c * z
    return pts

def permute_xyz(points: np.ndarray, new_from_old: Tuple[int, int, int]) -> np.ndarray:
    """
    Return a copy of points with axis permutation.
    new_from_old gives (old_index_for_newX, old_index_for_newY, old_index_for_newZ).

    Examples:
      axis=2 (axial=Z) from canonical (axial=Y): new=(X,Z,Y) -> (0,2,1)
      axis=0 (axial=X) from canonical (axial=Y): new=(Y,X,Z) -> (1,0,2)
    """
    p = np.asarray(points)
    return p[:, list(new_from_old)].copy()

def canonical_permutation_for_target_axis(target_axis: int) -> Tuple[int, int, int]:
    """
    Our *canonical* internal frame sets axial direction to +Y.
    This returns the permutation needed to move axial(Y) to the requested target axis.
    """
    if target_axis == 1:  # Y already
        return (0, 1, 2)
    if target_axis == 2:  # want axial along Z => swap Y<->Z
        return (0, 2, 1)
    if target_axis == 0:  # want axial along X => swap X<->Y
        return (1, 0, 2)
    raise ValueError("target_axis must be 0, 1, or 2.")

def orient_quads_ccw(points2d: np.ndarray, quads: np.ndarray) -> np.ndarray:
    """Ensure quad node ordering is CCW in the 2D plane.

    Why:
      - Gmsh may return mixed element orientations across surfaces.
      - Revolving quads with inconsistent orientation can create locally inverted hexes.

    Convention:
      - Positive signed area (CCW) when viewed in the +out-of-plane direction.
        For our ring mesh in (R,A), this is the standard XY plane convention.
    """
    pts = np.asarray(points2d, dtype=float)
    q = np.asarray(quads, dtype=np.int64)
    if q.size == 0:
        return q

    x = pts[q, 0]
    y = pts[q, 1]
    # Shoelace formula for quads, vectorized
    x1 = np.roll(x, -1, axis=1)
    y1 = np.roll(y, -1, axis=1)
    area2 = np.sum(x * y1 - x1 * y, axis=1)  # 2*area

    flip = area2 < 0.0
    if np.any(flip):
        q = q.copy()
        q[flip] = q[flip][:, [0, 3, 2, 1]]  # reverse winding
        print(f"[orient] Flipped {int(np.count_nonzero(flip))}/{len(q)} quads to enforce CCW orientation.")
    return q

def _hex6_volume(points: np.ndarray, hexes: np.ndarray) -> np.ndarray:
    """Return 6x signed volume based on one corner triple product.

    This detects *ordering inversions* robustly and cheaply:
      vol6 = dot( cross(p1-p0, p3-p0), p4-p0 )
    With standard Hex8 ordering, vol6 should be positive.
    """
    pts = np.asarray(points, dtype=float)
    h = np.asarray(hexes, dtype=np.int64)
    p0 = pts[h[:, 0]]
    e1 = pts[h[:, 1]] - p0
    e2 = pts[h[:, 3]] - p0
    e3 = pts[h[:, 4]] - p0
    return np.einsum("ij,ij->i", np.cross(e1, e2), e3)

def _set_mesh_cells(mesh: fe.Mesh, cells_new: np.ndarray) -> None:
    """Assign cells back to a felupe mesh, tolerating different attribute semantics."""
    try:
        mesh.cells[:] = cells_new
        return
    except Exception:
        pass
    try:
        setattr(mesh, "cells", cells_new)
        return
    except Exception:
        pass
    raise RuntimeError("Failed to set mesh.cells on the given mesh object.")

def fix_inverted_hexes_inplace(mesh: fe.Mesh, *, label: str = "") -> int:
    """Flip node ordering for Hex8 elements with negative signed volume.

    This is a safety net. If you see many flips here, the *root cause* is usually
    inconsistent 2D quad orientation prior to revolve.
    """
    if getattr(mesh, "cell_type", None) not in ("hexahedron", "hex", "hex8", None):
        # If unknown, still try if the cell array looks like Hex8.
        pass

    pts = np.asarray(mesh.points, dtype=float)
    cells = np.asarray(mesh.cells, dtype=np.int64)
    if cells.ndim != 2 or cells.shape[1] != 8:
        return 0

    vol6 = _hex6_volume(pts, cells)
    inv = vol6 <= 0.0
    n_bad = int(np.count_nonzero(inv))
    if n_bad == 0:
        return 0

    fixed = cells.copy()
    fixed[inv] = fixed[inv][:, [0, 3, 2, 1, 4, 7, 6, 5]]  # parity flip (keeps vertical edges)
    # Verify
    vol6b = _hex6_volume(pts, fixed)
    still = int(np.count_nonzero(vol6b <= 0.0))
    if still > 0:
        raise RuntimeError(
            f"[invfix] {label}: attempted to fix {n_bad} inverted hexes, but {still} are still inverted. "
            "This suggests geometric self-intersection / node collapse, not just ordering."
        )

    _set_mesh_cells(mesh, fixed)
    print(f"[invfix] {label}: fixed {n_bad} inverted hexes by flipping node ordering.")
    return n_bad

def snap_interface_nodes_core_to_ring(
    mesh_core: fe.Mesh,
    mesh_ring: fe.Mesh,
    R_core: float,
    tol_r: float = 1e-6,
    tol_snap: float = 1e-4,
) -> None:
    """
    Force the core/ring interface to be *node-identical* by snapping core interface nodes
    (r≈R_core) onto the nearest ring interface nodes.
    """
    pc = mesh_core.points
    pr = mesh_ring.points

    rc = np.hypot(pc[:, 0], pc[:, 2])
    rr = np.hypot(pr[:, 0], pr[:, 2])

    core_ids = np.where(np.abs(rc - float(R_core)) < float(tol_r))[0]
    ring_ids = np.where(np.abs(rr - float(R_core)) < float(tol_r))[0]

    if len(core_ids) == 0 or len(ring_ids) == 0:
        print(f"[snap] No interface nodes found (core={len(core_ids)}, ring={len(ring_ids)}). Skipping snap.")
        return

    tree = cKDTree(pr[ring_ids])
    dists, nn = tree.query(pc[core_ids], k=1)

    ok = dists < float(tol_snap)
    snapped = int(np.count_nonzero(ok))
    if snapped == 0:
        print(f"[snap] WARNING: 0 nodes snapped. Increase tol_snap (current {tol_snap}) or check alignment.")
        return

    # Snap in-place
    pc[core_ids[ok]] = pr[ring_ids[nn[ok]]]

    print(f"[snap] Snapped {snapped}/{len(core_ids)} core interface nodes onto ring interface nodes.")

def snap_interface_nodes_by_theta_layers(
    mesh_core: fe.Mesh,
    mesh_ring_3d: fe.Mesh,
    R_core: float,
    revolve_angle_deg: float,
    revolve_layers_hint: int,
    tol_r: float,
) -> None:
    # Robust, deterministic stitching without relying on felupe.revolve node ordering.
    # 1) Extract interface nodes by radius (r≈R_core) on both meshes
    # 2) Group nodes into theta-layers by clustering theta
    # 3) In each theta-layer, sort by axial coordinate (Y) and snap core nodes to ring nodes index-wise

    pc = mesh_core.points
    pr = mesh_ring_3d.points

    rc = np.hypot(pc[:, 0], pc[:, 2])
    rr = np.hypot(pr[:, 0], pr[:, 2])

    core_ids = np.where(np.abs(rc - float(R_core)) < float(tol_r))[0]
    ring_ids = np.where(np.abs(rr - float(R_core)) < float(tol_r))[0]

    if len(core_ids) == 0 or len(ring_ids) == 0:
        print(f"[snapL] No interface nodes found (core={len(core_ids)}, ring={len(ring_ids)}).")
        return

    # Choose theta tolerance based on expected step size
    phi = math.radians(float(revolve_angle_deg))
    # heuristic: step ~ phi / max(1, revolve_layers_hint)
    step = phi / max(1, int(revolve_layers_hint))
    theta_tol = max(1e-6, step / 10.0)

    def _theta_and_group(points: np.ndarray, ids: np.ndarray):
        x = points[ids, 0]
        z = points[ids, 2]
        th = np.arctan2(z, x)
        # map to [0, 2pi)
        two_pi = 2.0 * math.pi
        th = np.where(th < 0.0, th + two_pi, th)
        # For wedges near 0..phi, sometimes nodes near 2pi appear due to wrap. Fold them near 0.
        if phi > 0 and phi < 2.0:
            th = np.where(th > (math.pi), th - two_pi, th)

        key = np.round(th / theta_tol).astype(int)
        groups = {}
        th_sum = {}
        for k, nid, t in zip(key, ids, th):
            groups.setdefault(int(k), []).append(int(nid))
            th_sum[int(k)] = th_sum.get(int(k), 0.0) + float(t)
        layers = []
        for k, nids in groups.items():
            tmean = th_sum[k] / len(nids)
            # sort nodes by axial coordinate Y
            nids = np.array(nids, dtype=int)
            nids = nids[np.argsort(points[nids, 1])]
            layers.append((float(tmean), nids))
        layers.sort(key=lambda a: a[0])
        return layers

    core_layers = _theta_and_group(pc, core_ids)
    ring_layers = _theta_and_group(pr, ring_ids)

    if len(core_layers) != len(ring_layers):
        print(f"[snapL] WARNING: theta-layer count mismatch (core={len(core_layers)}, ring={len(ring_layers)}). "
              "Will snap by nearest theta.")
    # Match layers by nearest theta (greedy), ensuring one-to-one
    ring_used = np.zeros(len(ring_layers), dtype=bool)
    snapped_total = 0
    for t_c, ids_c in core_layers:
        # find nearest unused ring layer
        best = None
        best_d = 1e99
        for j, (t_r, ids_r) in enumerate(ring_layers):
            if ring_used[j]:
                continue
            d = abs(t_r - t_c)
            if d < best_d:
                best_d = d
                best = j
        if best is None:
            break
        ring_used[best] = True
        ids_r = ring_layers[best][1]

        m = min(len(ids_c), len(ids_r))
        if m == 0:
            continue
        pc[ids_c[:m]] = pr[ids_r[:m]]
        snapped_total += int(m)

    print(f"[snapL] Snapped {snapped_total} core interface nodes onto ring nodes (layer-based).")

def _snap_near_axis_points(mesh: fe.Mesh, tol: float) -> None:
    """Snap points very close to the rotation axis (canonical: Y axis) onto the axis."""
    pts = mesh.points
    if pts.shape[1] < 3:
        return
    r = np.hypot(pts[:, 0], pts[:, 2])
    mask = r < float(tol)
    if np.any(mask):
        pts[mask, 0] = 0.0
        pts[mask, 2] = 0.0

def _count_degenerate_cells(cells: np.ndarray) -> int:
    """Return number of cells that reference duplicate vertex ids."""
    cells = np.asarray(cells)
    if cells.ndim != 2:
        return 0
    deg = 0
    for c in cells:
        if len(set(map(int, c))) != len(c):
            deg += 1
    return deg

def stitch_core_ring_conformal(mesh_core: fe.Mesh,
                               mesh_ring_3d: fe.Mesh,
                               R_core: float,
                               tol_r: float) -> fe.Mesh:
    """Create a single conformal mesh by *index-stitching* the ring interface nodes onto the core interface nodes."""
    pc = np.asarray(mesh_core.points, dtype=float)
    pr = np.asarray(mesh_ring_3d.points, dtype=float)

    # Identify interface nodes by radius (canonical: R = hypot(X,Z))
    rc = np.hypot(pc[:, 0], pc[:, 2])
    rr = np.hypot(pr[:, 0], pr[:, 2])

    core_ids = np.where(np.abs(rc - float(R_core)) < float(tol_r))[0].astype(int)
    ring_ids = np.where(np.abs(rr - float(R_core)) < float(tol_r))[0].astype(int)

    if len(core_ids) == 0 or len(ring_ids) == 0:
        raise RuntimeError(f"[stitch] No interface nodes found (core={len(core_ids)}, ring={len(ring_ids)}).")

    # Build KDTree on core interface nodes and map each ring interface node to its nearest core node.
    tree = cKDTree(pc[core_ids])
    dist, nn = tree.query(pr[ring_ids], k=1)
    nn = nn.astype(int)

    # Tolerance in XYZ (after snap, this should be near zero). Allow slightly larger than tol_r.
    tol_xyz = max(float(tol_r) * 5.0, 1e-9)
    ok = dist <= tol_xyz

    if not np.all(ok):
        bad = int(np.sum(~ok))
        dmax = float(np.max(dist))
        print(f"[stitch] WARNING: {bad}/{len(ok)} ring interface nodes did not match within tol_xyz={tol_xyz:g} (max d={dmax:g}).")

    # Mapping: ring_point_index -> core_point_index
    ring_to_core = {int(ring_ids[i]): int(core_ids[nn[i]]) for i in range(len(ring_ids)) if ok[i]}

    # Decide which ring points to keep (drop those that map to core)
    keep = np.ones(len(pr), dtype=bool)
    for rid in ring_to_core.keys():
        keep[rid] = False

    # Build new index for all ring points (either mapped onto core indices, or appended after core points)
    core_n = len(pc)
    new_index = np.full(len(pr), -1, dtype=int)

    # 1) mapped ones
    for rid, cid in ring_to_core.items():
        new_index[rid] = cid

    # 2) kept ones -> appended
    kept_ids = np.where(keep)[0].astype(int)
    new_index[kept_ids] = core_n + np.arange(len(kept_ids), dtype=int)

    # Remap ring cells
    ring_cells = np.asarray(mesh_ring_3d.cells, dtype=int)
    ring_cells_m = new_index[ring_cells]

    # Combine points + cells
    points = np.vstack([pc, pr[kept_ids]])
    core_cells = np.asarray(mesh_core.cells, dtype=int)
    cells = np.vstack([core_cells, ring_cells_m])

    # Preserve cell type (must match)
    ct_core = getattr(mesh_core, "cell_type", None)
    ct_ring = getattr(mesh_ring_3d, "cell_type", None)
    if ct_core is None:
        raise RuntimeError("[stitch] mesh_core has no cell_type attribute.")
    if ct_ring is not None and ct_ring != ct_core:
        raise RuntimeError(f"[stitch] Cell type mismatch: core={ct_core}, ring={ct_ring}")

    merged = fe.Mesh(points, cells, ct_core)
    print(f"[stitch] Stitched ring->core on {len(ring_to_core)} nodes; kept ring nodes={len(kept_ids)}.")
    return merged

def _merge_duplicate_points_with_backoff(mesh: fe.Mesh, start_decimals: int, max_decimals: int = 12) -> fe.Mesh:
    """Merge duplicate points, but back off if it creates degenerate cells."""
    start_decimals = int(start_decimals)
    for d in range(start_decimals, max_decimals + 1):
        m = mesh.merge_duplicate_points(decimals=int(d))
        deg = _count_degenerate_cells(m.cells)
        if deg == 0:
            if d != start_decimals:
                print(f"[merge] Increased merge_decimals from {start_decimals} -> {d} to avoid degenerate cells.")
            return m
        print(f"[merge] decimals={d} produced {deg} degenerate cells; trying finer rounding...")
    print("[merge] WARNING: Could not merge points without degeneracy; keeping unmerged concatenated mesh.")
    return mesh

def save_mesh_with_optional_quadratic(mesh: fe.Mesh, output_path: str, element_order: int) -> None:
    """
    Save mesh with optional order elevation.

    - ext == ".msh":
        * 1次要素 → 直接 Gmsh2.2 で .msh 書き出し (meshio)
        * 高次要素 → 一時 .msh を Gmsh で次数上げしてから出力
    - ext == ".inp":
        * 1次/高次ともに：
            まず Gmsh2.2 の一時 .msh を作成 → Gmsh Python API で .inp へ変換
            （GUIでやっていることをそのままPythonで再現）
    - それ以外：
        * 1次要素 → meshio のデフォルト
        * 高次要素 → 一時 .msh を Gmsh で次数上げ → meshio で目的フォーマットへ変換
    """
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    meshio_mesh = mesh.as_meshio()
    ext = os.path.splitext(output_path)[1].lower()

    is_msh = (ext == ".msh")
    is_inp = (ext == ".inp")

    # ----------------------------------------------------
    # 0) Abaqus .inp は常に「Gmshで .msh → .inp 変換」経由
    # ----------------------------------------------------
    if is_inp:
        base, _ = os.path.splitext(output_path)
        tmp_lin = base + "_lin.msh"

        # まず felupe → meshio → Gmsh2.2 の線形メッシュを書き出す
        meshio.write(tmp_lin, meshio_mesh, file_format="gmsh22", binary=False)

        gmsh.initialize()
        try:
            gmsh.open(tmp_lin)
            if element_order > 1:
                gmsh.model.mesh.setOrder(int(element_order))
            # 拡張子 .inp を見て Gmsh が Abaqus フォーマットで書き出す
            gmsh.write(output_path)
            # 検証用に .msh も保存する (Gmsh v4 ASCII)
            gmsh.option.setNumber("Mesh.Binary", 0)
            gmsh.option.setNumber("Mesh.MshFileVersion", 4.1)
            gmsh.write(base + ".msh")
        finally:
            gmsh.finalize()

        try:
            os.remove(tmp_lin)
        except OSError:
            pass

        print(f"[OK] Abaqus INP saved via Gmsh: {output_path}")
        print(f"[OK] Verification MSH saved: {base}.msh")
        return

    # ----------------------------------------------------
    # 1) 1次要素 (Hex8) で .msh / その他 を保存
    # ----------------------------------------------------
    if element_order == 1:
        if is_msh:
            # これまでどおり Gmsh2.2 ASCII で .msh 保存
            meshio.write(output_path, meshio_mesh, file_format="gmsh22", binary=False)
        else:
            # .vtkなどは meshio の標準出力
            meshio.write(output_path, meshio_mesh, binary=False)

        print(f"[OK] Mesh saved: {output_path}")
        return

    # ----------------------------------------------------
    # 2) 高次要素 (2次以上) で .msh / その他 を保存
    # ----------------------------------------------------
    base, _ = os.path.splitext(output_path)
    tmp_lin = base + "_lin.msh"
    tmp_ho  = base + f"_order{element_order}.msh"

    # まず線形メッシュを Gmsh2.2 で一時保存
    meshio.write(tmp_lin, meshio_mesh, file_format="gmsh22", binary=False)

    gmsh.initialize()
    try:
        gmsh.open(tmp_lin)
        gmsh.model.mesh.setOrder(int(element_order))
        gmsh.write(tmp_ho)
    finally:
        gmsh.finalize()

    if is_msh:
        # 高次 .msh：Gmsh出力をそのまま最終ファイルに
        shutil.move(tmp_ho, output_path)
    else:
        # それ以外：Gmsh出力の .msh を meshio で読み直して変換
        m = meshio.read(tmp_ho)
        meshio.write(output_path, m, binary=False)

    # 一時ファイル後片付け
    for p in (tmp_lin, tmp_ho):
        try:
            os.remove(p)
        except OSError:
            pass

    print(f"[OK] Higher-order mesh saved: {output_path}")
