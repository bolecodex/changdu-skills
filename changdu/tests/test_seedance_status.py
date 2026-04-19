"""Tests for SeedanceClient.status response parsing covering audio_url and
video_duration introduced for Seedance 2.0 multimodal output.
"""

from __future__ import annotations

from typing import Any

from changdu.client.seedance import SeedanceClient


class _FakeArkClient:
    """Minimal stand-in for ArkBaseClient.get used by SeedanceClient.status."""

    def __init__(self, payload: dict[str, Any], request_id: str = "rid-1"):
        self._payload = payload
        self._request_id = request_id

    def get(self, endpoint: str):
        return self._payload, self._request_id


def _make_client(payload):
    sd = SeedanceClient.__new__(SeedanceClient)
    sd.client = _FakeArkClient(payload)
    sd.submit_endpoint = "/api/v3/contents/generations/tasks"
    sd.status_endpoint_template = "/api/v3/contents/generations/tasks/{task_id}"
    return sd


def test_status_parses_video_url_and_last_frame():
    payload = {
        "data": {
            "status": "Succeeded",
            "content": {
                "video_url": "https://cdn.example.com/out.mp4",
                "last_frame_url": "https://cdn.example.com/last.jpg",
            },
        }
    }
    sd = _make_client(payload)
    result = sd.status("task-1")
    assert result.task_id == "task-1"
    assert result.status == "Succeeded"
    assert result.file_url == "https://cdn.example.com/out.mp4"
    assert result.last_frame_url == "https://cdn.example.com/last.jpg"
    assert result.audio_url is None
    assert result.video_duration is None


def test_status_parses_audio_url_and_duration_from_video_obj():
    payload = {
        "data": {
            "status": "succeeded",
            "content": {
                "video": {
                    "url": "https://cdn.example.com/out.mp4",
                    "last_frame_url": "https://cdn.example.com/last.jpg",
                    "audio_url": "https://cdn.example.com/audio.mp3",
                    "duration": "15.0",
                },
            },
        }
    }
    sd = _make_client(payload)
    result = sd.status("task-2")
    assert result.file_url == "https://cdn.example.com/out.mp4"
    assert result.audio_url == "https://cdn.example.com/audio.mp3"
    assert result.video_duration == 15.0


def test_status_parses_audio_obj_when_separate():
    payload = {
        "data": {
            "status": "succeeded",
            "content": {
                "video_url": "https://cdn.example.com/out.mp4",
                "audio": {"url": "https://cdn.example.com/voice.mp3"},
            },
        }
    }
    sd = _make_client(payload)
    result = sd.status("task-3")
    assert result.audio_url == "https://cdn.example.com/voice.mp3"


def test_status_handles_failure():
    payload = {
        "data": {
            "status": "Failed",
            "reason": "internal error",
        }
    }
    sd = _make_client(payload)
    result = sd.status("task-4")
    assert result.status == "Failed"
    assert result.fail_reason == "internal error"
    assert result.file_url is None
