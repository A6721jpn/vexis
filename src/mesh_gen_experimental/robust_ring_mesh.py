from __future__ import annotations

import re
from typing import Sequence

import gmsh
import numpy as np

from src.mesh_gen.geometry import AxisInfo


_SINGULAR_DETAIL_RE = re.compile(
    r"Face\s+(\d+),\s+singular node\s+(\d+),\s+failed to assign to irregular vertex",
    flags=re.IGNORECASE,
)
_SUMMARY_WARN_RE = re.compile(r"\b(\d+)\s+warnings\b", flags=re.IGNORECASE)


def _set_num(name: str, value: float) -> None:
    try:
        gmsh.option.setNumber(name, float(value))
    except Exception:
        pass


def _apply_common_mesh_options(mesh_size: float) -> None:
    _set_num("Mesh.CharacteristicLengthMin", mesh_size)
    _set_num("Mesh.CharacteristicLengthMax", mesh_size)
    _set_num("Mesh.ElementOrder", 1)


def _apply_quasi_structured_options() -> None:
    """Keep the same baseline quasi-structured quad meshing path."""
    _set_num("Mesh.RecombineAll", 1)
    _set_num("Mesh.RecombinationAlgorithm", 2)
    _set_num("Mesh.SubdivisionAlgorithm", 1)
    _set_num("Mesh.Smoothing", 12)
    _set_num("Mesh.Optimize", 1)
    _set_num("Mesh.OptimizeNetgen", 1)
    _set_num("Mesh.Algorithm", 11)


def _curve_length(c_tag: int) -> float:
    try:
        return float(gmsh.model.occ.getMass(1, c_tag))
    except Exception:
        try:
            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(1, c_tag)
            return float(((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5)
        except Exception:
            return 0.0


def _curve_endpoints(c_tag: int) -> tuple[int, int] | None:
    bnd = gmsh.model.getBoundary([(1, c_tag)], oriented=False, recursive=False)
    pts = [t for (d, t) in bnd if d == 0]
    if len(pts) < 2:
        return None
    uniq: list[int] = []
    for p in pts:
        if p not in uniq:
            uniq.append(p)
    if len(uniq) < 2:
        return None
    return uniq[0], uniq[-1]


def _apply_transfinite_constraints(mesh_size: float, outer_surfaces: Sequence[int]) -> None:
    curve_n: dict[int, int] = {}
    transfinite_surfaces: list[int] = []

    for s_tag in outer_surfaces:
        bnd = gmsh.model.getBoundary([(2, s_tag)], oriented=False, recursive=False)
        curves = [t for (d, t) in bnd if d == 1]

        cu: list[int] = []
        for c in curves:
            if c not in cu:
                cu.append(c)
        if len(cu) != 4:
            continue

        endpoints = [_curve_endpoints(c) for c in cu]
        if any(e is None for e in endpoints):
            continue

        ep_sets = [set(e) for e in endpoints if e is not None]
        opp: list[tuple[int, int]] = []
        for i in range(4):
            for j in range(i + 1, 4):
                if ep_sets[i].isdisjoint(ep_sets[j]):
                    opp.append((i, j))
        if len(opp) != 2:
            continue

        local_n = [max(2, int(round(_curve_length(c) / mesh_size)) + 1) for c in cu]
        for i, j in opp:
            n = max(local_n[i], local_n[j])
            local_n[i] = n
            local_n[j] = n

        for c, n in zip(cu, local_n):
            curve_n[c] = max(curve_n.get(c, 0), n)
        transfinite_surfaces.append(s_tag)

    for c, n in curve_n.items():
        try:
            gmsh.model.mesh.setTransfiniteCurve(c, int(n))
        except Exception:
            pass

    for s in transfinite_surfaces:
        try:
            gmsh.model.mesh.setTransfiniteSurface(s)
            gmsh.model.mesh.setRecombine(2, s)
        except Exception:
            pass


def _parse_warning_counts(log_lines: Sequence[str]) -> tuple[int, int, dict[int, int], dict[tuple[int, int], int]]:
    singular_total = 0
    summary_total = 0
    face_hits: dict[int, int] = {}
    node_hits: dict[tuple[int, int], int] = {}
    for line in log_lines:
        m = _SINGULAR_DETAIL_RE.search(line)
        if m:
            face_id = int(m.group(1))
            node_id = int(m.group(2))
            singular_total += 1
            face_hits[face_id] = face_hits.get(face_id, 0) + 1
            key = (face_id, node_id)
            node_hits[key] = node_hits.get(key, 0) + 1
            continue

        m2 = _SUMMARY_WARN_RE.search(line)
        if m2:
            summary_total = max(summary_total, int(m2.group(1)))

    if summary_total == 0:
        summary_total = sum(1 for line in log_lines if "warning" in line.lower())

    return singular_total, summary_total, face_hits, node_hits


def _emit_singular_face_report(
    face_hits: dict[int, int],
    node_hits: dict[tuple[int, int], int],
    *,
    axes: AxisInfo,
) -> None:
    if not face_hits:
        return

    print(
        "[mesh-singular] total_hits=%d unique_faces=%d unique_face_nodes=%d"
        % (sum(face_hits.values()), len(face_hits), len(node_hits))
    )
    rd = axes.radial_dim
    ad = axes.axial_dim

    for face_id, hits in sorted(face_hits.items(), key=lambda kv: (-kv[1], kv[0])):
        try:
            bb = gmsh.model.getBoundingBox(2, face_id)
            r0, a0 = bb[rd], bb[ad]
            r1, a1 = bb[rd + 3], bb[ad + 3]
            print(
                "[mesh-singular] face=%d hits=%d radial=[%.6g, %.6g] axial=[%.6g, %.6g]"
                % (face_id, hits, r0, r1, a0, a1)
            )
        except Exception:
            print(
                "[mesh-singular] face=%d hits=%d radial=[n/a, n/a] axial=[n/a, n/a]"
                % (face_id, hits)
            )

    for (face_id, node_id), hits in sorted(node_hits.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1])):
        print(
            "[mesh-singular-node] face=%d node=%d hits=%d"
            % (face_id, node_id, hits)
        )


def _extract_surface_elements(outer_surfaces: Sequence[int]) -> tuple[np.ndarray, np.ndarray, int, int]:
    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    node_tags = np.asarray(node_tags, dtype=np.int64)
    points_all = np.asarray(node_coords, dtype=float).reshape(-1, 3)
    node_map = {int(tag): i for i, tag in enumerate(node_tags)}

    quads: list[np.ndarray] = []
    tri_count = 0
    for s_tag in outer_surfaces:
        elem_types, _, elem_node_tags = gmsh.model.mesh.getElements(2, s_tag)
        for etype, enodes in zip(elem_types, elem_node_tags):
            if etype == 3:
                en = np.asarray(enodes, dtype=np.int64).reshape(-1, 4)
                mapped = np.vectorize(node_map.__getitem__)(en)
                quads.append(mapped)
            elif etype == 2:
                tri_count += len(enodes) // 3

    if not quads:
        return np.empty((0, 3), dtype=float), np.empty((0, 4), dtype=np.int64), tri_count, 0

    q = np.vstack(quads).astype(np.int64)
    used = np.unique(q)
    old_to_new = {int(old): i for i, old in enumerate(used)}
    points = points_all[used]
    q = np.vectorize(old_to_new.__getitem__)(q).astype(np.int64)
    return points, q, tri_count, int(len(q))


def _mesh_outer_surfaces_only(outer_surfaces: Sequence[int]) -> tuple[list[tuple[int, int]], float]:
    """Restrict meshing scope to requested surfaces only.

    Returns:
      - hidden entities (to restore)
      - previous Mesh.MeshOnlyVisible option value
    """
    all_surfaces = gmsh.model.getEntities(2)
    outer_set = {int(s) for s in outer_surfaces}
    hidden: list[tuple[int, int]] = []
    for d, tag in all_surfaces:
        if d != 2:
            continue
        if int(tag) not in outer_set:
            hidden.append((2, int(tag)))

    if hidden:
        try:
            gmsh.model.setVisibility(hidden, 0, recursive=True)
        except Exception:
            hidden = []

    try:
        gmsh.model.setVisibility([(2, int(s)) for s in outer_surfaces], 1, recursive=True)
    except Exception:
        pass

    prev_only_visible = 0.0
    try:
        prev_only_visible = float(gmsh.option.getNumber("Mesh.MeshOnlyVisible"))
    except Exception:
        prev_only_visible = 0.0

    try:
        gmsh.option.setNumber("Mesh.MeshOnlyVisible", 1)
    except Exception:
        pass

    if hidden:
        print(
            "[mesh-exp] restricted meshing surfaces: outer=%d hidden=%d"
            % (len(outer_surfaces), len(hidden))
        )
    return hidden, prev_only_visible


def _restore_mesh_visibility(
    hidden: Sequence[tuple[int, int]],
    prev_only_visible: float,
) -> None:
    if hidden:
        try:
            gmsh.model.setVisibility(list(hidden), 1, recursive=True)
        except Exception:
            pass
    try:
        gmsh.option.setNumber("Mesh.MeshOnlyVisible", float(prev_only_visible))
    except Exception:
        pass


def mesh_outer_ring_quads_robust(
    mesh_size: float,
    outer_surfaces: Sequence[int],
    axes: AxisInfo,
    *,
    strategies: Sequence[str],
    singular_warning_target: int = 0,
) -> tuple[np.ndarray, np.ndarray, dict[str, int | str]]:
    """Experimental path fixed to baseline quasi-structured quad meshing.

    Note:
      Requested behavior is now single-path only (no multi-stage fallback).
      ``strategies`` is kept only for backward-compatible signature.
    """
    _ = strategies

    gmsh.model.mesh.clear()
    _apply_common_mesh_options(mesh_size)
    _apply_quasi_structured_options()
    _apply_transfinite_constraints(mesh_size, outer_surfaces)
    hidden_surfaces, prev_only_visible = _mesh_outer_surfaces_only(outer_surfaces)

    logger_started = False
    try:
        try:
            gmsh.logger.start()
            logger_started = True
        except Exception:
            logger_started = False

        gmsh.model.mesh.generate(2)
        for method in ("Netgen", "Laplace2D"):
            try:
                gmsh.model.mesh.optimize(method)
            except Exception:
                pass

        points, quads, tri_count, quad_count = _extract_surface_elements(outer_surfaces)
        log_lines: list[str] = []
        if logger_started:
            try:
                log_lines = list(gmsh.logger.get())
            except Exception:
                log_lines = []

        singular_total, summary_total, face_hits, node_hits = _parse_warning_counts(log_lines)
        _emit_singular_face_report(face_hits, node_hits, axes=axes)

        print(
            "[mesh-exp] strategy=quasi_structured success=%s singular=%d total_warn=%d tri=%d quad=%d target=%d"
            % (
                str(quad_count > 0 and tri_count == 0),
                singular_total,
                summary_total,
                tri_count,
                quad_count,
                singular_warning_target,
            )
        )

        if quad_count <= 0 or tri_count > 0:
            raise RuntimeError(
                "Quasi-structured ring meshing failed to create all-quad mesh "
                f"(tri={tri_count}, quad={quad_count})"
            )

        return (
            points,
            quads,
            {
                "strategy": "quasi_structured",
                "singular_warnings": singular_total,
                "total_warnings": summary_total,
                "tri_count": tri_count,
                "quad_count": quad_count,
                "unique_faces_with_singular": len(face_hits),
            },
        )
    finally:
        _restore_mesh_visibility(hidden_surfaces, prev_only_visible)
        if logger_started:
            try:
                gmsh.logger.stop()
            except Exception:
                pass
