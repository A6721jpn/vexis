from __future__ import annotations
import numpy as np
import gmsh
from typing import Tuple, Sequence, List, Optional, Dict
from .geometry import AxisInfo

def mesh_outer_ring_quads(mesh_size: float, outer_surfaces: Sequence[int], axes: AxisInfo) -> Tuple[np.ndarray, np.ndarray]:
    """Generate a quad mesh on outer surfaces and return (points3d, quads)."""
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", mesh_size)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", mesh_size)

    # Improve quad recombination quality and encourage structured quads where possible.
    gmsh.option.setNumber("Mesh.RecombineAll", 1)
    gmsh.option.setNumber("Mesh.RecombinationAlgorithm", 2)  # 2 = Blossom (generally higher quality)
    gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 1)
    gmsh.option.setNumber("Mesh.Smoothing", 10)
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)
    gmsh.option.setNumber("Mesh.Algorithm", 11)  # Quasi-structured Quad Meshing (experimental)

    # Try to make the 2D quad mesh closer to a structured grid:
    # apply transfinite constraints on "4-sided" outer profile surfaces (when detectable).
    def _curve_length(c_tag: int) -> float:
        try:
            return float(gmsh.model.occ.getMass(1, c_tag))
        except Exception:
            try:
                xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(1, c_tag)
                return float(((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5)
            except Exception:
                return 0.0

    def _curve_endpoints(c_tag: int) -> Optional[Tuple[int, int]]:
        bnd = gmsh.model.getBoundary([(1, c_tag)], oriented=False, recursive=False)
        pts = [t for (d, t) in bnd if d == 0]
        if len(pts) < 2:
            return None
        # remove duplicates while preserving order
        unique: List[int] = []
        for p in pts:
            if p not in unique:
                unique.append(p)
        if len(unique) < 2:
            return None
        return unique[0], unique[-1]

    curve_n: Dict[int, int] = {}
    transfinite_surfaces: List[int] = []
    for s in outer_surfaces:
        bnd = gmsh.model.getBoundary([(2, s)], oriented=False, recursive=False)
        curves = [t for (d, t) in bnd if d == 1]
        # unique while preserving order
        cu: List[int] = []
        for c in curves:
            if c not in cu:
                cu.append(c)
        if len(cu) != 4:
            continue

        endpoints = [_curve_endpoints(c) for c in cu]
        if any(e is None for e in endpoints):
            continue

        ep_sets = [set(e) for e in endpoints if e is not None]

        # find opposite pairs: curves that do not share endpoints
        opp: List[Tuple[int, int]] = []
        for i in range(4):
            for j in range(i + 1, 4):
                if ep_sets[i].isdisjoint(ep_sets[j]):
                    opp.append((i, j))
        if len(opp) != 2:
            continue

        local_n = [max(2, int(round(_curve_length(c) / mesh_size)) + 1) for c in cu]
        # enforce equal divisions on opposite pairs
        for (i, j) in opp:
            n = max(local_n[i], local_n[j])
            local_n[i] = local_n[j] = n

        for c, n in zip(cu, local_n):
            curve_n[c] = max(curve_n.get(c, 0), n)
        transfinite_surfaces.append(s)

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

    pg = gmsh.model.addPhysicalGroup(2, list(outer_surfaces))
    gmsh.model.setPhysicalName(2, pg, "OuterRing")

    gmsh.model.mesh.generate(2)

    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    node_tags = np.asarray(node_tags, dtype=np.int64)
    points_all = np.asarray(node_coords, dtype=float).reshape(-1, 3)
    node_map = {int(tag): i for i, tag in enumerate(node_tags)}

    quads: List[np.ndarray] = []
    tri_count = 0

    for s_tag in outer_surfaces:
        elem_types, _, elem_node_tags = gmsh.model.mesh.getElements(2, s_tag)
        for etype, enodes in zip(elem_types, elem_node_tags):
            if etype == 3:  # 4-node quad
                en = np.asarray(enodes, dtype=np.int64).reshape(-1, 4)
                mapped = np.vectorize(node_map.__getitem__)(en)
                quads.append(mapped)
            elif etype == 2:  # 3-node triangle (unexpected if recombination worked)
                tri_count += len(enodes) // 3

    if tri_count > 0 and not quads:
        raise RuntimeError(
            f"Outer ring meshing produced triangles only ({tri_count} tris). "
            "Try adjusting gmsh options (recombination), mesh_size, or geometry quality."
        )

    if not quads:
        raise RuntimeError("No quads generated in outer ring.")

    quads = np.vstack(quads)

    # Compact point array to those actually referenced by quads
    used = np.unique(quads)
    old_to_new = {int(old): i for i, old in enumerate(used)}
    points = points_all[used]
    quads = np.vectorize(old_to_new.__getitem__)(quads)

    return points, quads.astype(np.int64)
