"""Task status and wait commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from changdu.cli.context import AppContext
from changdu.client.ark_base import ArkClient
from changdu.client.polling import PollConfig, poll_task
from changdu.client.seedance import SeedanceClient
from changdu.errors import RequestError
from changdu.utils import download_binary

task_app = typer.Typer(help="Task operations.")


def _build_client(obj: AppContext) -> SeedanceClient:
    return SeedanceClient(
        client=ArkClient(api_key=obj.config.api_key, base_url=obj.config.base_url, timeout_s=obj.config.request_timeout_s),
        submit_endpoint=obj.config.video_submit_endpoint,
        status_endpoint_template=obj.config.video_status_endpoint_template,
    )


@task_app.command("show")
def show(ctx: typer.Context, task_id: str = typer.Argument(..., help="Task ID.")) -> None:
    obj: AppContext = ctx.obj
    client = _build_client(obj)
    status = client.status(task_id)
    payload = {
        "task_id": status.task_id,
        "status": status.status,
        "file_url": status.file_url,
        "fail_reason": status.fail_reason,
        "request_id": status.request_id,
    }
    if obj.output_json:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(f"task_id: {status.task_id}")
        typer.echo(f"status: {status.status}")
        if status.file_url:
            typer.echo(f"file_url: {status.file_url}")
        if status.fail_reason:
            typer.echo(f"fail_reason: {status.fail_reason}")


@task_app.command("wait")
def wait(
    ctx: typer.Context,
    task_id: str = typer.Argument(..., help="Task ID."),
    output: Path | None = typer.Option(None, "--output", help="Download path if task succeeds."),
    run_id: str | None = typer.Option(None, "--run-id", help="Attach events to an existing run."),
    interval: int | None = typer.Option(None, "--interval", help="Polling interval seconds."),
    timeout: int | None = typer.Option(None, "--timeout", help="Max wait seconds."),
) -> None:
    obj: AppContext = ctx.obj
    active_run_id = run_id or obj.trajectory_store.create_run("task wait")
    client = _build_client(obj)

    def on_update(result, normalized: str) -> None:
        obj.trajectory_store.append_event(
            active_run_id,
            "poll",
            {"task_id": result.task_id, "raw_status": result.status, "normalized": normalized, "request_id": result.request_id},
        )

    result = poll_task(
        fetcher=client.status,
        task_id=task_id,
        config=PollConfig(
            interval_s=interval or obj.config.poll_interval_s,
            max_wait_s=timeout or obj.config.poll_max_wait_s,
        ),
        on_update=on_update,
    )

    if result.status.lower() in ("failed", "error", "cancelled", "canceled"):
        raise RequestError(f"Task failed: {result.fail_reason or result.status}", request_id=result.request_id)

    if output and result.file_url:
        download_binary(result.file_url, output)
        obj.trajectory_store.append_event(active_run_id, "artifact", {"task_id": task_id, "output": str(output)})

    payload = {
        "ok": True,
        "task_id": task_id,
        "status": result.status,
        "file_url": result.file_url,
        "output": str(output) if output else None,
        "run_id": active_run_id,
    }
    if obj.output_json:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(f"Task succeeded: {task_id}")
        if output:
            typer.echo(f"saved: {output}")
