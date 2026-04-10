"""Image generation commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from changdu.cli.context import AppContext
from changdu.client.ark_base import ArkClient
from changdu.client.seedream import SeedreamClient
from changdu.models.requests import ImageGenerateRequest
from changdu.utils import read_prompt

image_app = typer.Typer(help="Image generation with Seedream.")


@image_app.command("generate")
def generate(
    ctx: typer.Context,
    prompt: str | None = typer.Option(None, "--prompt", help="Prompt content."),
    prompt_file: Path | None = typer.Option(None, "--prompt-file", help="Prompt text file."),
    output: Path = typer.Option(..., "--output", help="Output image path."),
    model: str | None = typer.Option(None, "--model", help="Override image model."),
    size: str | None = typer.Option(None, "--size", help="Override output size."),
) -> None:
    obj: AppContext = ctx.obj
    content = read_prompt(prompt, prompt_file)
    run_id = obj.trajectory_store.create_run("image generate")
    obj.trajectory_store.append_event(run_id, "input", {"prompt_len": len(content), "output": str(output)})

    client = SeedreamClient(
        client=ArkClient(api_key=obj.config.api_key, base_url=obj.config.base_url, timeout_s=obj.config.request_timeout_s),
        endpoint=obj.config.image_endpoint,
    )
    req = ImageGenerateRequest(
        model=model or obj.config.image_model,
        prompt=content,
        size=size or obj.config.image_size,
    )
    result = client.generate(req)
    client.write_output(result, output)

    obj.trajectory_store.append_event(
        run_id,
        "result",
        {"request_id": result.request_id, "output": str(output), "model": req.model, "size": req.size},
    )
    payload = {
        "ok": True,
        "run_id": run_id,
        "output": str(output),
        "request_id": result.request_id,
        "model": req.model,
    }
    if obj.output_json:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(f"Image generated: {output}")
        typer.echo(f"run_id: {run_id}")
