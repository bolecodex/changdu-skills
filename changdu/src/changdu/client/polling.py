"""Polling utilities for asynchronous tasks."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable

from changdu.errors import TimeoutError
from changdu.models.responses import TaskStatusResponse


TERMINAL_SUCCESS = {"succeeded", "success", "completed", "done"}
TERMINAL_FAILURE = {"failed", "error", "cancelled", "canceled"}
RUNNING = {"queued", "pending", "running", "processing", "in_progress"}


def normalize_status(raw_status: str) -> str:
    lowered = raw_status.lower()
    if lowered in TERMINAL_SUCCESS:
        return "succeeded"
    if lowered in TERMINAL_FAILURE:
        return "failed"
    if lowered in RUNNING:
        return "running"
    return "unknown"


@dataclass
class PollConfig:
    interval_s: int
    max_wait_s: int
    max_interval_s: int = 30


def poll_task(
    *,
    fetcher: Callable[[str], TaskStatusResponse],
    task_id: str,
    config: PollConfig,
    on_update: Callable[[TaskStatusResponse, str], None] | None = None,
) -> TaskStatusResponse:
    start = time.monotonic()
    interval = max(1, config.interval_s)

    while True:
        result = fetcher(task_id)
        normalized = normalize_status(result.status)
        if on_update:
            on_update(result, normalized)

        if normalized == "succeeded":
            return result
        if normalized == "failed":
            return result

        elapsed = time.monotonic() - start
        if elapsed >= config.max_wait_s:
            raise TimeoutError(f"Task {task_id} timed out after {config.max_wait_s}s.")

        jitter = random.uniform(0, 0.5)  # noqa: S311
        time.sleep(interval + jitter)
        interval = min(int(interval * 1.5), config.max_interval_s)
