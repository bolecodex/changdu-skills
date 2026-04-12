"""Entry point for changdu CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer

from changdu.cli.context import AppContext
from changdu.commands.auth import auth_app
from changdu.commands.batch import batch_app
from changdu.commands.compat import register_compat_commands
from changdu.commands.image import image_app
from changdu.commands.task import task_app
from changdu.commands.trajectory import traj_app
from changdu.commands.video import video_app
from changdu.config import load_config
from changdu.errors import ChangduError, ErrorPayload
from changdu.trajectory.store import TrajectoryStore

app = typer.Typer(
    add_completion=False,
    help=(
        "畅读 changdu 命令行工具（火山方舟图像/视频生成）\n\n"
        "【初始化配置】\n"
        "  export CHANGDU_ARK_API_KEY=\"你的API Key\"\n"
        "  export CHANGDU_SEED_TEXT_ENDPOINT=\"你的文本端点ID\"    # 可选\n"
        "  export CHANGDU_SEEDREAM_ENDPOINT=\"你的图像端点ID\"    # 可选\n"
        "  export CHANGDU_SEEDANCE_ENDPOINT=\"你的视频端点ID\"    # 可选\n\n"
        "【快速开始】\n"
        "  1) 文生图：changdu text2image --prompt \"一只猫的肖像\" --ratio 1:1 --output ./out/cat.jpg\n"
        "  2) 文生视频：changdu text2video --prompt \"夜晚街景，电影感\" --wait --output ./out/clip.mp4\n"
        "  3) 查任务：changdu query_result --submit_id <任务ID>\n\n"
        "【核心命令】\n"
        "  text2image, image2image, text2video, image2video, multiframe2video, multimodal2video, frames2video\n"
    )
)


def render_error(err: ChangduError, as_json: bool) -> None:
    payload = ErrorPayload(code=err.code, message=err.message, request_id=err.request_id)
    if as_json:
        typer.echo(json.dumps(payload.__dict__, ensure_ascii=False))
    else:
        rid = f" request_id={err.request_id}" if err.request_id else ""
        typer.echo(f"[{payload.code}] {payload.message}{rid}", err=True)


@app.callback()
def root(
    ctx: typer.Context,
    api_key: str | None = typer.Option(None, "--api-key", help="临时指定 API Key。"),
    profile: str = typer.Option("default", "--profile", help="配置档名称。"),
    config_path: Path | None = typer.Option(None, "--config-path", help="指定配置文件。"),
    output_json: bool = typer.Option(False, "--json", help="JSON 输出。"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="详细日志。"),
    trajectory_dir: Path | None = typer.Option(None, "--trajectory-dir", help="任务记录目录。"),
    seed_text_endpoint: str | None = typer.Option(
        None, "--seed-text-endpoint", help="临时覆盖文本端点。"
    ),
    seedream_endpoint: str | None = typer.Option(
        None, "--seedream-endpoint", help="临时覆盖图片端点。"
    ),
    seedance_endpoint: str | None = typer.Option(
        None, "--seedance-endpoint", help="临时覆盖视频端点。"
    ),
) -> None:
    overrides: dict[str, Any] = {}
    if api_key:
        overrides["api_key"] = api_key
    if trajectory_dir:
        overrides["trajectory_dir"] = trajectory_dir
    if seed_text_endpoint:
        overrides["text_model"] = seed_text_endpoint
    if seedream_endpoint:
        overrides["image_model"] = seedream_endpoint
    if seedance_endpoint:
        overrides["video_model"] = seedance_endpoint
    config = load_config(profile=profile, config_path=config_path, overrides=overrides)
    store = TrajectoryStore(config.trajectory_dir)
    ctx.obj = AppContext(
        config=config,
        output_json=output_json,
        verbose=verbose,
        profile=profile,
        trajectory_store=store,
        config_path=config_path,
    )


app.add_typer(auth_app, name="auth")
# 高级命令默认隐藏，避免新手在首页看到重复入口；命令依然可用
app.add_typer(image_app, name="image", hidden=True)
app.add_typer(video_app, name="video", hidden=True)
app.add_typer(task_app, name="task", hidden=True)
app.add_typer(traj_app, name="trajectory", hidden=True)
app.add_typer(batch_app, name="batch", hidden=True)
register_compat_commands(app)


def main() -> None:
    try:
        app()
    except ChangduError as err:
        render_error(err, as_json="--json" in sys.argv)
        raise SystemExit(err.exit_code) from None


if __name__ == "__main__":
    main()
