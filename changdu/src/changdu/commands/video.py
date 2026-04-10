"""Video generation commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from changdu.cli.context import AppContext
from changdu.client.ark_base import ArkClient
from changdu.client.seedance import SeedanceClient
from changdu.models.requests import VideoGenerateRequest
from changdu.utils import encode_image_to_data_url, read_prompt

video_app = typer.Typer(help="Video generation with Seedance.")


@video_app.command("generate")
def generate(
    ctx: typer.Context,
    prompt: str | None = typer.Option(None, "--prompt", help="Prompt content."),
    prompt_file: Path | None = typer.Option(None, "--prompt-file", help="Prompt text file."),
    image: list[Path] = typer.Option([], "--image", "-i", help="Reference images."),
    model: str | None = typer.Option(None, "--model", help="Override video model."),
    ratio: str | None = typer.Option(None, "--ratio", help="Output ratio."),
    duration: int | None = typer.Option(None, "--duration", help="Duration in seconds."),
) -> None:
    obj: AppContext = ctx.obj
    content = read_prompt(prompt, prompt_file)
    run_id = obj.trajectory_store.create_run("video generate")

    images = [encode_image_to_data_url(path) for path in image]
    req = VideoGenerateRequest(
        model=model or obj.config.video_model,
        prompt=content,
        ratio=ratio or obj.config.video_ratio,
        duration=duration or obj.config.video_duration,
        images=images,
    )
    obj.trajectory_store.append_event(
        run_id,
        "input",
        {"prompt_len": len(content), "image_count": len(images), "model": req.model, "ratio": req.ratio},
    )

    client = SeedanceClient(
        client=ArkClient(api_key=obj.config.api_key, base_url=obj.config.base_url, timeout_s=obj.config.request_timeout_s),
        submit_endpoint=obj.config.video_submit_endpoint,
        status_endpoint_template=obj.config.video_status_endpoint_template,
    )
    submitted = client.submit(req)
    obj.trajectory_store.append_event(
        run_id,
        "submitted",
        {"task_id": submitted.task_id, "request_id": submitted.request_id},
    )
    payload = {"ok": True, "run_id": run_id, "task_id": submitted.task_id, "request_id": submitted.request_id}
    if obj.output_json:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(f"Video task submitted: {submitted.task_id}")
        typer.echo(f"run_id: {run_id}")
