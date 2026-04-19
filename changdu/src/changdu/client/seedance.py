"""Seedance video generation client."""

from __future__ import annotations

import base64
from pathlib import Path

from changdu.client.ark_base import ArkClient
from changdu.models.requests import VideoGenerateRequest
from changdu.models.responses import TaskStatusResponse, VideoSubmitResponse


class SeedanceClient:
    def __init__(self, client: ArkClient, submit_endpoint: str, status_endpoint_template: str) -> None:
        self.client = client
        self.submit_endpoint = submit_endpoint
        self.status_endpoint_template = status_endpoint_template

    def submit(self, req: VideoGenerateRequest) -> VideoSubmitResponse:
        payload, request_id = self.client.post(self.submit_endpoint, req.to_api_payload())
        task_id = (
            payload.get("id")
            or payload.get("task_id")
            or payload.get("data", {}).get("task_id")
            or payload.get("data", {}).get("id")
        )
        if not task_id:
            raise ValueError("Video submission response did not include task ID.")
        return VideoSubmitResponse(task_id=str(task_id), request_id=request_id)

    def status(self, task_id: str) -> TaskStatusResponse:
        endpoint = self.status_endpoint_template.format(task_id=task_id)
        payload, request_id = self.client.get(endpoint)
        data = payload.get("data", payload)
        status = str(data.get("status") or payload.get("status") or data.get("state") or "unknown")
        fail_reason = data.get("reason") or data.get("error_message")

        file_url = None
        last_frame_url = None
        audio_url = None
        video_duration: float | None = None
        content = data.get("content") or {}
        if isinstance(content, dict):
            file_url = content.get("video_url")
            last_frame_url = content.get("last_frame_url")
            audio_url = content.get("audio_url")
            video_obj = content.get("video") or {}
            if isinstance(video_obj, dict):
                if not file_url:
                    file_url = video_obj.get("url")
                if not last_frame_url:
                    last_frame_url = video_obj.get("last_frame_url")
                if not audio_url:
                    audio_url = video_obj.get("audio_url")
                duration_raw = video_obj.get("duration") or video_obj.get("video_duration")
                if duration_raw is not None:
                    try:
                        video_duration = float(duration_raw)
                    except (TypeError, ValueError):
                        video_duration = None
            audio_obj = content.get("audio") or {}
            if isinstance(audio_obj, dict) and not audio_url:
                audio_url = audio_obj.get("url")
        file_url = file_url or data.get("url")
        last_frame_url = last_frame_url or data.get("last_frame_url")
        audio_url = audio_url or data.get("audio_url")
        if video_duration is None:
            duration_raw = data.get("duration") or data.get("video_duration")
            if duration_raw is not None:
                try:
                    video_duration = float(duration_raw)
                except (TypeError, ValueError):
                    video_duration = None

        return TaskStatusResponse(
            task_id=task_id,
            status=status,
            file_url=file_url,
            last_frame_url=last_frame_url,
            audio_url=audio_url,
            video_duration=video_duration,
            fail_reason=fail_reason,
            request_id=request_id,
        )

    def write_output(self, raw_video_bytes_b64: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(raw_video_bytes_b64))
