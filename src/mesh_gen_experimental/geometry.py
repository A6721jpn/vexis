from __future__ import annotations

import os
from typing import Sequence, Tuple

import gmsh

from src.mesh_gen.geometry import (
    AxisInfo,
    SplitResult,
    _compute_global_bounds,
    _detect_profile_axes,
    _extract_profile_a_of_R,
)

from .config import ExperimentalMeshGenConfig
from .robust_ring_mesh import mesh_outer_ring_quads_robust


def _normalize_dimtags(value):
    if isinstance(value, tuple):
        if value and isinstance(value[0], list):
            return value[0]
        if all(isinstance(x, tuple) and len(x) == 2 for x in value):
            return list(value)
        return []
    if isinstance(value, list):
        if all(isinstance(x, tuple) and len(x) == 2 for x in value):
            return value
    return []


def _maybe_heal_shapes(
    shapes: Sequence[Tuple[int, int]],
    cfg: ExperimentalMeshGenConfig,
) -> Sequence[Tuple[int, int]]:
    if not cfg.robust.enabled or not cfg.robust.occ_heal:
        return shapes

    healed_shapes = list(shapes)

    # 1) OCC duplicate cleanup
    if hasattr(gmsh.model.occ, "removeAllDuplicates"):
        try:
            gmsh.model.occ.removeAllDuplicates()
            gmsh.model.occ.synchronize()
        except Exception as exc:
            print(f"[mesh-exp] OCC removeAllDuplicates skipped: {exc}")

    # 2) OCC healing
    if hasattr(gmsh.model.occ, "healShapes"):
        try:
            healed = gmsh.model.occ.healShapes(
                list(shapes),
                float(cfg.robust.occ_heal_tolerance),
                bool(cfg.robust.occ_fix_degenerated),
                bool(cfg.robust.occ_fix_small_edges),
                bool(cfg.robust.occ_fix_small_faces),
                bool(cfg.robust.occ_sew_faces),
                False,
            )
            gmsh.model.occ.synchronize()
            normalized = _normalize_dimtags(healed)
            if normalized:
                healed_shapes = normalized
                print(
                    "[mesh-exp] OCC healShapes applied: in=%d out=%d"
                    % (len(shapes), len(healed_shapes))
                )
            else:
                print("[mesh-exp] OCC healShapes returned no explicit dimTags; keeping original set")
        except Exception as exc:
            print(f"[mesh-exp] OCC healShapes failed, continue without heal: {exc}")

    return healed_shapes


def _radius_interval_from_bb(bb: tuple[float, float, float, float, float, float], radial_dim: int) -> tuple[float, float]:
    """Convert signed bbox interval to radius interval using absolute distance."""
    lo = float(bb[radial_dim])
    hi = float(bb[radial_dim + 3])
    if lo > hi:
        lo, hi = hi, lo
    if lo <= 0.0 <= hi:
        r_lo = 0.0
    else:
        r_lo = min(abs(lo), abs(hi))
    r_hi = max(abs(lo), abs(hi))
    return r_lo, r_hi


def _classify_surfaces_by_radius(
    surfaces_2d: Sequence[int],
    *,
    radial_dim: int,
    r_core: float,
    tol: float = 1e-5,
) -> tuple[list[int], list[int], list[int]]:
    """Classify surfaces into outer/inner/straddle in radius domain."""
    outer: list[int] = []
    inner: list[int] = []
    straddle: list[int] = []

    for s_tag in surfaces_2d:
        bb = gmsh.model.occ.getBoundingBox(2, int(s_tag))
        r_lo, r_hi = _radius_interval_from_bb(bb, radial_dim)
        if r_hi <= r_core + tol:
            inner.append(int(s_tag))
        elif r_lo >= r_core - tol:
            outer.append(int(s_tag))
        else:
            straddle.append(int(s_tag))
    return outer, inner, straddle


def _dedup_ints(values: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for v in values:
        iv = int(v)
        if iv in seen:
            continue
        seen.add(iv)
        out.append(iv)
    return out


def _refine_split_surfaces(
    surfaces_2d: Sequence[int],
    *,
    cut_line: int,
    radial_dim: int,
    r_core: float,
    max_passes: int = 2,
) -> tuple[list[int], list[int]]:
    """Refine straddling surfaces so outer ring stays away from axis neighborhood."""
    working = _dedup_ints(list(surfaces_2d))
    tol = 1e-5

    for p in range(max_passes):
        outer, inner, straddle = _classify_surfaces_by_radius(
            working,
            radial_dim=radial_dim,
            r_core=r_core,
            tol=tol,
        )
        if not straddle:
            return outer, inner

        print(
            "[mesh-exp] split refine pass=%d straddle=%d (outer=%d inner=%d)"
            % (p + 1, len(straddle), len(outer), len(inner))
        )

        frag_out, _ = gmsh.model.occ.fragment(
            [(2, int(s)) for s in straddle],
            [(1, int(cut_line))],
        )
        gmsh.model.occ.synchronize()
        refined = [tag for dim, tag in frag_out if dim == 2]
        if not refined:
            break
        keep = [s for s in working if s not in set(straddle)]
        working = _dedup_ints(keep + refined)

    # Final conservative routing for remaining straddlers.
    outer, inner, straddle = _classify_surfaces_by_radius(
        working,
        radial_dim=radial_dim,
        r_core=r_core,
        tol=tol,
    )
    if straddle:
        routed_outer: list[int] = []
        routed_inner = list(inner)
        to_inner = 0
        axis_tol = max(tol * 10.0, 1e-7)
        for s_tag in straddle:
            bb = gmsh.model.occ.getBoundingBox(2, int(s_tag))
            r_lo, _ = _radius_interval_from_bb(bb, radial_dim)
            # Axis-near straddles are treated as inner to avoid injecting
            # axis-adjacent surfaces into ring meshing.
            if r_lo <= axis_tol:
                routed_inner.append(int(s_tag))
                to_inner += 1
            else:
                routed_outer.append(int(s_tag))
        outer = _dedup_ints(outer + routed_outer)
        inner = _dedup_ints(routed_inner)
        print(
            "[mesh-exp] straddle fallback routed: to_outer=%d to_inner=%d"
            % (len(routed_outer), to_inner)
        )
        # Re-print explicit sizes (previous line keeps historical log key)
        print(
            "[mesh-exp] final classification: outer=%d inner=%d unresolved_straddle=%d"
            % (len(outer), len(inner), len(straddle))
        )
    return outer, inner


def analyze_geometry_and_split(
    stp_path: str,
    cfg: ExperimentalMeshGenConfig,
) -> SplitResult:
    """Experimental geometry split + robust outer ring meshing."""
    if not os.path.exists(stp_path):
        raise FileNotFoundError(stp_path)

    gmsh.initialize()
    _set_num = gmsh.option.setNumber
    _set_num("General.Terminal", 1)
    _set_num("General.Verbosity", 2)
    try:
        _set_num("General.NoPopup", 1)
    except Exception:
        pass

    gmsh.model.add("adaptive_mesh_gen_experimental")
    try:
        shapes = gmsh.model.occ.importShapes(stp_path)
        gmsh.model.occ.synchronize()

        shapes = _maybe_heal_shapes(shapes, cfg)

        mins, maxs = _compute_global_bounds(shapes)
        axes = _detect_profile_axes(mins, maxs, revolve_axis=cfg.revolve_axis)

        rd = axes.radial_dim
        r_min = mins[rd]
        r_max = maxs[rd]
        r_abs_max = max(abs(r_min), abs(r_max))
        r_core = float(r_abs_max * cfg.ogrid_core_ratio)

        ad = axes.axial_dim
        p1 = [0.0, 0.0, 0.0]
        p2 = [0.0, 0.0, 0.0]
        p1[rd] = r_core
        p2[rd] = r_core

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
            raise RuntimeError("No 2D surfaces found after fragment()")

        outer_surfaces, inner_surfaces = _refine_split_surfaces(
            surfaces_2d,
            cut_line=cut_line,
            radial_dim=axes.radial_dim,
            r_core=r_core,
            max_passes=2,
        )
        if not outer_surfaces:
            raise RuntimeError("Failed to identify outer ring surfaces after split")

        a_bot, a_top = _extract_profile_a_of_R(inner_surfaces, axes, r_core)
        ring_points, ring_quads, meta = mesh_outer_ring_quads_robust(
            mesh_size=cfg.mesh_size,
            outer_surfaces=outer_surfaces,
            axes=axes,
            strategies=cfg.robust.strategies,
            singular_warning_target=cfg.robust.singular_warning_target,
        )
        print(
            "[mesh-exp] ring meshing selected strategy=%s singular=%s"
            % (meta.get("strategy"), meta.get("singular_warnings"))
        )

        return SplitResult(
            ring_points_3d=ring_points,
            ring_quads=ring_quads,
            R_core=r_core,
            axes=AxisInfo(
                radial_dim=axes.radial_dim,
                axial_dim=axes.axial_dim,
                normal_dim=axes.normal_dim,
            ),
            a_bot=a_bot,
            a_top=a_top,
        )
    finally:
        gmsh.finalize()
