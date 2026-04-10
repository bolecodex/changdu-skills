"""Filesystem-backed trajectory store."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from changdu.errors import TrajectoryError
from changdu.trajectory.schema import RunMeta, StepEvent, now_iso


class TrajectoryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run(self, command: str) -> str:
        run_id = uuid.uuid4().hex[:16]
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        meta = RunMeta(run_id=run_id, command=command)
        (run_dir / "meta.json").write_text(json.dumps(meta.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "events.jsonl").write_text("", encoding="utf-8")
        return run_id

    def append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        run_dir = self.root / run_id
        if not run_dir.exists():
            raise TrajectoryError(f"Run not found: {run_id}")
        evt = StepEvent(time=now_iso(), type=event_type, payload=payload)
        with (run_dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt.to_dict(), ensure_ascii=False) + "\n")

    def run_dir(self, run_id: str) -> Path:
        path = self.root / run_id
        if not path.exists():
            raise TrajectoryError(f"Run not found: {run_id}")
        return path

    def read_meta(self, run_id: str) -> dict[str, Any]:
        path = self.run_dir(run_id) / "meta.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise TrajectoryError(f"Invalid meta for run: {run_id}") from exc

    def iter_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self.run_dir(run_id) / "events.jsonl"
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def list_runs(self) -> list[str]:
        return sorted([p.name for p in self.root.iterdir() if p.is_dir()], reverse=True)
