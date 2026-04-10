"""Shared CLI application context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from changdu.config import AppConfig
from changdu.trajectory.store import TrajectoryStore


@dataclass
class AppContext:
    config: AppConfig
    output_json: bool
    verbose: bool
    profile: str
    trajectory_store: TrajectoryStore
    config_path: Path | None
