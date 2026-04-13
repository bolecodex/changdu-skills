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
        asset: list[str] = typer.Option([], "--asset", help="Asset 素材ID引用（可选）。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(5, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待任务完成。"),
        output: Path | None = typer.Option(None, "--output", help="等待完成时的视频保存路径。"),
        return_last_frame: bool = typer.Option(False, "--return-last-frame", help="返回生成视频的尾帧URL（用于连续生成）。"),
        first_frame_url: str | None = typer.Option(None, "--first-frame-url", help="指定首帧图片URL（来自上一 clip 的尾帧）。"),
    ) -> None:
        _submit_video_compat(
            ctx=ctx,
            prompt=prompt,
            images=[],
            asset_ids=asset,
            ratio=ratio,
            duration=duration,
            model=model,
            wait=wait,
            output=output,
            run_name="text2video",
            return_last_frame=return_last_frame,
            first_frame_url=first_frame_url,
        )

    @app.command("multimodal2video", help="多图参考生成视频（支持 Asset 素材引用）。")
    def multimodal2video(
        ctx: typer.Context,
        image: list[Path] = typer.Option([], "--image", help="参考图，可重复传入。"),
        asset: list[str] = typer.Option([], "--asset", help="Asset 素材ID，可重复传入（自动转为 asset:// 引用）。"),
        prompt: str = typer.Option("", "--prompt", help="提示词。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(5, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待任务完成。"),
        output: Path | None = typer.Option(None, "--output", help="等待完成时的视频保存路径。"),
        return_last_frame: bool = typer.Option(False, "--return-last-frame", help="返回生成视频的尾帧URL（用于连续生成）。"),
        first_frame_url: str | None = typer.Option(None, "--first-frame-url", help="指定首帧图片URL（来自上一 clip 的尾帧）。"),
    ) -> None:
        _submit_video_compat(
            ctx=ctx,
            prompt=prompt,
            images=image,
            asset_ids=asset,
            ratio=ratio,
            duration=duration,
            model=model,
            wait=wait,
            output=output,
            run_name="multimodal2video",
            return_last_frame=return_last_frame,
            first_frame_url=first_frame_url,
        )

    @app.command("image2video", help="单图生成视频（支持 Asset 素材引用）。")
    def image2video(
        ctx: typer.Context,
        image: Path | None = typer.Option(None, "--image", help="参考图。"),
        asset: str | None = typer.Option(None, "--asset", help="Asset 素材ID（替代 --image）。"),
        prompt: str = typer.Option("", "--prompt", help="提示词。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(5, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待任务完成。"),
        output: Path | None = typer.Option(None, "--output", help="等待完成时的视频保存路径。"),
        return_last_frame: bool = typer.Option(False, "--return-last-frame", help="返回生成视频的尾帧URL（用于连续生成）。"),
        first_frame_url: str | None = typer.Option(None, "--first-frame-url", help="指定首帧图片URL（来自上一 clip 的尾帧）。"),
    ) -> None:
        images = [image] if image else []
        asset_ids = [asset] if asset else []
        if not images and not asset_ids:
            typer.echo("错误：必须传入 --image 或 --asset 之一。", err=True)
            raise typer.Exit(1)
        _submit_video_compat(
            ctx=ctx,
            prompt=prompt,
            images=images,
            asset_ids=asset_ids,
            ratio=ratio,
            duration=duration,
            model=model,
            wait=wait,
            output=output,
            run_name="image2video",
            return_last_frame=return_last_frame,
            first_frame_url=first_frame_url,
        )

    @app.command("multiframe2video", help="多图叙事生成视频（支持 Asset 素材引用）。")
    def multiframe2video(
        ctx: typer.Context,
        image: list[Path] = typer.Option([], "--image", help="多张故事帧。"),
        asset: list[str] = typer.Option([], "--asset", help="Asset 素材ID，可重复传入。"),
        prompt: str = typer.Option("", "--prompt", help="提示词。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(5, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待任务完成。"),
        output: Path | None = typer.Option(None, "--output", help="等待完成时的视频保存路径。"),
        return_last_frame: bool = typer.Option(False, "--return-last-frame", help="返回生成视频的尾帧URL（用于连续生成）。"),
        first_frame_url: str | None = typer.Option(None, "--first-frame-url", help="指定首帧图片URL（来自上一 clip 的尾帧）。"),
    ) -> None:
        _submit_video_compat(
            ctx=ctx,
            prompt=prompt,
            images=image,
            asset_ids=asset,
            ratio=ratio,
            duration=duration,
            model=model,
            wait=wait,
            output=output,
            run_name="multiframe2video",
            return_last_frame=return_last_frame,
            first_frame_url=first_frame_url,
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

    @app.command("upload", help="上传文件到火山引擎 TOS 对象存储。")
    def upload(
        ctx: typer.Context,
        file: Path = typer.Argument(..., help="要上传的本地文件路径。"),
        bucket: str = typer.Option(None, "--bucket", help="TOS 桶名称（或 CHANGDU_TOS_BUCKET）。"),
        key: str | None = typer.Option(None, "--key", help="对象Key（默认为文件名）。"),
        prefix: str = typer.Option("", "--prefix", help="对象Key前缀（如 videos/ep001/）。"),
        public: bool = typer.Option(True, "--public/--private", help="是否设为公开读。"),
        ak: str | None = typer.Option(None, "--ak", help="火山引擎 Access Key（或 VOLC_ACCESSKEY）。"),
        sk: str | None = typer.Option(None, "--sk", help="火山引擎 Secret Key（或 VOLC_SECRETKEY）。"),
        tos_endpoint: str | None = typer.Option(None, "--tos-endpoint", help="TOS 端点（或 CHANGDU_TOS_ENDPOINT）。"),
        region: str | None = typer.Option(None, "--region", help="TOS 地域（或 CHANGDU_TOS_REGION）。"),
    ) -> None:
        import os
        from changdu.client.tos_upload import upload_file

        resolved_ak = ak or os.getenv("VOLC_ACCESSKEY") or os.getenv("CHANGDU_TOS_AK")
        resolved_sk = sk or os.getenv("VOLC_SECRETKEY") or os.getenv("CHANGDU_TOS_SK")
        resolved_bucket = bucket or os.getenv("CHANGDU_TOS_BUCKET")
        resolved_endpoint = tos_endpoint or os.getenv("CHANGDU_TOS_ENDPOINT", "tos-cn-beijing.volces.com")
        resolved_region = region or os.getenv("CHANGDU_TOS_REGION", "cn-beijing")

        if not resolved_ak or not resolved_sk:
            typer.echo("错误：缺少火山引擎 AK/SK。请设置 VOLC_ACCESSKEY + VOLC_SECRETKEY 环境变量，或通过 --ak/--sk 传入。", err=True)
            raise typer.Exit(1)
        if not resolved_bucket:
            typer.echo("错误：缺少 TOS 桶名。请设置 CHANGDU_TOS_BUCKET 环境变量，或通过 --bucket 传入。", err=True)
            raise typer.Exit(1)

        obj_key = key if key else (prefix + file.name)

        obj: AppContext = ctx.obj
        run_id = obj.trajectory_store.create_run("upload")

        try:
            result = upload_file(
                file_path=file,
                bucket=resolved_bucket,
                key=obj_key,
                ak=resolved_ak,
                sk=resolved_sk,
                endpoint=resolved_endpoint,
                region=resolved_region,
                public=public,
            )
        except FileNotFoundError as e:
            typer.echo(f"错误：{e}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            typer.echo(f"上传失败：{e}", err=True)
            raise typer.Exit(1)

        obj.trajectory_store.append_event(run_id, "uploaded", {
            "bucket": result.bucket,
            "key": result.key,
            "url": result.url,
            "status_code": result.status_code,
        })
        _emit(
            obj,
            {"bucket": result.bucket, "key": result.key, "url": result.url, "status": "success"},
            [f"桶: {result.bucket}", f"Key: {result.key}", f"URL: {result.url}", f"状态: 上传成功"],
        )

    # ── Asset 素材管理命令 ──

    def _build_assets_client():
        import os
        from changdu.client.assets import AssetsClient
        ak = os.getenv("VOLC_ACCESSKEY")
        sk = os.getenv("VOLC_SECRETKEY")
        if not ak or not sk:
            typer.echo("错误：缺少 VOLC_ACCESSKEY / VOLC_SECRETKEY 环境变量。", err=True)
            raise typer.Exit(1)
        region = os.getenv("CHANGDU_TOS_REGION", "cn-beijing")
        host = os.getenv("CHANGDU_ASSETS_HOST", "open.volcengineapi.com")
        return AssetsClient(ak=ak, sk=sk, region=region, host=host)

    @app.command("asset-group-create", help="创建素材资产组合（用于管理同一人物的素材）。")
    def asset_group_create(
        ctx: typer.Context,
        name: str = typer.Option(..., "--name", help="素材组名称。"),
        description: str = typer.Option("", "--description", help="素材组描述。"),
        project: str = typer.Option("default", "--project", help="项目名称。"),
    ) -> None:
        obj: AppContext = ctx.obj
        client = _build_assets_client()
        group = client.create_group(name=name, description=description, project_name=project)
        _emit(
            obj,
            {"group_id": group.id, "name": name, "status": "created"},
            [f"素材组ID: {group.id}", f"名称: {name}", "状态: 创建成功"],
        )

    @app.command("asset-create", help="上传素材（图片/视频/音频）到素材资产库。")
    def asset_create(
        ctx: typer.Context,
        url: str = typer.Option(None, "--url", help="素材的公开可访问 URL。"),
        file: Path | None = typer.Option(None, "--file", help="本地文件（自动上传到 TOS 获取 URL）。"),
        group_id: str = typer.Option(..., "--group-id", help="所属素材组 ID。"),
        asset_type: str = typer.Option("Image", "--type", help="素材类型: Image/Video/Audio。"),
        name: str = typer.Option("", "--name", help="素材名称（可选，用于检索）。"),
        project: str = typer.Option("default", "--project", help="项目名称。"),
        wait: bool = typer.Option(True, "--wait/--no-wait", help="等待素材处理完成。"),
    ) -> None:
        import os
        obj: AppContext = ctx.obj

        if not url and not file:
            typer.echo("错误：必须传入 --url 或 --file 之一。", err=True)
            raise typer.Exit(1)

        if file and not url:
            from changdu.client.tos_upload import upload_file
            resolved_ak = os.getenv("VOLC_ACCESSKEY")
            resolved_sk = os.getenv("VOLC_SECRETKEY")
            resolved_bucket = os.getenv("CHANGDU_TOS_BUCKET")
            resolved_endpoint = os.getenv("CHANGDU_TOS_ENDPOINT", "tos-cn-beijing.volces.com")
            resolved_region = os.getenv("CHANGDU_TOS_REGION", "cn-beijing")
            if not resolved_ak or not resolved_sk or not resolved_bucket:
                typer.echo("错误：本地文件上传需要 VOLC_ACCESSKEY / VOLC_SECRETKEY / CHANGDU_TOS_BUCKET。", err=True)
                raise typer.Exit(1)
            typer.echo(f"正在上传 {file.name} 到 TOS ...")
            tos_result = upload_file(
                file_path=file, bucket=resolved_bucket, key=f"assets/{file.name}",
                ak=resolved_ak, sk=resolved_sk, endpoint=resolved_endpoint,
                region=resolved_region, public=True,
            )
            url = tos_result.url
            typer.echo(f"TOS URL: {url}")

        client = _build_assets_client()
        asset = client.create_asset(group_id=group_id, url=url, asset_type=asset_type, name=name, project_name=project)
        typer.echo(f"素材ID: {asset.id}  状态: 处理中...")

        if wait:
            asset = client.wait_for_active(asset.id, project_name=project)
            typer.echo(f"素材ID: {asset.id}  状态: 可用")
            typer.echo(f"引用URL: {asset.asset_url}")

        _emit(
            obj,
            {"asset_id": asset.id, "asset_url": asset.asset_url, "status": asset.status},
            [] if wait else [f"素材ID: {asset.id}", f"引用URL: {asset.asset_url}", f"状态: {asset.status}"],
        )

    @app.command("asset-get", help="查询单个素材状态。")
    def asset_get(
        ctx: typer.Context,
        asset_id: str = typer.Option(..., "--id", help="素材 ID。"),
        project: str = typer.Option("default", "--project", help="项目名称。"),
    ) -> None:
        obj: AppContext = ctx.obj
        client = _build_assets_client()
        asset = client.get_asset(asset_id, project_name=project)
        status_cn = {"Active": "可用", "Processing": "处理中", "Failed": "失败"}.get(asset.status, asset.status)
        _emit(
            obj,
            {"asset_id": asset.id, "status": asset.status, "asset_url": asset.asset_url, "type": asset.asset_type, "url": asset.url},
            [f"素材ID: {asset.id}", f"类型: {asset.asset_type}", f"状态: {status_cn}", f"引用URL: {asset.asset_url}", f"原始URL: {asset.url or '-'}"],
        )

    @app.command("asset-list", help="列出素材资产。")
    def asset_list(
        ctx: typer.Context,
        group_id: str | None = typer.Option(None, "--group-id", help="按素材组 ID 过滤。"),
        status: str | None = typer.Option(None, "--status", help="按状态过滤: Active/Processing/Failed。"),
        project: str = typer.Option("default", "--project", help="项目名称。"),
        page: int = typer.Option(1, "--page", help="页码。"),
        page_size: int = typer.Option(20, "--page-size", help="每页数量。"),
    ) -> None:
        obj: AppContext = ctx.obj
        client = _build_assets_client()
        group_ids = [group_id] if group_id else None
        statuses = [status] if status else None
        assets = client.list_assets(group_ids=group_ids, statuses=statuses, page=page, page_size=page_size, project_name=project)
        if obj.output_json:
            typer.echo(json.dumps({"assets": [{"id": a.id, "name": a.name, "type": a.asset_type, "status": a.status, "asset_url": a.asset_url} for a in assets]}, ensure_ascii=False))
            return
        if not assets:
            typer.echo("暂无素材。")
            return
        for a in assets:
            status_cn = {"Active": "可用", "Processing": "处理中", "Failed": "失败"}.get(a.status, a.status)
            typer.echo(f"  {a.id}  类型={a.asset_type}  状态={status_cn}  名称={a.name or '-'}  引用={a.asset_url}")

    @app.command("asset-delete", help="删除单个素材。")
    def asset_delete(
        ctx: typer.Context,
        asset_id: str = typer.Option(..., "--id", help="要删除的素材 ID。"),
        project: str = typer.Option("default", "--project", help="项目名称。"),
    ) -> None:
        obj: AppContext = ctx.obj
        client = _build_assets_client()
        client.delete_asset(asset_id, project_name=project)
        _emit(obj, {"asset_id": asset_id, "status": "deleted"}, [f"素材ID: {asset_id}", "状态: 已删除"])

    @app.command("asset-group-list", help="列出素材组。")
    def asset_group_list(
        ctx: typer.Context,
        project: str = typer.Option("default", "--project", help="项目名称。"),
    ) -> None:
        obj: AppContext = ctx.obj
        client = _build_assets_client()
        groups = client.list_groups(project_name=project)
        if obj.output_json:
            typer.echo(json.dumps({"groups": [{"id": g.id, "name": g.name, "description": g.description} for g in groups]}, ensure_ascii=False))
            return
        if not groups:
            typer.echo("暂无素材组。")
            return
        for g in groups:
            typer.echo(f"  {g.id}  名称={g.name}  描述={g.description or '-'}")

    @app.command("sequential-generate", help="按顺序生成多个视频片段，自动用前一个视频的尾帧衔接下一个，保证连贯性。")
    def sequential_generate(
        ctx: typer.Context,
        prompt_dir: Path = typer.Option(..., "--prompt-dir", help="包含 视频_ClipXXX.prompt.txt 的目录。"),
        image: list[Path] = typer.Option([], "--image", help="参考图（每个 clip 共享），可重复传入。"),
        asset: list[str] = typer.Option([], "--asset", help="Asset 素材ID（每个 clip 共享），可重复传入。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(15, "--duration", help="每个 clip 的时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        output_dir: Path = typer.Option(None, "--output-dir", help="视频输出目录（默认同 prompt-dir）。"),
        extract_keyframes: bool = typer.Option(True, "--extract-keyframes/--no-keyframes", help="是否从前一 clip 抽取关键帧作为额外参考。"),
        prompt_header: str = typer.Option("", "--prompt-header", help="每个 clip 提示词前缀（如角色/场景说明）。"),
    ) -> None:
        import re
        from changdu.utils import extract_keyframes as _extract_kf

        obj: AppContext = ctx.obj
        out_dir = output_dir or prompt_dir

        prompt_files = sorted(
            [f for f in prompt_dir.iterdir() if re.match(r"视频_Clip\d+\.prompt\.txt$", f.name)],
            key=lambda f: f.name,
        )
        if not prompt_files:
            typer.echo(f"错误：在 {prompt_dir} 中未找到 视频_ClipXXX.prompt.txt 文件。", err=True)
            raise typer.Exit(1)

        typer.echo(f"共发现 {len(prompt_files)} 个 clip 待生成，将按顺序逐个生成（尾帧衔接模式）")

        last_frame_url: str | None = None
        for idx, pf in enumerate(prompt_files):
            clip_num = re.search(r"Clip(\d+)", pf.name)
            clip_label = clip_num.group(0) if clip_num else f"Clip{idx+1:03d}"
            clip_prompt = pf.read_text(encoding="utf-8").strip()
            full_prompt = f"{prompt_header}{clip_prompt}" if prompt_header else clip_prompt
            clip_output = out_dir / f"视频_{clip_label}.mp4"

            typer.echo(f"\n{'='*50}")
            typer.echo(f"[{idx+1}/{len(prompt_files)}] 正在生成 {clip_label} ...")

            extra_ref_images: list[Path] = []
            if idx > 0 and extract_keyframes and not last_frame_url:
                prev_clip = out_dir / f"视频_{prev_label}.mp4"
                if prev_clip.exists():
                    typer.echo(f"  从 {prev_label} 抽取关键帧 ...")
                    kf_dir = out_dir / "keyframes"
                    extra_ref_images = _extract_kf(prev_clip, kf_dir)
                    typer.echo(f"  抽取到 {len(extra_ref_images)} 帧参考图")

            all_images = list(image) + extra_ref_images if not last_frame_url else []

            result = _submit_video_compat(
                ctx=ctx,
                prompt=full_prompt,
                images=all_images,
                asset_ids=asset,
                ratio=ratio,
                duration=duration,
                model=model,
                wait=True,
                output=clip_output,
                run_name=f"sequential-{clip_label}",
                return_last_frame=True,
                first_frame_url=last_frame_url,
            )

            if result and result.last_frame_url:
                last_frame_url = result.last_frame_url
                typer.echo(f"  尾帧URL已缓存，将用于 {clip_label} → 下一 clip 衔接")
            else:
                last_frame_url = None

            prev_label = clip_label

        typer.echo(f"\n{'='*50}")
        typer.echo(f"全部 {len(prompt_files)} 个 clip 生成完毕！输出目录: {out_dir}")

    @app.command("clip-regen", help="重新生成单个 clip，可指定前一 clip 提供视觉上下文。")
    def clip_regen(
        ctx: typer.Context,
        clip: int = typer.Option(..., "--clip", help="要重新生成的 clip 编号（如 4）。"),
        prompt_dir: Path = typer.Option(..., "--prompt-dir", help="包含 视频_ClipXXX.prompt.txt 的目录。"),
        image: list[Path] = typer.Option([], "--image", help="参考图，可重复传入。"),
        asset: list[str] = typer.Option([], "--asset", help="Asset 素材ID，可重复传入。"),
        prev_clip: Path | None = typer.Option(None, "--prev-clip", help="前一 clip 的视频文件（用于抽取尾帧作为参考）。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(15, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        prompt_header: str = typer.Option("", "--prompt-header", help="提示词前缀。"),
        output: Path | None = typer.Option(None, "--output", help="输出路径（默认覆盖原文件）。"),
    ) -> None:
        from changdu.utils import extract_keyframes as _extract_kf

        clip_label = f"Clip{clip:03d}"
        prompt_file = prompt_dir / f"视频_{clip_label}.prompt.txt"
        if not prompt_file.exists():
            typer.echo(f"错误：未找到 {prompt_file}", err=True)
            raise typer.Exit(1)

        clip_prompt = prompt_file.read_text(encoding="utf-8").strip()
        full_prompt = f"{prompt_header}{clip_prompt}" if prompt_header else clip_prompt
        clip_output = output or (prompt_dir / f"视频_{clip_label}.mp4")

        typer.echo(f"正在重新生成 {clip_label} ...")

        extra_ref_images: list[Path] = []
        if prev_clip and prev_clip.exists():
            typer.echo(f"  从 {prev_clip.name} 抽取关键帧作为参考 ...")
            kf_dir = prompt_dir / "keyframes"
            extra_ref_images = _extract_kf(prev_clip, kf_dir)
            typer.echo(f"  抽取到 {len(extra_ref_images)} 帧参考图")

        all_images = list(image) + extra_ref_images

        result = _submit_video_compat(
            ctx=ctx,
            prompt=full_prompt,
            images=all_images,
            asset_ids=asset,
            ratio=ratio,
            duration=duration,
            model=model,
            wait=True,
            output=clip_output,
            run_name=f"clip-regen-{clip_label}",
            return_last_frame=True,
        )

        if result and result.last_frame_url:
            typer.echo(f"  新尾帧URL: {result.last_frame_url}")
        typer.echo(f"{clip_label} 重新生成完毕: {clip_output}")

    @app.command("clip-transition", help="用 ffmpeg 在两个 clip 之间添加转场效果（淡入淡出/裁剪/拼接）。")
    def clip_transition(
        ctx: typer.Context,
        clip_a: Path = typer.Option(..., "--clip-a", help="前一个视频片段。"),
        clip_b: Path = typer.Option(..., "--clip-b", help="后一个视频片段。"),
        transition: str = typer.Option("fade", "--transition", help="转场类型：fade/dissolve/wipeleft/none。"),
        trans_duration: float = typer.Option(0.5, "--duration", help="转场时长（秒）。"),
        trim_a_tail: float = typer.Option(0.0, "--trim-a-tail", help="裁掉前一 clip 尾部的秒数。"),
        trim_b_head: float = typer.Option(0.0, "--trim-b-head", help="裁掉后一 clip 头部的秒数。"),
        output: Path = typer.Option(..., "--output", help="输出合并后的视频路径。"),
    ) -> None:
        import subprocess

        if not clip_a.exists():
            typer.echo(f"错误：文件不存在 {clip_a}", err=True)
            raise typer.Exit(1)
        if not clip_b.exists():
            typer.echo(f"错误：文件不存在 {clip_b}", err=True)
            raise typer.Exit(1)

        output.parent.mkdir(parents=True, exist_ok=True)
        tmp_a = output.parent / f"_trim_a_{clip_a.name}"
        tmp_b = output.parent / f"_trim_b_{clip_b.name}"

        try:
            src_a = clip_a
            if trim_a_tail > 0:
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip_a)],
                    capture_output=True, text=True, timeout=10,
                )
                dur_a = float(probe.stdout.strip()) if probe.stdout.strip() else 15.0
                end_a = max(dur_a - trim_a_tail, 1.0)
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(clip_a), "-to", str(end_a), "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(tmp_a)],
                    capture_output=True, timeout=120,
                )
                src_a = tmp_a
                typer.echo(f"  裁剪 {clip_a.name} 尾部 {trim_a_tail}s → {end_a:.1f}s")

            src_b = clip_b
            if trim_b_head > 0:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(clip_b), "-ss", str(trim_b_head), "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(tmp_b)],
                    capture_output=True, timeout=120,
                )
                src_b = tmp_b
                typer.echo(f"  裁剪 {clip_b.name} 头部 {trim_b_head}s")

            if transition == "none":
                filelist = output.parent / "_concat_list.txt"
                filelist.write_text(f"file '{src_a}'\nfile '{src_b}'\n")
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(filelist), "-c", "copy", str(output)],
                    capture_output=True, timeout=120,
                )
                filelist.unlink(missing_ok=True)
            else:
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src_a)],
                    capture_output=True, text=True, timeout=10,
                )
                offset = float(probe.stdout.strip()) - trans_duration if probe.stdout.strip() else 14.5
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(src_a), "-i", str(src_b),
                     "-filter_complex", f"xfade=transition={transition}:duration={trans_duration}:offset={offset}",
                     "-c:v", "libx264", "-crf", "18", str(output)],
                    capture_output=True, timeout=120,
                )

            typer.echo(f"转场合并完成: {output}")
        finally:
            tmp_a.unlink(missing_ok=True)
            tmp_b.unlink(missing_ok=True)

    @app.command("color-match", help="对目录下所有 clip 进行亮度/色调统一处理。")
    def color_match(
        ctx: typer.Context,
        input_dir: Path = typer.Option(..., "--input-dir", help="包含 视频_ClipXXX.mp4 的目录。"),
        output_dir: Path = typer.Option(None, "--output-dir", help="调色后输出目录（默认在原目录下创建 graded/ 子目录）。"),
        brightness: float = typer.Option(0.0, "--brightness", help="亮度调整（-1.0 到 1.0）。"),
        contrast: float = typer.Option(1.0, "--contrast", help="对比度（0.5 到 2.0，默认 1.0 不变）。"),
        saturation: float = typer.Option(1.0, "--saturation", help="饱和度（0.0 到 3.0，默认 1.0 不变）。"),
        gamma: float = typer.Option(1.0, "--gamma", help="伽马值（0.1 到 10.0，默认 1.0 不变）。"),
        preset: str | None = typer.Option(None, "--preset", help="曲线预设：vintage/strong_contrast/darker/lighter。"),
    ) -> None:
        import re
        import subprocess

        out_dir = output_dir or (input_dir / "graded")
        out_dir.mkdir(parents=True, exist_ok=True)

        clips = sorted(
            [f for f in input_dir.iterdir() if re.match(r"视频_Clip\d+\.mp4$", f.name)],
            key=lambda f: f.name,
        )
        if not clips:
            typer.echo(f"错误：在 {input_dir} 中未找到 视频_ClipXXX.mp4 文件。", err=True)
            raise typer.Exit(1)

        vf_parts: list[str] = []
        needs_eq = brightness != 0.0 or contrast != 1.0 or saturation != 1.0 or gamma != 1.0
        if needs_eq:
            vf_parts.append(f"eq=brightness={brightness}:contrast={contrast}:saturation={saturation}:gamma={gamma}")
        if preset:
            vf_parts.append(f"curves=preset={preset}")

        if not vf_parts:
            vf_parts.append("eq=brightness=0:contrast=1")

        vf = ",".join(vf_parts)
        typer.echo(f"调色滤镜: {vf}")
        typer.echo(f"共 {len(clips)} 个 clip 待处理")

        for clip in clips:
            out_path = out_dir / clip.name
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(clip), "-vf", vf, "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(out_path)],
                capture_output=True, timeout=300,
            )
            typer.echo(f"  {clip.name} → {out_path}")

        typer.echo(f"全部调色完成，输出目录: {out_dir}")

    @app.command("examples", help="显示可直接复制的示例命令。")
    def examples() -> None:
        typer.echo("【环境变量配置】")
        typer.echo('export CHANGDU_ARK_API_KEY="你的API Key"')
        typer.echo('export CHANGDU_SEED_TEXT_ENDPOINT="你的文本端点ID"    # 可选')
        typer.echo('export CHANGDU_SEEDREAM_ENDPOINT="你的图像端点ID"    # 可选')
        typer.echo('export CHANGDU_SEEDANCE_ENDPOINT="你的视频端点ID"    # 可选')
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
        typer.echo("")
        typer.echo("【示例5：上传文件到 TOS】")
        typer.echo("changdu upload ./out/clip.mp4 --bucket my-bucket --prefix videos/")
        typer.echo("changdu upload ./out/cat.jpg --bucket my-bucket --public")
        typer.echo("")
        typer.echo("【示例6：真人剧 — 素材资产管理（Assets）】")
        typer.echo('# 1) 创建素材组')
        typer.echo('changdu asset-group-create --name "我的角色组"')
        typer.echo('# 2) 上传角色照片入库（本地文件自动走 TOS）')
        typer.echo('changdu asset-create --file ./角色/女主.jpg --group-id <素材组ID> --type Image')
        typer.echo('# 3) 查看素材状态')
        typer.echo('changdu asset-get --id <素材ID>')
        typer.echo('# 4) 用素材生成真人视频')
        typer.echo('changdu multimodal2video --asset <素材ID> --asset <素材ID2> --prompt "图片1的女孩..." --wait --output clip.mp4')
        typer.echo("")
        typer.echo("【示例7：连续视频生成（尾帧衔接）】")
        typer.echo("# 一键顺序生成多个 clip，自动用前一 clip 的尾帧作为下一 clip 的首帧")
        typer.echo("changdu sequential-generate \\")
        typer.echo("  --prompt-dir ./单集制作/EP001/ \\")
        typer.echo("  --asset <角色ID> --asset <场景ID> \\")
        typer.echo("  --ratio 16:9 --duration 15 \\")
        typer.echo('  --prompt-header "图片1是主角，图片2是场景。" \\')
        typer.echo("  --output-dir ./单集制作/EP001/")
        typer.echo("")
        typer.echo("【示例8：手动尾帧衔接（单个命令）】")
        typer.echo("# 第1个 clip：生成视频并返回尾帧URL")
        typer.echo('changdu multimodal2video --image 角色.jpg --prompt "..." --wait --output clip001.mp4 --return-last-frame')
        typer.echo("# 第2个 clip：将上一 clip 的尾帧URL作为首帧")
        typer.echo('changdu multimodal2video --image 角色.jpg --prompt "..." --wait --output clip002.mp4 --return-last-frame --first-frame-url <上一clip的尾帧URL>')
        typer.echo("")
        typer.echo("【示例9：单 clip 重新生成（修复穿帮）】")
        typer.echo("# 用改进后的 prompt 重新生成第4个 clip，用第3个 clip 的尾帧做参考")
        typer.echo("changdu clip-regen \\")
        typer.echo("  --clip 4 --prompt-dir ./单集制作/EP002/ \\")
        typer.echo("  --asset <角色ID> --asset <场景ID> \\")
        typer.echo("  --prev-clip ./单集制作/EP002/视频_Clip003.mp4 \\")
        typer.echo("  --ratio 16:9 --duration 15")
        typer.echo("")
        typer.echo("【示例10：相邻 clip 添加转场】")
        typer.echo("# 裁掉 clip3 尾部2秒 + clip4 头部1秒，添加淡入淡出转场")
        typer.echo("changdu clip-transition \\")
        typer.echo("  --clip-a 视频_Clip003.mp4 --clip-b 视频_Clip004.mp4 \\")
        typer.echo("  --transition fade --duration 0.5 \\")
        typer.echo("  --trim-a-tail 2.0 --trim-b-head 1.0 \\")
        typer.echo("  --output merged_003_004.mp4")
        typer.echo("")
        typer.echo("【示例11：全片色调统一】")
        typer.echo("# 偏暗月光色调 + vintage 曲线")
        typer.echo("changdu color-match \\")
        typer.echo("  --input-dir ./单集制作/EP002/ \\")
        typer.echo("  --output-dir ./单集制作/EP002/graded/ \\")
        typer.echo("  --brightness -0.05 --contrast 1.1 --saturation 0.9 \\")
        typer.echo("  --preset vintage")


def _submit_video_compat(
    *,
    ctx: typer.Context,
    prompt: str,
    images: list[Path],
    asset_ids: list[str] | None = None,
    ratio: str,
    duration: int,
    model: str | None,
    wait: bool,
    output: Path | None,
    run_name: str,
    return_last_frame: bool = False,
    first_frame_url: str | None = None,
) -> Any:
    """Submit a video generation request. Returns TaskStatusResponse when wait=True, None otherwise."""

    obj: AppContext = ctx.obj
    run_id = obj.trajectory_store.create_run(run_name)
    encoded_images = [encode_image_to_data_url(p) for p in images]
    asset_urls = [f"asset://{aid}" if not aid.startswith("asset://") else aid for aid in (asset_ids or [])]
    all_image_refs = encoded_images + asset_urls
    req = VideoGenerateRequest(
        model=model or obj.config.video_model,
        prompt=prompt,
        ratio=ratio,
        duration=duration,
        images=all_image_refs,
        return_last_frame=return_last_frame,
        first_frame_url=first_frame_url,
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
        return None

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

    out_payload: dict[str, Any] = {
        "submit_id": submitted.task_id,
        "status": result.status,
        "output": str(output) if output else None,
    }
    pretty: list[str] = [
        f"任务ID: {submitted.task_id}",
        f"状态: {_status_cn(result.status)}",
        f"已保存: {output}" if output else "已保存: -",
    ]
    if result.last_frame_url:
        out_payload["last_frame_url"] = result.last_frame_url
        pretty.append(f"尾帧URL: {result.last_frame_url}")
    _emit(obj, out_payload, pretty)
    return result


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
