"""User-facing commands for changdu."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from changdu import __version__
from changdu.cli.context import AppContext
from changdu.client.ark_base import ArkClient
from changdu.client.polling import PollConfig, poll_task
from changdu.client.seedance import SeedanceClient
from changdu.client.seedream import SeedreamClient
from changdu.errors import RequestError
from changdu.models.requests import ImageGenerateRequest, VideoGenerateRequest
from changdu.utils import download_binary, encode_image_to_data_url


def _status_cn(status: str) -> str:
    m = {
        "submitted": "已提交",
        "success": "成功",
        "succeeded": "成功",
        "running": "执行中",
        "pending": "排队中",
        "failed": "失败",
        "error": "失败",
        "cancelled": "已取消",
        "canceled": "已取消",
    }
    return m.get(status.lower(), status)


def _build_seedream(obj: AppContext) -> SeedreamClient:
    return SeedreamClient(
        client=ArkClient(api_key=obj.config.api_key, base_url=obj.config.base_url, timeout_s=obj.config.request_timeout_s),
        endpoint=obj.config.image_endpoint,
    )


def _build_seedance(obj: AppContext) -> SeedanceClient:
    return SeedanceClient(
        client=ArkClient(api_key=obj.config.api_key, base_url=obj.config.base_url, timeout_s=obj.config.request_timeout_s),
        submit_endpoint=obj.config.video_submit_endpoint,
        status_endpoint_template=obj.config.video_status_endpoint_template,
    )


def _emit(obj: AppContext, payload: dict[str, Any], pretty_lines: list[str]) -> None:
    if obj.output_json:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        for line in pretty_lines:
            typer.echo(line)


def register_compat_commands(app: typer.Typer) -> None:
    @app.command("version", help="显示版本信息。")
    def version() -> None:
        typer.echo(f"畅读 changdu {__version__}")

    @app.command("text2image", help="文本生成图片。")
    def text2image(
        ctx: typer.Context,
        prompt: str = typer.Option(..., "--prompt", help="提示词。"),
        ratio: str | None = typer.Option(None, "--ratio", help="画幅比例提示，如 1:1、16:9。"),
        resolution_type: str = typer.Option("2k", "--resolution_type", help="分辨率档位，如 1k/2k。"),
        endpoint: str | None = typer.Option(None, "--endpoint", help="覆盖图片模型/端点 ID。"),
        output: Path = typer.Option(Path("./outputs/text2image.jpg"), "--output", help="输出图片路径。"),
    ) -> None:
        obj: AppContext = ctx.obj
        run_id = obj.trajectory_store.create_run("text2image")
        content = prompt if not ratio else f"{prompt}。画幅比例 {ratio}"
        size = "2K" if resolution_type.lower() == "2k" else resolution_type.upper()

        req = ImageGenerateRequest(model=endpoint or obj.config.image_model, prompt=content, size=size)
        result = _build_seedream(obj).generate(req)
        _build_seedream(obj).write_output(result, output)
        obj.trajectory_store.append_event(run_id, "result", {"output": str(output), "request_id": result.request_id})
        _emit(
            obj,
            {"submit_id": run_id, "output": str(output), "request_id": result.request_id, "status": "success"},
            [f"任务ID: {run_id}", f"已保存: {output}", f"状态: {_status_cn('success')}"],
        )

    @app.command("text2video", help="文本生成视频。")
    def text2video(
        ctx: typer.Context,
        prompt: str = typer.Option(..., "--prompt", help="提示词。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(5, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待任务完成。"),
        output: Path | None = typer.Option(None, "--output", help="等待完成时的视频保存路径。"),
    ) -> None:
        _submit_video_compat(
            ctx=ctx,
            prompt=prompt,
            images=[],
            ratio=ratio,
            duration=duration,
            model=model,
            wait=wait,
            output=output,
            run_name="text2video",
        )

    @app.command("multimodal2video", help="多图参考生成视频。")
    def multimodal2video(
        ctx: typer.Context,
        image: list[Path] = typer.Option([], "--image", help="参考图，可重复传入。"),
        prompt: str = typer.Option("", "--prompt", help="提示词。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(5, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待任务完成。"),
        output: Path | None = typer.Option(None, "--output", help="等待完成时的视频保存路径。"),
    ) -> None:
        _submit_video_compat(
            ctx=ctx,
            prompt=prompt,
            images=image,
            ratio=ratio,
            duration=duration,
            model=model,
            wait=wait,
            output=output,
            run_name="multimodal2video",
        )

    @app.command("image2video", help="单图生成视频。")
    def image2video(
        ctx: typer.Context,
        image: Path = typer.Option(..., "--image", help="参考图。"),
        prompt: str = typer.Option("", "--prompt", help="提示词。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(5, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待任务完成。"),
        output: Path | None = typer.Option(None, "--output", help="等待完成时的视频保存路径。"),
    ) -> None:
        _submit_video_compat(
            ctx=ctx,
            prompt=prompt,
            images=[image],
            ratio=ratio,
            duration=duration,
            model=model,
            wait=wait,
            output=output,
            run_name="image2video",
        )

    @app.command("multiframe2video", help="多图叙事生成视频。")
    def multiframe2video(
        ctx: typer.Context,
        image: list[Path] = typer.Option([], "--image", help="多张故事帧。"),
        prompt: str = typer.Option("", "--prompt", help="提示词。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(5, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待任务完成。"),
        output: Path | None = typer.Option(None, "--output", help="等待完成时的视频保存路径。"),
    ) -> None:
        _submit_video_compat(
            ctx=ctx,
            prompt=prompt,
            images=image,
            ratio=ratio,
            duration=duration,
            model=model,
            wait=wait,
            output=output,
            run_name="multiframe2video",
        )

    @app.command("frames2video", help="首尾帧插值生成视频。")
    def frames2video(
        ctx: typer.Context,
        first_frame: Path = typer.Option(..., "--first_frame", help="首帧图片。"),
        last_frame: Path = typer.Option(..., "--last_frame", help="尾帧图片。"),
        prompt: str = typer.Option("", "--prompt", help="提示词。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待任务完成。"),
        output: Path | None = typer.Option(None, "--output", help="等待完成时的视频保存路径。"),
    ) -> None:
        _submit_video_compat(
            ctx=ctx,
            prompt=prompt,
            images=[first_frame, last_frame],
            ratio="16:9",
            duration=5,
            model=model,
            wait=wait,
            output=output,
            run_name="frames2video",
        )

    @app.command("query_result", help="按任务ID查询状态。")
    def query_result(
        ctx: typer.Context,
        submit_id: str = typer.Option(..., "--submit_id", help="任务 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待到最终状态。"),
        output: Path | None = typer.Option(None, "--output", help="等待成功后的视频保存路径。"),
        interval: int = typer.Option(10, "--interval", help="轮询间隔（秒）。"),
        timeout: int = typer.Option(900, "--timeout", help="最长等待时间（秒）。"),
    ) -> None:
        obj: AppContext = ctx.obj
        client = _build_seedance(obj)
        run_id = obj.trajectory_store.create_run("query_result")
        if not wait:
            status = client.status(submit_id)
            _emit(
                obj,
                {
                    "submit_id": submit_id,
                    "status": status.status,
                    "file_url": status.file_url,
                    "request_id": status.request_id,
                },
                [f"任务ID: {submit_id}", f"状态: {_status_cn(status.status)}", f"下载地址: {status.file_url or '-'}"],
            )
            return

        result = poll_task(
            fetcher=client.status,
            task_id=submit_id,
            config=PollConfig(interval_s=interval, max_wait_s=timeout),
            on_update=lambda r, n: obj.trajectory_store.append_event(
                run_id, "poll", {"submit_id": submit_id, "raw_status": r.status, "normalized": n}
            ),
        )
        if result.status.lower() in {"failed", "error", "cancelled", "canceled"}:
            raise RequestError(f"Task failed: {result.fail_reason or result.status}", request_id=result.request_id)
        if output and result.file_url:
            download_binary(result.file_url, output)
        _emit(
            obj,
            {"submit_id": submit_id, "status": result.status, "output": str(output) if output else None},
            [f"任务ID: {submit_id}", f"状态: {_status_cn(result.status)}", f"已保存: {output}" if output else "已保存: -"],
        )

    @app.command("list_task", help="列出本地任务记录。")
    def list_task(
        ctx: typer.Context,
        gen_status: str | None = typer.Option(None, "--gen_status", help="按状态过滤：success/running/failed。"),
    ) -> None:
        obj: AppContext = ctx.obj
        tasks = _collect_tasks(obj)
        if gen_status:
            status_map = {"success": "succeeded", "running": "running", "failed": "failed"}
            wanted = status_map.get(gen_status.lower(), gen_status.lower())
            tasks = [t for t in tasks if t.status == wanted]

        if obj.output_json:
            typer.echo(json.dumps({"tasks": [t.__dict__ for t in tasks]}, ensure_ascii=False))
            return
        if not tasks:
            typer.echo("暂无任务记录。")
            return
        for t in tasks:
            typer.echo(f"任务ID={t.submit_id} 状态={_status_cn(t.status)} 来源命令={t.command}")

    @app.command("image2image", help="多参考图生成图片。")
    def image2image(
        ctx: typer.Context,
        image: list[Path] = typer.Option([], "--image", help="参考图，可重复传入。"),
        prompt: str = typer.Option(..., "--prompt", help="编辑提示词。"),
        ratio: str | None = typer.Option(None, "--ratio", help="画幅比例提示，如 1:1、16:9。"),
        resolution_type: str = typer.Option("2k", "--resolution_type", help="分辨率档位，如 1k/2k。"),
        endpoint: str | None = typer.Option(None, "--endpoint", help="覆盖图片模型/端点 ID。"),
        output: Path = typer.Option(Path("./outputs/image2image.jpg"), "--output", help="输出图片路径。"),
    ) -> None:
        obj: AppContext = ctx.obj
        if not image:
            raise RequestError("image2image 至少需要传入一张 --image 参考图。")
        run_id = obj.trajectory_store.create_run("image2image")
        content = prompt if not ratio else f"{prompt}。画幅比例 {ratio}"
        size = "2K" if resolution_type.lower() == "2k" else resolution_type.upper()
        encoded_images = [encode_image_to_data_url(p) for p in image]
        req = ImageGenerateRequest(
            model=endpoint or obj.config.image_model,
            prompt=content,
            size=size,
            images=encoded_images,
        )
        cli = _build_seedream(obj)
        result = cli.generate(req)
        cli.write_output(result, output)
        obj.trajectory_store.append_event(
            run_id,
            "result",
            {"output": str(output), "request_id": result.request_id, "image_count": len(encoded_images)},
        )
        _emit(
            obj,
            {
                "submit_id": run_id,
                "output": str(output),
                "request_id": result.request_id,
                "status": "success",
                "image_count": len(encoded_images),
            },
            [f"任务ID: {run_id}", f"已保存: {output}", f"参考图数量: {len(encoded_images)}", f"状态: {_status_cn('success')}"],
        )

    @app.command("examples", help="显示可直接复制的示例命令。")
    def examples() -> None:
        typer.echo("【环境变量配置】")
        typer.echo('export CHANGDU_ARK_API_KEY="你的API Key"')
        typer.echo('export CHANGDU_SEED_TEXT_ENDPOINT="ep-m-20260328105436-n2x7w"')
        typer.echo('export CHANGDU_SEEDREAM_ENDPOINT="ep-m-20260403105201-9p9g6"')
        typer.echo('export CHANGDU_SEEDANCE_ENDPOINT="ep-20260326170052-hjksg"')
        typer.echo("")
        typer.echo("【示例1：文生图】")
        typer.echo('changdu text2image --prompt "一只猫的肖像" --ratio 1:1 --resolution_type 2k --output ./out/cat.jpg')
        typer.echo("")
        typer.echo("【示例2：图生图】")
        typer.echo(
            'changdu image2image --image ./a.jpg --image ./b.jpg --prompt "将图1衣服换成图2风格" --output ./out/edit.jpg'
        )
        typer.echo("")
        typer.echo("【示例3：文生视频并等待完成】")
        typer.echo('changdu text2video --prompt "夜晚街景，电影感" --wait --output ./out/clip.mp4')
        typer.echo("")
        typer.echo("【示例4：查询任务状态】")
        typer.echo("changdu query_result --submit_id <任务ID>")


def _submit_video_compat(
    *,
    ctx: typer.Context,
    prompt: str,
    images: list[Path],
    ratio: str,
    duration: int,
    model: str | None,
    wait: bool,
    output: Path | None,
    run_name: str,
) -> None:
    obj: AppContext = ctx.obj
    run_id = obj.trajectory_store.create_run(run_name)
    encoded_images = [encode_image_to_data_url(p) for p in images]
    req = VideoGenerateRequest(
        model=model or obj.config.video_model,
        prompt=prompt,
        ratio=ratio,
        duration=duration,
        images=encoded_images,
    )
    client = _build_seedance(obj)
    submitted = client.submit(req)
    obj.trajectory_store.append_event(run_id, "submitted", {"task_id": submitted.task_id, "request_id": submitted.request_id})
    if not wait:
        _emit(
            obj,
            {"submit_id": submitted.task_id, "run_id": run_id, "status": "submitted"},
            [f"任务ID: {submitted.task_id}", f"运行ID: {run_id}", f"状态: {_status_cn('submitted')}"],
        )
        return

    result = poll_task(
        fetcher=client.status,
        task_id=submitted.task_id,
        config=PollConfig(interval_s=obj.config.poll_interval_s, max_wait_s=obj.config.poll_max_wait_s),
        on_update=lambda r, n: obj.trajectory_store.append_event(
            run_id, "poll", {"submit_id": submitted.task_id, "raw_status": r.status, "normalized": n}
        ),
    )
    if result.status.lower() in {"failed", "error", "cancelled", "canceled"}:
        raise RequestError(f"Task failed: {result.fail_reason or result.status}", request_id=result.request_id)
    if output and result.file_url:
        download_binary(result.file_url, output)
    _emit(
        obj,
        {"submit_id": submitted.task_id, "status": result.status, "output": str(output) if output else None},
        [f"任务ID: {submitted.task_id}", f"状态: {_status_cn(result.status)}", f"已保存: {output}" if output else "已保存: -"],
    )


@dataclass
class CompatTask:
    submit_id: str
    status: str
    command: str


def _collect_tasks(obj: AppContext) -> list[CompatTask]:
    tasks: dict[str, CompatTask] = {}
    for run_id in obj.trajectory_store.list_runs():
        try:
            meta = obj.trajectory_store.read_meta(run_id)
            events = obj.trajectory_store.iter_events(run_id)
        except Exception:
            continue
        command = str(meta.get("command", "-"))
        for evt in events:
            payload = evt.get("payload", {})
            submit_id = (
                payload.get("task_id")
                or payload.get("submit_id")
                or payload.get("id")
            )
            if not submit_id:
                continue
            status = payload.get("normalized") or payload.get("status") or "submitted"
            status = str(status).lower()
            if status == "success":
                status = "succeeded"
            tasks[str(submit_id)] = CompatTask(submit_id=str(submit_id), status=status, command=command)
    return sorted(tasks.values(), key=lambda t: t.submit_id, reverse=True)
