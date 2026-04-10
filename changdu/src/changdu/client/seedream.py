"""Seedream image generation client."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from changdu.client.ark_base import ArkClient
from changdu.models.requests import ImageGenerateRequest
from changdu.models.responses import ImageGenerateResponse


class SeedreamClient:
    def __init__(self, client: ArkClient, endpoint: str) -> None:
        self.client = client
        self.endpoint = endpoint

    def generate(self, req: ImageGenerateRequest) -> ImageGenerateResponse:
        payload, request_id = self.client.post(self.endpoint, req.to_api_payload())
        data = payload.get("data", [{}])
        first = data[0] if data else {}
        return ImageGenerateResponse(
            image_url=first.get("url"),
            image_b64=first.get("b64_json"),
            request_id=request_id,
        )

    def write_output(self, result: ImageGenerateResponse, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if result.image_b64:
            output_path.write_bytes(base64.b64decode(result.image_b64))
            return
        if result.image_url:
            with httpx.Client(timeout=120) as client:
                resp = client.get(result.image_url)
                resp.raise_for_status()
            output_path.write_bytes(resp.content)
            return
        raise ValueError("Image response did not include url or b64 payload.")
