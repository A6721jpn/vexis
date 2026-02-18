from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class RobustMeshSpec:
    enabled: bool = True
    occ_heal: bool = True
    occ_heal_tolerance: float = 1e-7
    occ_fix_degenerated: bool = True
    occ_fix_small_edges: bool = True
    occ_fix_small_faces: bool = True
    occ_sew_faces: bool = True
    strategies: tuple[str, ...] = (
        "structured_blossom",
        "frontal_recombine",
        "delaunay_recombine",
    )
    singular_warning_target: int = 0


@dataclass(frozen=True)
class ExperimentalMeshGenConfig:
    revolve_axis: int = 2
    revolve_angle: float = 90.0
    revolve_layers: int = 16
    mesh_size: float = 0.5
    mesh_dimension: int = 1
    ogrid_core_ratio: float = 0.1
    core_inner_ratio: float = 0.35
    core_radial_layers: int = 0
    radial_mapping_beta: float = 2.0
    merge_decimals: int = 5
    output_format: str = "inp"
    robust: RobustMeshSpec = RobustMeshSpec()

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def from_yaml(path: str) -> "ExperimentalMeshGenConfig":
        with open(path, "r", encoding="utf-8") as f:
            full_config = yaml.safe_load(f) or {}

        raw_mesh = full_config.get("mesh", {}) if isinstance(full_config, dict) else {}
        robust_from_mesh = raw_mesh.get("robust", {}) if isinstance(raw_mesh, dict) else {}
        raw_robust = full_config.get("mesh_robust", robust_from_mesh)
        if not isinstance(raw_robust, dict):
            raw_robust = {}

        def _get(name: str, cast, default):
            v = raw_mesh.get(name, default)
            try:
                return cast(v)
            except Exception as exc:
                raise ValueError(f"Invalid config value: {name}={v!r} ({exc})") from exc

        base = ExperimentalMeshGenConfig(
            revolve_axis=_get("revolve_axis", int, ExperimentalMeshGenConfig.revolve_axis),
            revolve_angle=_get("revolve_angle", float, ExperimentalMeshGenConfig.revolve_angle),
            revolve_layers=_get("revolve_layers", int, ExperimentalMeshGenConfig.revolve_layers),
            mesh_size=_get("mesh_size", float, ExperimentalMeshGenConfig.mesh_size),
            mesh_dimension=_get("mesh_dimension", int, ExperimentalMeshGenConfig.mesh_dimension),
            ogrid_core_ratio=_get("ogrid_core_ratio", float, ExperimentalMeshGenConfig.ogrid_core_ratio),
            core_inner_ratio=_get("core_inner_ratio", float, ExperimentalMeshGenConfig.core_inner_ratio),
            core_radial_layers=_get("core_radial_layers", int, ExperimentalMeshGenConfig.core_radial_layers),
            radial_mapping_beta=_get("radial_mapping_beta", float, ExperimentalMeshGenConfig.radial_mapping_beta),
            merge_decimals=_get("merge_decimals", int, ExperimentalMeshGenConfig.merge_decimals),
            output_format=_get("output_format", str, ExperimentalMeshGenConfig.output_format),
        )

        strategy_raw = raw_robust.get("strategies", RobustMeshSpec.strategies)
        if isinstance(strategy_raw, str):
            strategies = tuple(s.strip() for s in strategy_raw.split(",") if s.strip())
        else:
            strategies = tuple(str(s).strip() for s in (strategy_raw or []) if str(s).strip())
        if not strategies:
            strategies = RobustMeshSpec.strategies

        robust = RobustMeshSpec(
            enabled=ExperimentalMeshGenConfig._as_bool(
                raw_robust.get("enabled", RobustMeshSpec.enabled)
            ),
            occ_heal=ExperimentalMeshGenConfig._as_bool(
                raw_robust.get("occ_heal", RobustMeshSpec.occ_heal)
            ),
            occ_heal_tolerance=float(
                raw_robust.get("occ_heal_tolerance", RobustMeshSpec.occ_heal_tolerance)
            ),
            occ_fix_degenerated=ExperimentalMeshGenConfig._as_bool(
                raw_robust.get("occ_fix_degenerated", RobustMeshSpec.occ_fix_degenerated)
            ),
            occ_fix_small_edges=ExperimentalMeshGenConfig._as_bool(
                raw_robust.get("occ_fix_small_edges", RobustMeshSpec.occ_fix_small_edges)
            ),
            occ_fix_small_faces=ExperimentalMeshGenConfig._as_bool(
                raw_robust.get("occ_fix_small_faces", RobustMeshSpec.occ_fix_small_faces)
            ),
            occ_sew_faces=ExperimentalMeshGenConfig._as_bool(
                raw_robust.get("occ_sew_faces", RobustMeshSpec.occ_sew_faces)
            ),
            strategies=strategies,
            singular_warning_target=int(
                raw_robust.get(
                    "singular_warning_target", RobustMeshSpec.singular_warning_target
                )
            ),
        )

        cfg = ExperimentalMeshGenConfig(
            revolve_axis=base.revolve_axis,
            revolve_angle=base.revolve_angle,
            revolve_layers=base.revolve_layers,
            mesh_size=base.mesh_size,
            mesh_dimension=base.mesh_dimension,
            ogrid_core_ratio=base.ogrid_core_ratio,
            core_inner_ratio=base.core_inner_ratio,
            core_radial_layers=base.core_radial_layers,
            radial_mapping_beta=base.radial_mapping_beta,
            merge_decimals=base.merge_decimals,
            output_format=base.output_format,
            robust=robust,
        )

        supported_strategies = {
            "structured_blossom",
            "frontal_recombine",
            "delaunay_recombine",
        }
        unknown = [s for s in cfg.robust.strategies if s not in supported_strategies]
        if unknown:
            raise ValueError(
                f"mesh_robust.strategies contains unknown values: {unknown}. "
                f"supported={sorted(supported_strategies)}"
            )

        if cfg.revolve_axis not in (0, 1, 2):
            raise ValueError("revolve_axis must be 0, 1, or 2")
        if abs(cfg.revolve_angle - 90.0) > 1e-6:
            raise ValueError("revolve_angle must be 90.0 (current prototype limitation)")
        if cfg.revolve_layers < 5:
            raise ValueError("revolve_layers must be >= 5")
        if cfg.mesh_size <= 0.0:
            raise ValueError("mesh_size must be > 0")
        if not (0.0 < cfg.ogrid_core_ratio < 1.0):
            raise ValueError("ogrid_core_ratio must be in (0,1)")
        if not (0.0 < cfg.core_inner_ratio < 1.0):
            raise ValueError("core_inner_ratio must be in (0,1)")
        if cfg.core_radial_layers < 0:
            raise ValueError("core_radial_layers must be >= 0")
        if cfg.mesh_dimension not in (1, 2):
            raise ValueError("mesh_dimension must be 1 or 2")
        if cfg.robust.occ_heal_tolerance <= 0.0:
            raise ValueError("mesh_robust.occ_heal_tolerance must be > 0")
        if cfg.robust.singular_warning_target < 0:
            raise ValueError("mesh_robust.singular_warning_target must be >= 0")

        return cfg
