"""Configuration loading with precedence controls."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

from changdu.errors import ConfigError


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "changdu" / "config.toml"
DEFAULT_TRAJECTORY_DIR = Path.home() / ".local" / "share" / "changdu" / "runs"


@dataclass
class AppConfig:
    api_key: str
    base_url: str = "https://ark.cn-beijing.volces.com"
    image_endpoint: str = "/api/v3/images/generations"
    video_submit_endpoint: str = "/api/v3/contents/generations/tasks"
    video_status_endpoint_template: str = "/api/v3/contents/generations/tasks/{task_id}"
    # `*_model` fields can be regular model IDs or user-owned endpoint IDs (ep-*)
    text_model: str | None = None
    image_model: str = "doubao-seedream-5-0-260128"
    video_model: str = "doubao-seedance-2-0-260128"
    image_size: str = "2K"
    video_ratio: str = "16:9"
    video_duration: int = 15
    request_timeout_s: int = 120
    poll_interval_s: int = 10
    poll_max_wait_s: int = 900
    trajectory_dir: Path = DEFAULT_TRAJECTORY_DIR


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _profile_map(data: dict[str, Any], profile: str) -> dict[str, Any]:
    profiles = data.get("profiles", {})
    selected = profiles.get(profile, {})
    default_section = data.get("default", {})
    merged = {**default_section, **selected}
    return merged


def load_config(
    *,
    profile: str = "default",
    config_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> AppConfig:
    path = config_path or DEFAULT_CONFIG_PATH
    data = _read_toml(path)
    cfg_map = _profile_map(data, profile)
    overrides = overrides or {}

    api_key = (
        overrides.get("api_key")
        or os.getenv("CHANGDU_ARK_API_KEY")
        or os.getenv("ARK_API_KEY")
        or cfg_map.get("api_key")
    )
    if not api_key:
        raise ConfigError(
            "Missing API key. Set CHANGDU_ARK_API_KEY (or ARK_API_KEY), or configure api_key in profile."
        )

    merged: dict[str, Any] = {
        "api_key": api_key,
        "base_url": os.getenv("CHANGDU_ARK_BASE_URL", cfg_map.get("base_url", "https://ark.cn-beijing.volces.com")),
        "image_endpoint": cfg_map.get("image_endpoint", "/api/v3/images/generations"),
        "video_submit_endpoint": cfg_map.get("video_submit_endpoint", "/api/v3/contents/generations/tasks"),
        "video_status_endpoint_template": cfg_map.get(
            "video_status_endpoint_template", "/api/v3/contents/generations/tasks/{task_id}"
        ),
        "text_model": (
            os.getenv("CHANGDU_SEED_TEXT_ENDPOINT")
            or os.getenv("CHANGDU_TEXT_MODEL")
            or cfg_map.get("text_model")
        ),
        "image_model": (
            os.getenv("CHANGDU_SEEDREAM_ENDPOINT")
            or os.getenv("CHANGDU_IMAGE_MODEL")
            or cfg_map.get("image_model", "doubao-seedream-5-0-260128")
        ),
        "video_model": (
            os.getenv("CHANGDU_SEEDANCE_ENDPOINT")
            or os.getenv("CHANGDU_VIDEO_MODEL")
            or cfg_map.get("video_model", "doubao-seedance-2-0-260128")
        ),
        "image_size": cfg_map.get("image_size", "2K"),
        "video_ratio": cfg_map.get("video_ratio", "16:9"),
        "video_duration": int(cfg_map.get("video_duration", 15)),
        "request_timeout_s": int(
            os.getenv("CHANGDU_REQUEST_TIMEOUT_S")
            or cfg_map.get("request_timeout_s", 120)
        ),
        "poll_interval_s": int(
            os.getenv("CHANGDU_POLL_INTERVAL_S")
            or cfg_map.get("poll_interval_s", 10)
        ),
        "poll_max_wait_s": int(
            os.getenv("CHANGDU_POLL_MAX_WAIT_S")
            or cfg_map.get("poll_max_wait_s", 900)
        ),
        "trajectory_dir": Path(
            os.getenv("CHANGDU_TRAJECTORY_DIR", cfg_map.get("trajectory_dir", str(DEFAULT_TRAJECTORY_DIR)))
        ),
    }
    merged.update({k: v for k, v in overrides.items() if v is not None})
    if isinstance(merged.get("trajectory_dir"), str):
        merged["trajectory_dir"] = Path(merged["trajectory_dir"])
    return AppConfig(**merged)
