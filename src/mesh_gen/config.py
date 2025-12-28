from __future__ import annotations
import yaml
from dataclasses import dataclass

@dataclass(frozen=True)
class MeshGenConfig:
    revolve_axis: int = 2          # 0=X, 1=Y, 2=Z
    revolve_angle: float = 90.0    # degrees
    revolve_layers: int = 16
    mesh_size: float = 0.5
    mesh_dimension: int = 1        # (historical naming) element order: 1=linear, 2=quadratic, ...
    ogrid_core_ratio: float = 0.1
    # --- Core (inner) 2D O-grid settings ---
    core_inner_ratio: float = 0.35  # size of inner square/rectangle relative to R_core (0<ratio<1)
    core_radial_layers: int = 0     # 0=auto; otherwise explicit radial layers in O-grid block
    radial_mapping_beta: float = 2.0  # currently unused (kept for forward compatibility)
    merge_decimals: int = 5            # for merge_duplicate_points

    @staticmethod
    def from_yaml(path: str) -> "MeshGenConfig":
        with open(path, "r", encoding="utf-8") as f:
            full_config = yaml.safe_load(f)
        
        # Expect settings to be nested under 'mesh'
        # If 'mesh' key is missing, fallback to root or empty dict (use defaults)
        raw = full_config.get("mesh", {}) if full_config else {}

        def _get(name: str, cast, default):
            v = raw.get(name, default)
            try:
                return cast(v)
            except Exception as e:
                raise ValueError(f"Invalid config value: {name}={v!r} ({e})")

        cfg = MeshGenConfig(
            revolve_axis=_get("revolve_axis", int, MeshGenConfig.revolve_axis),
            revolve_angle=_get("revolve_angle", float, MeshGenConfig.revolve_angle),
            revolve_layers=_get("revolve_layers", int, MeshGenConfig.revolve_layers),
            mesh_size=_get("mesh_size", float, MeshGenConfig.mesh_size),
            mesh_dimension=_get("mesh_dimension", int, MeshGenConfig.mesh_dimension),
            ogrid_core_ratio=_get("ogrid_core_ratio", float, MeshGenConfig.ogrid_core_ratio),
            core_inner_ratio=_get("core_inner_ratio", float, MeshGenConfig.core_inner_ratio),
            core_radial_layers=_get("core_radial_layers", int, MeshGenConfig.core_radial_layers),
            radial_mapping_beta=_get("radial_mapping_beta", float, MeshGenConfig.radial_mapping_beta),
            merge_decimals=_get("merge_decimals", int, MeshGenConfig.merge_decimals),
        )

        if cfg.revolve_axis not in (0, 1, 2):
            raise ValueError("revolve_axis must be 0, 1, or 2.")
        if cfg.revolve_layers < 1:
            raise ValueError("revolve_layers must be >= 1.")
        if cfg.mesh_size <= 0:
            raise ValueError("mesh_size must be > 0.")
        if not (0.0 < cfg.ogrid_core_ratio < 1.0):
            raise ValueError("ogrid_core_ratio must be in (0,1).")
        if not (0.0 < cfg.core_inner_ratio < 1.0):
            raise ValueError("core_inner_ratio must be in (0,1).")
        if cfg.core_radial_layers < 0:
            raise ValueError("core_radial_layers must be >= 0.")
        if cfg.mesh_dimension < 1:
            raise ValueError("mesh_dimension (element order) must be >= 1.")

        return cfg
