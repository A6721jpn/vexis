from __future__ import annotations

import os
from dataclasses import dataclass

import yaml


def _resolve_relative_path(value: str, *roots: str) -> str:
    if os.path.isabs(value):
        return value

    for root in roots:
        candidate = os.path.abspath(os.path.join(root, value))
        if os.path.exists(candidate):
            return candidate

    return os.path.abspath(os.path.join(roots[-1], value))


def _looks_like_path(value: str) -> bool:
    return any(separator in value for separator in (os.sep, "/", "\\"))


@dataclass(frozen=True)
class AnalysisConfig:
    total_stroke: float
    time_steps: int
    num_threads: int | None
    template_feb: str
    febio_path: str
    contact_penalty: float
    material_name: str

    @staticmethod
    def from_yaml(path: str) -> "AnalysisConfig":
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            full_config = yaml.safe_load(f) or {}

        raw = full_config.get("analysis", {})
        config_dir = os.path.dirname(os.path.abspath(path))
        app_dir = os.path.dirname(config_dir)

        def _get(name: str, cast, default=None, required: bool = False):
            value = raw.get(name, default)
            if required and value is None:
                raise ValueError(f"Missing required config value: {name}")
            if value is None:
                return None
            try:
                return cast(value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Invalid config value: {name}={value!r} ({error})"
                ) from error

        total_stroke_raw = raw.get("total_stroke", raw.get("push_dist", 0.0))
        try:
            total_stroke = float(total_stroke_raw)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid total_stroke/push_dist: {total_stroke_raw}"
            ) from error

        template_feb = _resolve_relative_path(
            _get("template_feb", str, "template2.feb"),
            config_dir,
            app_dir,
        )
        febio_path = _get("febio_path", str, "")
        if febio_path and _looks_like_path(febio_path):
            febio_path = _resolve_relative_path(febio_path, config_dir, app_dir)

        cfg = AnalysisConfig(
            total_stroke=total_stroke,
            time_steps=_get("time_steps", int, 20),
            num_threads=_get("num_threads", int, None),
            template_feb=template_feb,
            febio_path=febio_path,
            contact_penalty=_get("contact_penalty", float, 5.0),
            material_name=_get("material_name", str, "Ogden_Rubber_v1"),
        )

        if cfg.total_stroke == 0.0:
            raise ValueError("total_stroke must not be 0.")

        if cfg.time_steps <= 0:
            raise ValueError(f"time_steps must be > 0. Got {cfg.time_steps}")

        if cfg.num_threads is not None:
            if cfg.num_threads <= 0:
                raise ValueError(f"num_threads must be > 0. Got {cfg.num_threads}")
            if cfg.num_threads > 32:
                raise ValueError(f"num_threads must be <= 32. Got {cfg.num_threads}")

        if not os.path.exists(cfg.template_feb):
            raise FileNotFoundError(f"template_feb not found: {cfg.template_feb}")

        if not 0.0 < cfg.contact_penalty < 20.0:
            raise ValueError(
                f"contact_penalty must be (0 < value < 20). Got {cfg.contact_penalty}"
            )

        if cfg.febio_path and not os.path.exists(cfg.febio_path):
            if _looks_like_path(cfg.febio_path) or os.path.isabs(cfg.febio_path):
                raise FileNotFoundError(f"febio_path not found: {cfg.febio_path}")

        return cfg
