"""Trajectory inspection commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from changdu.cli.context import AppContext

traj_app = typer.Typer(help="Inspect trajectory runs.")


@traj_app.command("list")
def list_runs(ctx: typer.Context) -> None:
    obj: AppContext = ctx.obj
    runs = obj.trajectory_store.list_runs()
    if obj.output_json:
        typer.echo(json.dumps({"runs": runs}, ensure_ascii=False))
    else:
        for run_id in runs:
            typer.echo(run_id)


@traj_app.command("show")
def show(ctx: typer.Context, run_id: str = typer.Argument(..., help="Run ID.")) -> None:
    obj: AppContext = ctx.obj
    meta = obj.trajectory_store.read_meta(run_id)
    events = obj.trajectory_store.iter_events(run_id)
    payload = {"meta": meta, "events": events}
    if obj.output_json:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(f"run_id: {meta['run_id']}")
        typer.echo(f"command: {meta['command']}")
        typer.echo(f"created_at: {meta['created_at']}")
        typer.echo(f"events: {len(events)}")


@traj_app.command("export")
def export(
    ctx: typer.Context,
    run_id: str = typer.Argument(..., help="Run ID."),
    output: Path = typer.Option(..., "--output", help="Output json path."),
) -> None:
    obj: AppContext = ctx.obj
    payload = {"meta": obj.trajectory_store.read_meta(run_id), "events": obj.trajectory_store.iter_events(run_id)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"exported: {output}")
