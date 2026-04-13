"""Small utility helpers."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

import httpx


def read_prompt(prompt: str | None, prompt_file: Path | None) -> str:
    if prompt:
        return prompt
    if prompt_file:
        return prompt_file.read_text(encoding="utf-8").strip()
    raise ValueError("Provide --prompt or --prompt-file.")


def encode_image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".") or "png"
    if suffix == "jpg":
        suffix = "jpeg"
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/{suffix};base64,{b64}"


def download_binary(url: str, output_path: Path) -> None:
    with httpx.Client(timeout=300) as client:
        resp = client.get(url)
        resp.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(resp.content)


def extract_keyframes(video_path: Path, output_dir: Path) -> list[Path]:
    """Extract last frame and mid-point frame from a video via ffmpeg.

    Returns a list of extracted image paths (mid frame first, then last frame)
    so they can be used as reference images for the next clip.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem
    last_frame = output_dir / f"{stem}_lastframe.jpg"
    mid_frame = output_dir / f"{stem}_midframe.jpg"
    results: list[Path] = []

    # Get total frame count via ffprobe
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-count_frames",
        "-show_entries", "stream=nb_read_frames",
        "-of", "csv=p=0",
        str(video_path),
    ]
    try:
        probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        total_frames = int(probe.stdout.strip()) if probe.stdout.strip().isdigit() else 360
    except (subprocess.TimeoutExpired, ValueError):
        total_frames = 360
    mid_n = total_frames // 2

    # Mid frame
    mid_cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"select=eq(n\\,{mid_n})",
        "-vframes", "1", "-q:v", "1",
        str(mid_frame),
    ]
    try:
        subprocess.run(mid_cmd, capture_output=True, timeout=30)
        if mid_frame.exists() and mid_frame.stat().st_size > 0:
            results.append(mid_frame)
    except subprocess.TimeoutExpired:
        pass

    # Last frame
    last_cmd = [
        "ffmpeg", "-y", "-sseof", "-1",
        "-i", str(video_path),
        "-update", "1", "-q:v", "1",
        str(last_frame),
    ]
    try:
        subprocess.run(last_cmd, capture_output=True, timeout=30)
        if last_frame.exists() and last_frame.stat().st_size > 0:
            results.append(last_frame)
    except subprocess.TimeoutExpired:
        pass

    return results


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
