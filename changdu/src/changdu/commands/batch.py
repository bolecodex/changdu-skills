"""Batch run commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml

from changdu.cli.context import AppContext
from changdu.client.ark_base import ArkClient
from changdu.client.polling import PollConfig, poll_task
from changdu.client.seedance import SeedanceClient
from changdu.client.seedream import SeedreamClient
from changdu.models.requests import ImageGenerateRequest, VideoGenerateRequest
from changdu.utils import download_binary, encode_image_to_data_url, read_prompt

batch_app = typer.Typer(help="Batch execution from YAML spec.")


def _resolve_path(spec_path: Path, raw: str | None) -> Path | None:
    if not raw:
        return None
    p = Path(raw)
    if p.is_absolute():
        return p
    return spec_path.parent / p


@batch_app.command("run")
def run(
    ctx: typer.Context,
    spec: Path = typer.Argument(..., exists=True, help="Batch spec YAML file."),
) -> None:
    obj: AppContext = ctx.obj
    cfg = yaml.safe_load(spec.read_text(encoding="utf-8")) or {}
    jobs: list[dict[str, Any]] = cfg.get("jobs", [])
    run_id = obj.trajectory_store.create_run("batch run")
    results: list[dict[str, Any]] = []

    base_client = ArkClient(
        api_key=obj.config.api_key,
        base_url=obj.config.base_url,
        timeout_s=obj.config.request_timeout_s,
    )
    image_client = SeedreamClient(base_client, obj.config.image_endpoint)
    video_client = SeedanceClient(base_client, obj.config.video_submit_endpoint, obj.config.video_status_endpoint_template)

    for idx, job in enumerate(jobs, start=1):
        job_type = job.get("type")
        name = job.get("name") or f"job-{idx}"
        obj.trajectory_store.append_event(run_id, "batch_job_start", {"index": idx, "type": job_type, "name": name})
        if job_type == "image":
            prompt = read_prompt(job.get("prompt"), _resolve_path(spec, job.get("prompt_file")))
            output = _resolve_path(spec, job["output"])
            if output is None:
                raise ValueError("image job requires output")
            req = ImageGenerateRequest(
                model=job.get("model", obj.config.image_model),
                prompt=prompt,
                size=job.get("size", obj.config.image_size),
            )
            result = image_client.generate(req)
            image_client.write_output(result, output)
            result_payload = {"index": idx, "type": "image", "status": "succeeded", "output": str(output)}
            results.append(result_payload)
            obj.trajectory_store.append_event(run_id, "batch_job_done", result_payload)
            continue

        if job_type == "video":
            prompt = read_prompt(job.get("prompt"), _resolve_path(spec, job.get("prompt_file")))
            output = _resolve_path(spec, job["output"])
            if output is None:
                raise ValueError("video job requires output")
            image_paths = [_resolve_path(spec, p) for p in job.get("images", [])]
            image_paths = [p for p in image_paths if p is not None]
            images = [encode_image_to_data_url(p) for p in image_paths]
            req = VideoGenerateRequest(
                model=job.get("model", obj.config.video_model),
                prompt=prompt,
                ratio=job.get("ratio", obj.config.video_ratio),
                duration=int(job.get("duration", obj.config.video_duration)),
                images=images,
            )
            submitted = video_client.submit(req)
            final = poll_task(
                fetcher=video_client.status,
                task_id=submitted.task_id,
                config=PollConfig(
                    interval_s=int(job.get("interval", obj.config.poll_interval_s)),
                    max_wait_s=int(job.get("timeout", obj.config.poll_max_wait_s)),
                ),
                on_update=lambda r, normalized: obj.trajectory_store.append_event(
                    run_id,
                    "batch_poll",
                    {"index": idx, "task_id": submitted.task_id, "raw_status": r.status, "normalized": normalized},
                ),
            )
            if final.file_url:
                download_binary(final.file_url, output)
            result_payload = {
                "index": idx,
                "type": "video",
                "status": final.status,
                "task_id": submitted.task_id,
                "output": str(output),
            }
            results.append(result_payload)
            obj.trajectory_store.append_event(run_id, "batch_job_done", result_payload)
            continue

        result_payload = {"index": idx, "type": job_type, "status": "skipped", "reason": "unknown job type"}
        results.append(result_payload)
        obj.trajectory_store.append_event(run_id, "batch_job_skipped", result_payload)

    payload = {"ok": True, "run_id": run_id, "jobs": results}
    if obj.output_json:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(f"batch run created: {run_id}")
        typer.echo(f"jobs finished: {len(jobs)}")
