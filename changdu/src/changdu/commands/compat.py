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
            payload: dict[str, Any] = {
                "submit_id": submit_id,
                "status": status.status,
                "file_url": status.file_url,
                "request_id": status.request_id,
            }
            pretty = [f"任务ID: {submit_id}", f"状态: {_status_cn(status.status)}", f"下载地址: {status.file_url or '-'}"]
            if status.last_frame_url:
                payload["last_frame_url"] = status.last_frame_url
                pretty.append(f"尾帧URL: {status.last_frame_url}")
            _emit(obj, payload, pretty)
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
        last_frame_path: Path | None = None
        if result.last_frame_url and output:
            last_frame_path = output.with_suffix(".lastframe.jpg")
            try:
                download_binary(result.last_frame_url, last_frame_path)
            except Exception:
                last_frame_path = None
        out_payload: dict[str, Any] = {"submit_id": submit_id, "status": result.status, "output": str(output) if output else None}
        pretty = [f"任务ID: {submit_id}", f"状态: {_status_cn(result.status)}", f"已保存: {output}" if output else "已保存: -"]
        if result.last_frame_url:
            out_payload["last_frame_url"] = result.last_frame_url
            pretty.append(f"尾帧URL: {result.last_frame_url}")
        if last_frame_path:
            out_payload["last_frame_path"] = str(last_frame_path)
            pretty.append(f"尾帧已保存: {last_frame_path}")
        _emit(obj, out_payload, pretty)

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

        already_done = 0
        for pf in prompt_files:
            cn = re.search(r"Clip(\d+)", pf.name)
            cl = cn.group(0) if cn else ""
            if (out_dir / f"视频_{cl}.mp4").exists():
                already_done += 1
            else:
                break

        if already_done > 0:
            typer.echo(f"发现 {already_done} 个已完成的 clip，从第 {already_done + 1} 个开始续做")

        typer.echo(f"共发现 {len(prompt_files)} 个 clip 待生成，将按顺序逐个生成（尾帧衔接模式）")

        last_frame_url: str | None = None
        for idx, pf in enumerate(prompt_files):
            clip_num = re.search(r"Clip(\d+)", pf.name)
            clip_label = clip_num.group(0) if clip_num else f"Clip{idx+1:03d}"
            clip_prompt = pf.read_text(encoding="utf-8").strip()
            full_prompt = f"{prompt_header}{clip_prompt}" if prompt_header else clip_prompt
            clip_output = out_dir / f"视频_{clip_label}.mp4"

            if clip_output.exists() and idx < already_done:
                typer.echo(f"\n{'='*50}")
                typer.echo(f"[{idx+1}/{len(prompt_files)}] {clip_label} 已存在，跳过")
                prev_label = clip_label
                last_frame_url = None
                continue

            typer.echo(f"\n{'='*50}")
            typer.echo(f"[{idx+1}/{len(prompt_files)}] 正在生成 {clip_label} ...")

            extra_ref_images: list[Path] = []
            if idx > 0 and not last_frame_url and extract_keyframes and not asset:
                prev_clip = out_dir / f"视频_{prev_label}.mp4"
                if prev_clip.exists():
                    typer.echo(f"  从 {prev_label} 抽取关键帧 ...")
                    kf_dir = out_dir / "keyframes"
                    extra_ref_images = _extract_kf(prev_clip, kf_dir)
                    typer.echo(f"  抽取到 {len(extra_ref_images)} 帧参考图")
            elif idx > 0 and not last_frame_url and asset:
                typer.echo(f"  使用 Asset 素材模式，依赖角色/场景素材保持一致性")

            resolved_first_frame = last_frame_url
            if asset:
                resolved_first_frame = None
                if idx > 0:
                    typer.echo(f"  Asset模式：跳过首帧衔接（API不支持混合），依赖素材+提示词保持一致性")

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
                run_name=f"sequential-{clip_label}",
                return_last_frame=True,
                first_frame_url=resolved_first_frame,
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
        prev_clip: Path | None = typer.Option(None, "--prev-clip", help="前一 clip 的视频文件（用于抽取尾帧作为参考图）。"),
        first_frame_url: str | None = typer.Option(None, "--first-frame-url", help="首帧图片URL（来自上一 clip 的尾帧），保证画面连续。优先于 --prev-clip。"),
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
        if first_frame_url:
            typer.echo(f"  使用首帧URL衔接（first_frame模式，保证画面连续）")
        elif prev_clip and prev_clip.exists():
            typer.echo(f"  从 {prev_clip.name} 抽取关键帧作为参考 ...")
            kf_dir = prompt_dir / "keyframes"
            extra_ref_images = _extract_kf(prev_clip, kf_dir)
            typer.echo(f"  抽取到 {len(extra_ref_images)} 帧参考图")

        all_images = list(image) + extra_ref_images if not first_frame_url else list(image)

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
            first_frame_url=first_frame_url,
        )

        if result and result.last_frame_url:
            typer.echo(f"  新尾帧URL: {result.last_frame_url}")
        typer.echo(f"{clip_label} 重新生成完毕: {clip_output}")

    @app.command("clip-chain-regen", help="连续重新生成多个 clip，自动用尾帧衔接保证画面连续（穿帮修复利器）。")
    def clip_chain_regen(
        ctx: typer.Context,
        clips: str = typer.Option(..., "--clips", help="要重新生成的 clip 编号列表，逗号分隔（如 2,3,4）。"),
        prompt_dir: Path = typer.Option(..., "--prompt-dir", help="包含 视频_ClipXXX.prompt.txt 的目录。"),
        image: list[Path] = typer.Option([], "--image", help="参考图（每个 clip 共享），可重复传入。"),
        asset: list[str] = typer.Option([], "--asset", help="Asset 素材ID（每个 clip 共享），可重复传入。"),
        start_frame_url: str | None = typer.Option(None, "--start-frame-url", help="链条起始首帧URL（来自前一 clip 的 last_frame_url）。"),
        regen_prev: bool = typer.Option(False, "--regen-prev", help="先重新生成 clips 列表前一个 clip 以获取 last_frame_url 作为起点。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(15, "--duration", help="每个 clip 的时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        prompt_header: str = typer.Option("", "--prompt-header", help="每个 clip 提示词前缀。"),
        output_dir: Path | None = typer.Option(None, "--output-dir", help="视频输出目录（默认同 prompt-dir）。"),
        concat: bool = typer.Option(False, "--concat", help="全部完成后自动拼接所有 clip 为完整视频。"),
        concat_output: Path | None = typer.Option(None, "--concat-output", help="拼接输出路径（需配合 --concat）。"),
    ) -> None:
        clip_nums = [int(c.strip()) for c in clips.split(",") if c.strip()]
        if not clip_nums:
            typer.echo("错误：--clips 参数为空。", err=True)
            raise typer.Exit(1)

        out_dir = output_dir or prompt_dir

        for cn in clip_nums:
            pf = prompt_dir / f"视频_Clip{cn:03d}.prompt.txt"
            if not pf.exists():
                typer.echo(f"错误：未找到 {pf}", err=True)
                raise typer.Exit(1)

        last_frame_url: str | None = start_frame_url

        if regen_prev and not last_frame_url:
            prev_num = clip_nums[0] - 1
            if prev_num >= 1:
                prev_label = f"Clip{prev_num:03d}"
                prev_prompt_file = prompt_dir / f"视频_{prev_label}.prompt.txt"
                if prev_prompt_file.exists():
                    typer.echo(f"先重新生成 {prev_label} 以获取尾帧URL ...")
                    prev_prompt = prev_prompt_file.read_text(encoding="utf-8").strip()
                    prev_full = f"{prompt_header}{prev_prompt}" if prompt_header else prev_prompt
                    prev_output = out_dir / f"视频_{prev_label}.mp4"
                    prev_result = _submit_video_compat(
                        ctx=ctx, prompt=prev_full, images=list(image),
                        asset_ids=asset, ratio=ratio, duration=duration,
                        model=model, wait=True, output=prev_output,
                        run_name=f"chain-prev-{prev_label}", return_last_frame=True,
                    )
                    if prev_result and prev_result.last_frame_url:
                        last_frame_url = prev_result.last_frame_url
                        typer.echo(f"  {prev_label} 尾帧URL已获取")
                    else:
                        typer.echo(f"  警告：{prev_label} 未返回尾帧URL")

        typer.echo(f"将按顺序重新生成 {len(clip_nums)} 个 clip: {', '.join(f'Clip{c:03d}' for c in clip_nums)}")
        typer.echo(f"模式: {'尾帧衔接' if last_frame_url else '独立生成（无首帧约束）'}")

        for idx, cn in enumerate(clip_nums):
            clip_label = f"Clip{cn:03d}"
            prompt_file = prompt_dir / f"视频_{clip_label}.prompt.txt"
            clip_prompt = prompt_file.read_text(encoding="utf-8").strip()
            full_prompt = f"{prompt_header}{clip_prompt}" if prompt_header else clip_prompt
            clip_output = out_dir / f"视频_{clip_label}.mp4"

            typer.echo(f"\n{'='*50}")
            typer.echo(f"[{idx+1}/{len(clip_nums)}] 正在重新生成 {clip_label} ...")
            if last_frame_url:
                typer.echo(f"  首帧URL衔接模式（保证画面连续）")

            result = _submit_video_compat(
                ctx=ctx,
                prompt=full_prompt,
                images=list(image) if not last_frame_url else [],
                asset_ids=asset,
                ratio=ratio,
                duration=duration,
                model=model,
                wait=True,
                output=clip_output,
                run_name=f"chain-regen-{clip_label}",
                return_last_frame=True,
                first_frame_url=last_frame_url,
            )

            if result and result.last_frame_url:
                last_frame_url = result.last_frame_url
                typer.echo(f"  尾帧URL已缓存，将用于下一 clip 衔接")
            else:
                last_frame_url = None
                typer.echo(f"  警告：未获取到尾帧URL，下一 clip 将无首帧约束")

        typer.echo(f"\n{'='*50}")
        typer.echo(f"全部 {len(clip_nums)} 个 clip 重新生成完毕！")

        if concat:
            import re
            import subprocess

            abs_dir = out_dir.resolve()
            all_clips = sorted(
                [f for f in abs_dir.iterdir() if re.match(r"视频_Clip\d+\.mp4$", f.name)],
                key=lambda f: f.name,
            )
            if all_clips:
                c_output = (concat_output or (out_dir / "完整版_修复.mp4")).resolve()
                c_output.parent.mkdir(parents=True, exist_ok=True)
                filelist = abs_dir / "_chain_concat.txt"
                filelist.write_text("\n".join(f"file '{c.resolve()}'" for c in all_clips) + "\n")
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(filelist), "-c", "copy", str(c_output)],
                    capture_output=True, timeout=300,
                )
                filelist.unlink(missing_ok=True)
                typer.echo(f"已拼接: {c_output} ({len(all_clips)} 个 clip)")

    @app.command("clip-concat", help="将目录下所有 clip 按顺序拼接为完整视频，保留音视频轨道。")
    def clip_concat(
        ctx: typer.Context,
        input_dir: Path = typer.Option(..., "--input-dir", "-d", help="包含 视频_ClipXXX.mp4 的目录。"),
        output: Path = typer.Option(..., "--output", "-o", help="输出视频路径。"),
        trim_tail: float = typer.Option(0.0, "--trim-tail", help="裁掉每个 clip 尾部的秒数（可解决叙事泄漏）。"),
    ) -> None:
        import re
        import subprocess

        abs_dir = input_dir.resolve()
        clips = sorted(
            [f for f in abs_dir.iterdir() if re.match(r"视频_Clip\d+\.mp4$", f.name)],
            key=lambda f: f.name,
        )
        if not clips:
            typer.echo(f"错误：在 {input_dir} 中未找到 视频_ClipXXX.mp4 文件。", err=True)
            raise typer.Exit(1)

        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = output.parent / "_concat_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            sources: list[Path] = []
            for clip in clips:
                if trim_tail > 0:
                    probe = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
                        capture_output=True, text=True, timeout=10,
                    )
                    dur = float(probe.stdout.strip()) if probe.stdout.strip() else 15.0
                    end = max(dur - trim_tail, 1.0)
                    trimmed = tmp_dir / clip.name
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", str(clip), "-to", str(end), "-c", "copy", str(trimmed)],
                        capture_output=True, timeout=60,
                    )
                    sources.append(trimmed.resolve())
                    typer.echo(f"  {clip.name}: 裁剪尾部 {trim_tail}s → {end:.1f}s")
                else:
                    sources.append(clip.resolve())

            filelist = tmp_dir / "concat_list.txt"
            filelist.write_text("\n".join(f"file '{s}'" for s in sources) + "\n")
            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(filelist), "-c", "copy", str(output)],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                typer.echo(f"拼接失败: {result.stderr[-200:]}", err=True)
                raise typer.Exit(1)

            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(output)],
                capture_output=True, text=True, timeout=10,
            )
            dur_str = probe.stdout.strip()
            typer.echo(f"拼接完成: {output} ({len(clips)} 个 clip, {float(dur_str):.1f}s)")
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @app.command("clip-trim", help="裁剪单个 clip 的头部或尾部（保留音视频），用于去除叙事泄漏。")
    def clip_trim(
        ctx: typer.Context,
        input_file: Path = typer.Option(..., "--input", "-i", help="输入视频文件。"),
        output: Path = typer.Option(..., "--output", "-o", help="输出视频文件。"),
        trim_head: float = typer.Option(0.0, "--trim-head", help="裁掉头部秒数。"),
        trim_tail: float = typer.Option(0.0, "--trim-tail", help="裁掉尾部秒数。"),
    ) -> None:
        import subprocess

        input_file = input_file.resolve()
        if not input_file.exists():
            typer.echo(f"错误：文件不存在 {input_file}", err=True)
            raise typer.Exit(1)
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        cmd = ["ffmpeg", "-y", "-i", str(input_file)]
        if trim_head > 0:
            cmd.extend(["-ss", str(trim_head)])
        if trim_tail > 0:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(input_file)],
                capture_output=True, text=True, timeout=10,
            )
            dur = float(probe.stdout.strip()) if probe.stdout.strip() else 15.0
            end = max(dur - trim_tail, 1.0)
            cmd.extend(["-to", str(end - trim_head)])
        cmd.extend(["-c", "copy", str(output)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            typer.echo(f"裁剪失败: {result.stderr[-200:]}", err=True)
            raise typer.Exit(1)

        probe2 = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(output)],
            capture_output=True, text=True, timeout=10,
        )
        typer.echo(f"裁剪完成: {output} ({float(probe2.stdout.strip()):.1f}s)")

    @app.command("prompt-optimize", help="基于 Seedance 2.0 提示词指南优化视频提示词，提升生成质量、减少穿帮。")
    def prompt_optimize(
        ctx: typer.Context,
        input_file: Path = typer.Option(None, "--input", "-i", help="单个提示词文件路径（.prompt.txt）。"),
        input_dir: Path = typer.Option(None, "--dir", "-d", help="包含 视频_ClipXXX.prompt.txt 的目录，批量优化。"),
        output_dir: Path = typer.Option(None, "--output-dir", "-o", help="优化后输出目录（默认覆盖原文件）。"),
        prev_clip_prompt: Path = typer.Option(None, "--prev-prompt", help="前一 clip 的 prompt 文件，用于增强衔接描述。"),
        style: str = typer.Option("电影写实", "--style", help="视觉风格关键词（如：电影写实、赛博朋克、古风水墨）。"),
        quality_suffix: bool = typer.Option(True, "--quality/--no-quality", help="是否追加画质约束后缀。"),
        face_stable: bool = typer.Option(True, "--face-stable/--no-face-stable", help="是否追加面部稳定约束。"),
        check_only: bool = typer.Option(False, "--check", help="仅检查问题，不修改文件。"),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细优化信息。"),
    ) -> None:
        import re
        import textwrap

        if not input_file and not input_dir:
            typer.echo("错误：请通过 --input 指定单个文件或 --dir 指定目录。", err=True)
            raise typer.Exit(1)

        files: list[Path] = []
        if input_file:
            if not input_file.exists():
                typer.echo(f"错误：文件不存在 {input_file}", err=True)
                raise typer.Exit(1)
            files.append(input_file)
        elif input_dir:
            files = sorted(
                [f for f in input_dir.iterdir() if re.match(r"视频_Clip\d+\.prompt\.txt$", f.name)],
                key=lambda f: f.name,
            )
            if not files:
                typer.echo(f"错误：在 {input_dir} 中未找到 视频_ClipXXX.prompt.txt 文件。", err=True)
                raise typer.Exit(1)

        prev_prompt_text = ""
        if prev_clip_prompt and prev_clip_prompt.exists():
            prev_prompt_text = prev_clip_prompt.read_text(encoding="utf-8").strip()

        quality_block = "高清细节丰富，电影质感，色彩自然，光影柔和。"
        face_block = "面部稳定不变形，五官清晰，人体结构正常，动作自然流畅，不僵硬，画面无卡顿，无闪烁。"

        total_issues = 0
        total_fixed = 0

        for file_path in files:
            raw = file_path.read_text(encoding="utf-8").strip()
            issues: list[str] = []
            fixes: list[str] = []
            optimized = raw

            # --- Rule 1: Check for constraint blocks ---
            has_char_anchor = "【角色锚定】" in raw
            has_prop_lock = "【道具锁定】" in raw
            has_scene_lock = "【场景锁定】" in raw
            has_neg_constraint = "【否定约束】" in raw

            if not has_char_anchor:
                issues.append("[缺失] 无【角色锚定】块 — 角色外貌可能不一致")
            if not has_prop_lock:
                issues.append("[缺失] 无【道具锁定】块 — 道具可能随意变化")
            if not has_scene_lock:
                issues.append("[缺失] 无【场景锁定】块 — 场景可能不连贯")
            if not has_neg_constraint:
                issues.append("[缺失] 无【否定约束】块 — 易出错细节无防护")

            # --- Rule 2: Check for timeline structure ---
            has_timeline = bool(re.search(r"\d+[–\-]\d+\.?\d*\s*s", raw))
            if not has_timeline:
                issues.append("[结构] 无时间轴分镜 — 建议用 '0–5s:' 格式拆分动作")

            # --- Rule 3: Check for abstract emotion words ---
            abstract_words = ["很悲伤", "非常愤怒", "很高兴", "十分紧张", "很害怕", "震撼", "漂亮", "好看"]
            found_abstract = [w for w in abstract_words if w in raw]
            if found_abstract:
                issues.append(f"[抽象词] 发现模糊情绪词: {', '.join(found_abstract)} — 应替换为具体身体信号")

            # --- Rule 4: Check for multiple camera movements in one segment ---
            cam_words = ["推镜", "拉远", "横移", "摇移", "环绕", "俯拍", "仰拍", "跟拍", "手持"]
            segments = re.split(r"\d+[–\-]\d+\.?\d*\s*s\s*[:：]", raw)
            for seg_idx, seg in enumerate(segments[1:], 1):
                cam_count = sum(1 for w in cam_words if w in seg)
                if cam_count >= 3:
                    issues.append(f"[运镜] 第{seg_idx}段含{cam_count}种运镜 — 每段建议只用1种，减少画面抖动")

            # --- Rule 5: Check for violent action words ---
            violent_words = ["狂奔", "剧烈翻滚", "大跳", "高速旋转", "疯狂", "猛烈冲刺"]
            found_violent = [w for w in violent_words if w in raw]
            if found_violent:
                issues.append(f"[动作] 高强度动作词: {', '.join(found_violent)} — Seedance 偏好缓慢连续动作，可能生成抖动")

            # --- Rule 6: Check for scope boundary ---
            has_scope = "本段仅展示上述动作" in raw or "不展示后续剧情" in raw
            if not has_scope:
                issues.append("[范围] 无范围边界声明 — 可能导致叙事泄漏到下一 clip")

            # --- Rule 7: Check for tail markers ---
            has_no_bgm = "不要BGM" in raw or "不要bgm" in raw.lower()
            has_no_subtitle = "不要字幕" in raw
            if not has_no_bgm or not has_no_subtitle:
                issues.append("[尾标] 缺少 '不要BGM，不要字幕' 尾部约束")

            # --- Rule 8: Check for transition words between actions ---
            transition_phrases = ["借着", "顺势", "紧接着", "随后", "与此同时", "同时"]
            has_transitions = any(p in raw for p in transition_phrases)
            if not has_transitions and has_timeline:
                issues.append("[衔接] 动作间缺少过渡词 — 加入'顺势/借着惯性/紧接着'提升连贯性")

            # --- Rule 9: Check for ambiguous appearance descriptions ---
            ambiguous_hair = ["束冠短发", "短发束起", "发髻", "束发"]
            found_ambiguous_hair = [w for w in ambiguous_hair if w in raw]
            has_explicit_hat = any(w in raw for w in ["幞头", "官帽", "头盔", "斗笠", "头巾", "帽子", "头戴"])
            if found_ambiguous_hair and not has_explicit_hat:
                issues.append(f"[头饰] 发型描述模糊: {', '.join(found_ambiguous_hair)} — 易导致帽子时有时无穿帮，应明确写'头戴XX帽'或'无帽露发髻'")

            # --- Rule 10: Cross-clip consistency (batch mode) ---
            if input_dir and len(files) > 1:
                char_anchor = re.search(r"【角色锚定】(.+?)(?:\n|【)", raw, re.DOTALL)
                neg_constraint = re.search(r"【否定约束】(.+?)(?:\n|$)", raw, re.DOTALL)
                if char_anchor and neg_constraint:
                    anchor_text = char_anchor.group(1)
                    neg_text = neg_constraint.group(1)
                    if "帽" in anchor_text and "帽" not in neg_text:
                        issues.append("[一致性] 角色锚定提到帽子但否定约束未包含帽子约束 — 应加'全程戴帽不摘'")

            # --- Apply auto-fixes (only if not check-only) ---
            if not check_only:
                # Fix: Add quality suffix
                if quality_suffix and quality_block not in raw:
                    last_line = optimized.rstrip().split("\n")[-1]
                    if "不要BGM" in last_line or "不要字幕" in last_line:
                        optimized = optimized.rstrip()
                        insert_pos = optimized.rfind("不要BGM")
                        if insert_pos > 0:
                            before = optimized[:insert_pos].rstrip()
                            after = optimized[insert_pos:]
                            optimized = f"{before}\n{style}风格，{quality_block}\n{after}"
                            fixes.append("+ 追加画质约束")
                    else:
                        optimized = f"{optimized}\n{style}风格，{quality_block}"
                        fixes.append("+ 追加画质约束")

                # Fix: Add face stability
                if face_stable and face_block not in raw and "面部稳定" not in raw:
                    tail_match = re.search(r"不要BGM", optimized)
                    if tail_match:
                        pos = tail_match.start()
                        optimized = optimized[:pos] + face_block + "\n" + optimized[pos:]
                        fixes.append("+ 追加面部稳定约束")
                    else:
                        optimized = f"{optimized}\n{face_block}"
                        fixes.append("+ 追加面部稳定约束")

                # Fix: Add scope boundary if missing
                if not has_scope:
                    tail_match = re.search(r"不要BGM", optimized)
                    if tail_match:
                        pos = tail_match.start()
                        optimized = optimized[:pos] + "本段仅展示上述动作，不展示后续剧情。\n" + optimized[pos:]
                        fixes.append("+ 追加范围边界声明")
                    else:
                        optimized += "\n本段仅展示上述动作，不展示后续剧情。"
                        fixes.append("+ 追加范围边界声明")

                # Fix: Add tail markers if missing
                if not has_no_bgm or not has_no_subtitle:
                    if not optimized.rstrip().endswith("不要BGM，不要字幕"):
                        optimized = optimized.rstrip() + "\n不要BGM，不要字幕"
                        fixes.append("+ 追加尾部约束")

            total_issues += len(issues)
            total_fixed += len(fixes)

            # --- Output ---
            typer.echo(f"\n{'─'*50}")
            typer.echo(f"📄 {file_path.name}")

            if issues:
                typer.echo(f"  发现 {len(issues)} 个问题：")
                for issue in issues:
                    typer.echo(f"    {issue}")
            else:
                typer.echo("  ✓ 无问题")

            if fixes:
                typer.echo(f"  已修复 {len(fixes)} 项：")
                for fix in fixes:
                    typer.echo(f"    {fix}")

            if verbose and optimized != raw:
                typer.echo("  优化后预览（前200字符）：")
                typer.echo(textwrap.indent(optimized[:200] + "...", "    "))

            # Write optimized file
            if not check_only and optimized != raw:
                if output_dir:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    out_path = output_dir / file_path.name
                else:
                    out_path = file_path
                out_path.write_text(optimized, encoding="utf-8")
                typer.echo(f"  已保存: {out_path}")

        typer.echo(f"\n{'═'*50}")
        typer.echo(f"汇总: {len(files)} 个文件, {total_issues} 个问题, {total_fixed} 项已修复")
        if check_only:
            typer.echo("（仅检查模式，未修改文件）")

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
        typer.echo("【示例9：穿帮修复 — 重新生成单个 clip】")
        typer.echo("# 修改 prompt 后用 Seedance 重新生成第4个 clip（穿帮的正确修复方式）")
        typer.echo("changdu clip-regen \\")
        typer.echo("  --clip 4 --prompt-dir ./单集制作/EP001/ \\")
        typer.echo("  --asset <角色ID> --asset <场景ID> \\")
        typer.echo("  --prompt-header '图片1是男主面部，图片2是场景。' \\")
        typer.echo("  --ratio 16:9 --duration 15")
        typer.echo("")
        typer.echo("【示例10：拼接全部 clip 为完整视频（保留音频）】")
        typer.echo("changdu clip-concat \\")
        typer.echo("  --input-dir ./单集制作/EP001/ \\")
        typer.echo("  --output ./单集制作/EP001/完整版.mp4")
        typer.echo("")
        typer.echo("【示例11：拼接 + 裁掉每个 clip 尾部（去叙事泄漏）】")
        typer.echo("changdu clip-concat \\")
        typer.echo("  --input-dir ./单集制作/EP001/ \\")
        typer.echo("  --output ./单集制作/EP001/完整版.mp4 \\")
        typer.echo("  --trim-tail 1.0")
        typer.echo("")
        typer.echo("【示例12：裁剪单个 clip（去头尾叙事泄漏）】")
        typer.echo("changdu clip-trim \\")
        typer.echo("  --input 视频_Clip003.mp4 \\")
        typer.echo("  --output 视频_Clip003_trimmed.mp4 \\")
        typer.echo("  --trim-tail 2.0")
        typer.echo("")
        typer.echo("【示例13：提示词优化（批量检查）】")
        typer.echo("changdu prompt-optimize --dir ./单集制作/EP003/ --check")
        typer.echo("")
        typer.echo("【示例14：提示词优化（自动修复）】")
        typer.echo("changdu prompt-optimize --dir ./单集制作/EP003/ --style '古风电影写实' --verbose")


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

    last_frame_path: Path | None = None
    if result.last_frame_url and output:
        last_frame_path = output.with_suffix(".lastframe.jpg")
        try:
            download_binary(result.last_frame_url, last_frame_path)
        except Exception:
            last_frame_path = None

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
    if last_frame_path:
        out_payload["last_frame_path"] = str(last_frame_path)
        pretty.append(f"尾帧已保存: {last_frame_path}")
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
