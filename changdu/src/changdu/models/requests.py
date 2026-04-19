"""Request payload models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ImageGenerateRequest(BaseModel):
    model: str
    prompt: str
    size: str = "2K"
    response_format: str = "url"
    images: list[str] = Field(default_factory=list)

    def to_api_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": self.prompt,
            "size": self.size,
            "watermark": False,
        }
        if self.images:
            payload["image"] = self.images
            payload["sequential_image_generation"] = "disabled"
        return payload


class VideoGenerateRequest(BaseModel):
    """Seedance 2.0 video generation request.

    Two mutually-exclusive operating modes are exposed by the API:

    1. **First/last-frame driven mode** — set `first_frame_url` and/or
       `last_frame_url`. The model strictly interpolates between/from
       these frames. ``images``, ``videos`` and ``audios`` MUST be empty
       in this mode (the API rejects mixing them with frame anchors:
       ``first/last frame content cannot be mixed with reference media
       content``).

    2. **Reference media mode** — pass any combination of:
       - up to 9 reference images (``role=reference_image``)
       - up to 3 reference videos (``role=reference_video``)
       - up to 3 reference audios (``role=reference_audio``)

    ``to_api_payload`` raises ``ValueError`` if both modes are mixed,
    so the caller fails fast (no wasted ARK call).
    """

    model: str
    prompt: str
    ratio: str = "16:9"
    duration: int = 15
    images: list[str] = Field(default_factory=list)
    videos: list[str] = Field(default_factory=list)
    audios: list[str] = Field(default_factory=list)
    return_last_frame: bool = False
    first_frame_url: str | None = None
    last_frame_url: str | None = None
    generate_audio: bool = True
    quality: str | None = None

    def to_api_payload(self) -> dict[str, Any]:
        has_frame_anchor = bool(self.first_frame_url or self.last_frame_url)
        has_reference_media = bool(self.images or self.videos or self.audios)
        if has_frame_anchor and has_reference_media:
            raise ValueError(
                "Seedance API 不允许 first_frame/last_frame 与 reference_image/"
                "reference_video/reference_audio 同时使用。请二选一："
                "用首尾帧模式（first_frame_url / last_frame_url）或参考媒体模式"
                "（images / videos / audios）。"
            )

        content: list[dict[str, Any]] = []
        text_prompt = self.prompt.strip()
        if text_prompt:
            content.append({"type": "text", "text": text_prompt})

        if self.first_frame_url:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self.first_frame_url},
                    "role": "first_frame",
                }
            )
        if self.last_frame_url:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self.last_frame_url},
                    "role": "last_frame",
                }
            )
        for img in self.images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": img},
                    "role": "reference_image",
                }
            )
        for vid in self.videos:
            content.append(
                {
                    "type": "video_url",
                    "video_url": {"url": vid},
                    "role": "reference_video",
                }
            )
        for aud in self.audios:
            content.append(
                {
                    "type": "audio_url",
                    "audio_url": {"url": aud},
                    "role": "reference_audio",
                }
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "content": content,
            "ratio": self.ratio,
            "duration": self.duration,
            "watermark": False,
        }
        if self.quality:
            payload["quality"] = self.quality
        if not self.generate_audio:
            payload["generate_audio"] = False
        if self.return_last_frame:
            payload["return_last_frame"] = True
        return payload
