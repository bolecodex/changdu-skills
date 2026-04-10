"""Auth commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from changdu.cli.context import AppContext

auth_app = typer.Typer(help="鉴权与配置检查。")


@auth_app.command("check")
def check(ctx: typer.Context) -> None:
    obj: AppContext = ctx.obj
    payload = {
        "ok": True,
        "base_url": obj.config.base_url,
        "profile": obj.profile,
        "config_path": str(obj.config_path or Path("~/.config/changdu/config.toml").expanduser()),
        "trajectory_dir": str(obj.config.trajectory_dir),
        "text_model": obj.config.text_model,
        "image_model": obj.config.image_model,
        "video_model": obj.config.video_model,
    }
    if obj.output_json:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo("配置检查通过。")
        typer.echo(f"服务地址: {payload['base_url']}")
        typer.echo(f"配置档: {payload['profile']}")
        typer.echo(f"文本端点: {payload['text_model'] or '-'}")
        typer.echo(f"图片端点: {payload['image_model']}")
        typer.echo(f"视频端点: {payload['video_model']}")


@auth_app.command("print-config-path")
def print_config_path() -> None:
    typer.echo(str(Path("~/.config/changdu/config.toml").expanduser()))
