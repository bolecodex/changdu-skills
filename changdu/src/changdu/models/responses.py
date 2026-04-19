"""Response payload helpers."""

from __future__ import annotations

from pydantic import BaseModel


class ImageGenerateResponse(BaseModel):
    image_url: str | None = None
    image_b64: str | None = None
    request_id: str | None = None


class VideoSubmitResponse(BaseModel):
    task_id: str
    request_id: str | None = None


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    file_url: str | None = None
    last_frame_url: str | None = None
    audio_url: str | None = None
    video_duration: float | None = None
    fail_reason: str | None = None
    request_id: str | None = None
