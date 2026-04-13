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
    model: str
    prompt: str
    ratio: str = "16:9"
    duration: int = 15
    images: list[str] = Field(default_factory=list)
    return_last_frame: bool = False
    first_frame_url: str | None = None

    def to_api_payload(self) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        text_prompt = self.prompt.strip()
        if text_prompt:
            content.append({"type": "text", "text": text_prompt})
        if self.first_frame_url:
            # API constraint: first_frame cannot be mixed with reference_image
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self.first_frame_url},
                    "role": "first_frame",
                }
            )
        else:
            for img in self.images:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": img},
                        "role": "reference_image",
                    }
                )
        payload: dict[str, Any] = {
            "model": self.model,
            "content": content,
            "ratio": self.ratio,
            "duration": self.duration,
            "watermark": False,
        }
        if self.return_last_frame:
            payload["return_last_frame"] = True
        return payload
