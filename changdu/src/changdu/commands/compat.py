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


# ── Media reference resolution ─────────────────────────────────────────────
# Reference videos and audios cannot be inlined as data URLs (size & API
# restrictions), so local files are uploaded to TOS first. Asset IDs are
# converted to `asset://...` URIs. Plain URLs are passed through.
def _resolve_media_ref(value: str | Path, *, kind: str) -> str:
    """Normalise a video/audio reference into an URL the Ark API can fetch.

    Accepts:
    - A local file path → uploaded to TOS, returns the public URL.
    - An `asset-...` ID or `asset://...` URI → returned as `asset://<id>`.
    - An `http(s)://` URL → returned as-is.
    """

    text = str(value).strip()
    if not text:
        raise typer.BadParameter(f"empty {kind} reference")

    if text.startswith("asset://"):
        return text
    if text.startswith("asset-"):
        return f"asset://{text}"
    if text.startswith("http://") or text.startswith("https://"):
        return text

    path = Path(text)
    if not path.exists():
        raise typer.BadParameter(f"{kind} reference not found locally and not a URL/asset id: {text}")

    return _upload_to_tos(path, kind=kind)


def _upload_to_tos(path: Path, *, kind: str) -> str:
    import os

    from changdu.client.tos_upload import upload_file

    ak = os.getenv("VOLC_ACCESSKEY") or os.getenv("CHANGDU_TOS_AK")
    sk = os.getenv("VOLC_SECRETKEY") or os.getenv("CHANGDU_TOS_SK")
    bucket = os.getenv("CHANGDU_TOS_BUCKET")
    endpoint = os.getenv("CHANGDU_TOS_ENDPOINT", "tos-cn-beijing.volces.com")
    region = os.getenv("CHANGDU_TOS_REGION", "cn-beijing")
    if not ak or not sk or not bucket:
        raise typer.BadParameter(
            f"传入本地{kind}文件需要配置 TOS：VOLC_ACCESSKEY / VOLC_SECRETKEY / CHANGDU_TOS_BUCKET"
        )
    typer.echo(f"  正在上传 {kind}: {path.name} → TOS ...")
    result = upload_file(
        file_path=path,
        bucket=bucket,
        key=f"refs/{kind}/{path.name}",
        ak=ak,
        sk=sk,
        endpoint=endpoint,
        region=region,
        public=True,
    )
    typer.echo(f"  TOS URL: {result.url}")
    return result.url


def _extract_tail_segment(video_path: Path, output_path: Path, tail_seconds: float = 5.0) -> Path:
    """Extract the trailing N seconds of a video (audio + video copy).

    Used to feed the previous clip's tail into the next clip as a
    `reference_video` to lock visual continuity.
    """

    import subprocess

    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    try:
        duration = float(probe.stdout.strip()) if probe.stdout.strip() else 15.0
    except ValueError:
        duration = 15.0

    tail_seconds = max(2.0, min(tail_seconds, 15.0, duration))
    start = max(0.0, duration - tail_seconds)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.2f}",
        "-i", str(video_path),
        "-t", f"{tail_seconds:.2f}",
        "-c", "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ffmpeg tail extract failed: {result.stderr[-300:]}")
    return output_path


def _extract_voice_audio(
    video_path: Path,
    output_path: Path,
    *,
    start: float = 0.0,
    duration: float = 8.0,
    fmt: str = "mp3",
) -> Path:
    """Extract a short audio clip from a video, suitable for use as a
    Seedance `reference_audio` voice anchor.

    Auto-clamps ``start`` and ``duration`` to fit within the actual video
    length so that callers asking for e.g. 6s+8s on a 5s clip still get a
    valid extract instead of a near-empty file rejected by ARK.
    """

    import subprocess

    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")

    video_duration = _probe_duration(video_path, default=15.0)
    if video_duration <= 1.5:
        raise RuntimeError(
            f"video duration {video_duration:.2f}s too short to extract a voice "
            "anchor (need >= 1.8s)."
        )

    if start >= video_duration - 1.5:
        new_start = max(0.0, video_duration - max(2.0, duration) - 0.2)
        start = new_start
    available = max(1.8, video_duration - start - 0.05)
    duration = max(1.8, min(duration, available, 15.0))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt.lower() == "wav":
        codec_args = ["-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2"]
    else:
        codec_args = ["-vn", "-acodec", "libmp3lame", "-q:a", "2", "-ac", "2"]

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.2f}",
        "-i", str(video_path),
        "-t", f"{duration:.2f}",
        *codec_args,
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg voice extract failed: {result.stderr[-300:]}")
    return output_path


def _probe_duration(path: Path, default: float = 5.0) -> float:
    """Probe a media file's duration in seconds via ffprobe; returns ``default`` on error."""

    import subprocess

    if not path.exists():
        return default
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    raw = probe.stdout.strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _build_concat_filter_complex(
    durations: list[float],
    *,
    crossfade: float = 0.0,
    normalize_audio: bool = False,
) -> tuple[str, str, str, float]:
    """Compose a ``filter_complex`` for the ``clip-concat`` pipeline.

    Pipeline (per option):

    - ``crossfade>0`` : pairwise ``xfade`` (video) + ``acrossfade`` (audio)
    - ``crossfade==0`` : ``concat`` filter (no transition) — only used when
      another option (loudnorm) forces re-encode anyway
    - ``normalize_audio`` : append ``loudnorm=I=-16:LRA=11:TP=-1.5``

    Returns ``(filter_complex, video_label, audio_label, total_duration)``.
    """

    if not durations:
        raise ValueError("durations must contain at least one clip duration")

    n = len(durations)
    chains: list[str] = []

    if n == 1:
        v_label = "[0:v]"
        a_label = "[0:a]"
        total = durations[0]
    elif crossfade > 0:
        offset = 0.0
        prev_v = "[0:v]"
        prev_a = "[0:a]"
        for i in range(1, n):
            offset += durations[i - 1] - crossfade
            v_next = f"[v{i:02d}]"
            a_next = f"[a{i:02d}]"
            chains.append(
                f"{prev_v}[{i}:v]xfade=transition=fade:duration={crossfade:.3f}:"
                f"offset={offset:.3f}{v_next}"
            )
            chains.append(
                f"{prev_a}[{i}:a]acrossfade=d={crossfade:.3f}:c1=tri:c2=tri{a_next}"
            )
            prev_v = v_next
            prev_a = a_next
        v_label = prev_v
        a_label = prev_a
        total = sum(durations) - (n - 1) * crossfade
    else:
        v_inputs = "".join(f"[{i}:v]" for i in range(n))
        a_inputs = "".join(f"[{i}:a]" for i in range(n))
        chains.append(f"{v_inputs}{a_inputs}concat=n={n}:v=1:a=1[vcat][acat]")
        v_label = "[vcat]"
        a_label = "[acat]"
        total = sum(durations)

    if normalize_audio:
        chains.append(f"{a_label}loudnorm=I=-16:LRA=11:TP=-1.5[anorm]")
        a_label = "[anorm]"

    return ";".join(chains), v_label, a_label, total


def _run_concat_with_filters(
    sources: list[Path],
    output: Path,
    *,
    crossfade: float,
    normalize_audio: bool,
    timeout_s: int = 600,
) -> tuple[float, str]:
    """Run the concat pipeline (re-encode) and return ``(out_duration, ffmpeg_cmd)``."""

    import subprocess

    durations = [_probe_duration(s) for s in sources]
    fc, vout, aout, _total = _build_concat_filter_complex(
        durations,
        crossfade=crossfade,
        normalize_audio=normalize_audio,
    )

    cmd: list[str] = ["ffmpeg", "-y"]
    for src in sources:
        cmd.extend(["-i", str(src)])
    cmd.extend([
        "-filter_complex", fc,
        "-map", vout,
        "-map", aout,
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output),
    ])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if result.returncode != 0 or not output.exists():
        raise RuntimeError(f"ffmpeg concat (filter_complex) failed: {result.stderr[-400:]}")
    return _probe_duration(output), " ".join(cmd)


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
        last_frame_url: str | None = typer.Option(None, "--last-frame-url", help="指定尾帧图片URL（首尾帧驱动模式）。"),
        ref_video: list[str] = typer.Option([], "--ref-video", help="参考视频（本地路径/URL/asset ID），最多 3 个。"),
        ref_audio: list[str] = typer.Option([], "--ref-audio", help="参考音频（本地路径/URL/asset ID），最多 3 段。"),
        no_audio: bool = typer.Option(False, "--no-audio", help="禁用同步音频生成。"),
        quality: str | None = typer.Option(None, "--quality", help="视频分辨率：480p/720p/1080p（默认随端点）。"),
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
            last_frame_url=last_frame_url,
            ref_videos=ref_video,
            ref_audios=ref_audio,
            generate_audio=not no_audio,
            quality=quality,
        )

    @app.command("multimodal2video", help="多模态参考生成视频（图片 + 视频 + 音频，支持 Asset 素材引用）。")
    def multimodal2video(
        ctx: typer.Context,
        image: list[Path] = typer.Option([], "--image", help="参考图，可重复传入。"),
        asset: list[str] = typer.Option([], "--asset", help="Asset 素材ID（图片/视频/音频通用），自动转 asset:// 引用。"),
        prompt: str = typer.Option("", "--prompt", help="提示词。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(5, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        wait: bool = typer.Option(False, "--wait", help="是否等待任务完成。"),
        output: Path | None = typer.Option(None, "--output", help="等待完成时的视频保存路径。"),
        return_last_frame: bool = typer.Option(False, "--return-last-frame", help="返回生成视频的尾帧URL（用于连续生成）。"),
        first_frame_url: str | None = typer.Option(None, "--first-frame-url", help="指定首帧图片URL（来自上一 clip 的尾帧）。"),
        last_frame_url: str | None = typer.Option(None, "--last-frame-url", help="指定尾帧图片URL（首尾帧驱动）。"),
        ref_video: list[str] = typer.Option([], "--ref-video", help="参考视频（本地路径/URL/asset ID），最多 3 个，用于动作/运镜/外观连贯参考。"),
        ref_audio: list[str] = typer.Option([], "--ref-audio", help="参考音频（本地路径/URL/asset ID），最多 3 段，用于音色/台词锁定。"),
        no_audio: bool = typer.Option(False, "--no-audio", help="禁用同步音频生成。"),
        quality: str | None = typer.Option(None, "--quality", help="视频分辨率：480p/720p/1080p。"),
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
            last_frame_url=last_frame_url,
            ref_videos=ref_video,
            ref_audios=ref_audio,
            generate_audio=not no_audio,
            quality=quality,
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
        last_frame_url: str | None = typer.Option(None, "--last-frame-url", help="指定尾帧图片URL（首尾帧驱动）。"),
        ref_video: list[str] = typer.Option([], "--ref-video", help="参考视频（本地路径/URL/asset ID）。"),
        ref_audio: list[str] = typer.Option([], "--ref-audio", help="参考音频（本地路径/URL/asset ID）。"),
        no_audio: bool = typer.Option(False, "--no-audio", help="禁用同步音频生成。"),
        quality: str | None = typer.Option(None, "--quality", help="视频分辨率：480p/720p/1080p。"),
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
            last_frame_url=last_frame_url,
            ref_videos=ref_video,
            ref_audios=ref_audio,
            generate_audio=not no_audio,
            quality=quality,
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
        last_frame_url: str | None = typer.Option(None, "--last-frame-url", help="指定尾帧图片URL（首尾帧驱动）。"),
        ref_video: list[str] = typer.Option([], "--ref-video", help="参考视频（本地路径/URL/asset ID）。"),
        ref_audio: list[str] = typer.Option([], "--ref-audio", help="参考音频（本地路径/URL/asset ID）。"),
        no_audio: bool = typer.Option(False, "--no-audio", help="禁用同步音频生成。"),
        quality: str | None = typer.Option(None, "--quality", help="视频分辨率：480p/720p/1080p。"),
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
            last_frame_url=last_frame_url,
            ref_videos=ref_video,
            ref_audios=ref_audio,
            generate_audio=not no_audio,
            quality=quality,
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

    @app.command("sequential-generate", help="按顺序生成多个视频片段，默认用前一 clip 的尾段做 reference_video + 可选音色锁定，保证人物/场景/音色的连贯。")
    def sequential_generate(
        ctx: typer.Context,
        prompt_dir: Path = typer.Option(..., "--prompt-dir", help="包含 视频_ClipXXX.prompt.txt 的目录。"),
        image: list[Path] = typer.Option([], "--image", help="参考图（每个 clip 共享），可重复传入。"),
        asset: list[str] = typer.Option([], "--asset", help="Asset 素材ID（每个 clip 共享），可重复传入。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(15, "--duration", help="每个 clip 的时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        output_dir: Path = typer.Option(None, "--output-dir", help="视频输出目录（默认同 prompt-dir）。"),
        prompt_header: str = typer.Option("", "--prompt-header", help="每个 clip 提示词前缀（如角色/场景说明）。"),
        continuity_mode: str = typer.Option(
            "ref_video",
            "--continuity-mode",
            help=(
                "衔接模式：first_frame（前段尾帧做首帧）/ ref_video（前段尾段做参考视频，推荐）/ "
                "auto（先 ref_video，被 ARK 拒绝时自动降级到 first_frame）。"
                "API 不允许同一请求同时塞 first_frame 和 reference_video。"
                "（旧值 both 等价于 auto，已保留兼容。）"
            ),
        ),
        prev_tail_seconds: float = typer.Option(5.0, "--prev-tail-seconds", help="ref_video 模式下从前一 clip 抽取的尾段时长（秒）。"),
        extract_keyframes: bool = typer.Option(False, "--extract-keyframes/--no-keyframes", help="兼容旧行为：从前一 clip 抽中/尾帧作为额外参考图。"),
        voice_asset: str | None = typer.Option(None, "--voice-asset", help="音色样本 asset ID（如 asset-xxxx），每个 clip 都会附加做 reference_audio。"),
        voice_from_clip: int | None = typer.Option(
            None,
            "--voice-from-clip",
            help="第 N 个 clip 完成后自动提取主角音色（默认提取第 6-12 秒），上传入库后从 N+1 起所有后续 clip 自动锁音色。",
        ),
        voice_group_id: str | None = typer.Option(None, "--voice-group-id", help="--voice-from-clip 自动入库时使用的素材组ID（必填条件）。"),
        voice_clip_start: float = typer.Option(6.0, "--voice-clip-start", help="--voice-from-clip 提取音色的起始时间（秒）。"),
        voice_clip_duration: float = typer.Option(8.0, "--voice-clip-duration", help="--voice-from-clip 提取音色的时长（秒，2-15）。"),
        ref_video_extra: list[str] = typer.Option([], "--ref-video", help="额外参考视频（每个 clip 共享），最多 3。"),
        ref_audio_extra: list[str] = typer.Option([], "--ref-audio", help="额外参考音频（每个 clip 共享），最多 3。"),
        no_audio: bool = typer.Option(False, "--no-audio", help="禁用同步音频生成。"),
        quality: str | None = typer.Option(None, "--quality", help="视频分辨率：480p/720p/1080p。"),
    ) -> None:
        import re
        from changdu.utils import extract_keyframes as _extract_kf

        obj: AppContext = ctx.obj
        out_dir = output_dir or prompt_dir

        if continuity_mode not in {"first_frame", "ref_video", "both", "auto"}:
            typer.echo("错误：--continuity-mode 必须是 first_frame / ref_video / auto 之一。", err=True)
            raise typer.Exit(1)
        if continuity_mode == "both":
            continuity_mode = "auto"

        if voice_from_clip and not voice_group_id:
            typer.echo("错误：--voice-from-clip 需要同时传入 --voice-group-id。", err=True)
            raise typer.Exit(1)

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

        typer.echo(
            f"共发现 {len(prompt_files)} 个 clip 待生成；continuity={continuity_mode}, "
            f"voice_asset={'有' if voice_asset else ('待提取' if voice_from_clip else '无')}"
        )

        shared_audios_base: list[str] = list(ref_audio_extra)
        if voice_asset:
            shared_audios_base.append(voice_asset)

        last_frame_url: str | None = None
        last_video_path: Path | None = None
        prev_label: str = ""
        active_voice_asset: str | None = voice_asset

        for idx, pf in enumerate(prompt_files):
            clip_num = re.search(r"Clip(\d+)", pf.name)
            clip_label = clip_num.group(0) if clip_num else f"Clip{idx+1:03d}"
            clip_index = int(clip_num.group(1)) if clip_num else (idx + 1)
            clip_prompt = pf.read_text(encoding="utf-8").strip()
            full_prompt = f"{prompt_header}\n\n{clip_prompt}" if prompt_header else clip_prompt
            clip_output = out_dir / f"视频_{clip_label}.mp4"

            if clip_output.exists() and idx < already_done:
                typer.echo(f"\n{'='*50}")
                typer.echo(f"[{idx+1}/{len(prompt_files)}] {clip_label} 已存在，跳过生成（仍补做 voice/last_frame 提取）")
                prev_label = clip_label
                last_video_path = clip_output
                last_frame_url = None

                lf_path = clip_output.with_suffix(".lastframe.jpg")
                if not lf_path.exists():
                    try:
                        import subprocess
                        subprocess.run(
                            [
                                "ffmpeg", "-y", "-sseof", "-0.05", "-i", str(clip_output),
                                "-frames:v", "1", "-q:v", "2", str(lf_path),
                            ],
                            capture_output=True, text=True, timeout=60,
                        )
                    except Exception as exc:
                        typer.echo(f"  警告：补抽 lastframe 失败：{exc}", err=True)
                if lf_path.exists():
                    try:
                        last_frame_url = _upload_to_tos(lf_path, kind="image")
                        typer.echo(f"  已上传 lastframe 用于后续 fallback：{last_frame_url}")
                    except Exception as exc:
                        typer.echo(f"  警告：lastframe 上传 TOS 失败（fallback 不可用）：{exc}", err=True)

                if (
                    voice_from_clip is not None
                    and clip_index == voice_from_clip
                    and not active_voice_asset
                ):
                    typer.echo(
                        f"  正在从已存在的 {clip_label} 提取主角音色样本"
                        f"（{voice_clip_start:.1f}s 起 {voice_clip_duration:.1f}s）..."
                    )
                    fmt_urls: dict[str, str] = {}
                    for fmt in ("wav", "mp3"):
                        voice_path = out_dir / "_voices" / f"voice_from_{clip_label}.{fmt}"
                        try:
                            _extract_voice_audio(
                                clip_output, voice_path,
                                start=voice_clip_start, duration=voice_clip_duration, fmt=fmt,
                            )
                            fmt_urls[fmt] = _upload_to_tos(voice_path, kind="audio")
                        except Exception as exc:
                            typer.echo(f"  警告：音色抽取/上传失败（fmt={fmt}）：{exc}", err=True)
                            continue
                        try:
                            assets_client = _build_assets_client()
                            asset_obj = assets_client.create_asset(
                                group_id=voice_group_id, url=fmt_urls[fmt],
                                asset_type="Audio", name=f"voice-from-{clip_label}",
                            )
                            asset_obj = assets_client.wait_for_active(asset_obj.id)
                            typer.echo(
                                f"  音色已入库（{fmt}）: {asset_obj.id}（仅记录，"
                                "实际 reference_audio 走 wav TOS URL 直链）"
                            )
                        except Exception as exc:
                            typer.echo(f"  说明：asset 入库失败（fmt={fmt}）：{exc}（不影响后续）", err=True)
                    if "wav" in fmt_urls:
                        active_voice_asset = fmt_urls["wav"]
                        typer.echo(f"  使用 wav TOS URL 作为 reference_audio：{active_voice_asset}")
                    elif "mp3" in fmt_urls:
                        active_voice_asset = fmt_urls["mp3"]
                        typer.echo(
                            f"  仅有 mp3 TOS URL：{active_voice_asset}（兼容性差，可能被拒）",
                            err=True,
                        )
                continue

            typer.echo(f"\n{'='*50}")
            typer.echo(f"[{idx+1}/{len(prompt_files)}] 正在生成 {clip_label} ...")

            ff_url: str | None = None
            videos_for_this: list[str] = list(ref_video_extra)
            extra_ref_images: list[Path] = []
            tail_for_fallback: Path | None = None

            if idx > 0 and continuity_mode == "first_frame" and last_frame_url:
                ff_url = last_frame_url
                typer.echo("  首帧URL衔接（first_frame）")

            if (
                idx > 0
                and continuity_mode in {"ref_video", "auto"}
                and last_video_path
                and last_video_path.exists()
            ):
                tail_dir = out_dir / "_tails"
                tail_path = tail_dir / f"{last_video_path.stem}_tail.mp4"
                try:
                    _extract_tail_segment(last_video_path, tail_path, tail_seconds=prev_tail_seconds)
                    videos_for_this.append(str(tail_path))
                    tail_for_fallback = tail_path
                    typer.echo(
                        f"  ref_video 衔接：{last_video_path.name} → 尾段 {prev_tail_seconds:.1f}s"
                    )
                except Exception as exc:
                    typer.echo(f"  警告：尾段抽取失败：{exc}", err=True)

            if (
                idx > 0
                and extract_keyframes
                and continuity_mode == "first_frame"
                and not asset
                and not last_frame_url
            ):
                prev_clip_path = out_dir / f"视频_{prev_label}.mp4"
                if prev_clip_path.exists():
                    typer.echo(f"  兼容旧逻辑：从 {prev_label} 抽取关键帧 ...")
                    kf_dir = out_dir / "keyframes"
                    extra_ref_images = _extract_kf(prev_clip_path, kf_dir)
                    typer.echo(f"  抽取到 {len(extra_ref_images)} 帧参考图")

            audios_for_this: list[str] = list(shared_audios_base)
            if active_voice_asset and active_voice_asset not in audios_for_this:
                audios_for_this.append(active_voice_asset)

            all_images = list(image) + extra_ref_images

            has_frame_anchor = bool(ff_url)
            has_ref_media = bool(all_images or asset or videos_for_this or audios_for_this)
            if has_frame_anchor and has_ref_media:
                typer.echo(
                    f"  注意：first_frame_url 与参考媒体互斥，"
                    "优先使用 first_frame_url 衔接，清空本次参考媒体（音色由 prompt 文本锚定）"
                )
                all_images = []
                videos_for_this = []
                audios_for_this = []
                asset_ids_for_this: list[str] = []
            else:
                asset_ids_for_this = list(asset)

            try:
                result = _submit_video_compat(
                    ctx=ctx,
                    prompt=full_prompt,
                    images=all_images,
                    asset_ids=asset_ids_for_this,
                    ratio=ratio,
                    duration=duration,
                    model=model,
                    wait=True,
                    output=clip_output,
                    run_name=f"sequential-{clip_label}",
                    return_last_frame=True,
                    first_frame_url=ff_url,
                    ref_videos=videos_for_this,
                    ref_audios=audios_for_this,
                    generate_audio=not no_audio,
                    quality=quality,
                )
            except Exception as exc:
                msg = str(exc)
                fallback_triggers = (
                    "may contain real person",
                    "first/last frame content cannot be mixed",
                    "Sensitive",
                    "InvalidParameter",
                    "FormatUnsupported",
                    "audio probe err",
                    "is not found",
                    "is not valid",
                )
                can_fallback = (
                    continuity_mode == "auto"
                    and idx > 0
                    and last_frame_url
                    and any(t in msg for t in fallback_triggers)
                )
                if not can_fallback:
                    raise
                typer.echo(
                    f"  警告：提交被拒（{msg.splitlines()[0][:140]}），"
                    "降级为 first_frame_url 模式重试（清空所有参考媒体，音色由 prompt 锚定）..."
                )
                result = _submit_video_compat(
                    ctx=ctx,
                    prompt=full_prompt,
                    images=[],
                    asset_ids=[],
                    ratio=ratio,
                    duration=duration,
                    model=model,
                    wait=True,
                    output=clip_output,
                    run_name=f"sequential-{clip_label}-fallback",
                    return_last_frame=True,
                    first_frame_url=last_frame_url,
                    ref_videos=[],
                    ref_audios=[],
                    generate_audio=not no_audio,
                    quality=quality,
                )

            if result and result.last_frame_url:
                last_frame_url = result.last_frame_url
                typer.echo(f"  尾帧URL已缓存，将用于 {clip_label} → 下一 clip 衔接")
            else:
                last_frame_url = None
            if clip_output.exists():
                last_video_path = clip_output

            if (
                voice_from_clip is not None
                and clip_index == voice_from_clip
                and not active_voice_asset
                and last_video_path
                and last_video_path.exists()
            ):
                typer.echo(
                    f"  正在从 {clip_label} 提取主角音色样本（{voice_clip_start:.1f}s 起 {voice_clip_duration:.1f}s）..."
                )
                fmt_urls: dict[str, str] = {}
                asset_id_logged: str | None = None
                for fmt in ("wav", "mp3"):
                    voice_path = out_dir / "_voices" / f"voice_from_{clip_label}.{fmt}"
                    try:
                        _extract_voice_audio(
                            last_video_path,
                            voice_path,
                            start=voice_clip_start,
                            duration=voice_clip_duration,
                            fmt=fmt,
                        )
                        fmt_urls[fmt] = _upload_to_tos(voice_path, kind="audio")
                    except Exception as exc:
                        typer.echo(f"  警告：音色抽取/上传失败（fmt={fmt}）：{exc}", err=True)
                        continue
                    try:
                        assets_client = _build_assets_client()
                        asset_obj = assets_client.create_asset(
                            group_id=voice_group_id,
                            url=fmt_urls[fmt],
                            asset_type="Audio",
                            name=f"voice-from-{clip_label}",
                        )
                        asset_obj = assets_client.wait_for_active(asset_obj.id)
                        asset_id_logged = asset_obj.id
                        typer.echo(
                            f"  音色已入库（{fmt}）: {asset_obj.id} → {asset_obj.asset_url}（仅记录，"
                            "实际 reference_audio 走 wav TOS URL 直链）"
                        )
                    except Exception as exc:
                        typer.echo(f"  说明：asset 入库失败（fmt={fmt}）：{exc}（不影响后续，wav TOS URL 直接做 reference_audio）", err=True)
                if "wav" in fmt_urls:
                    active_voice_asset = fmt_urls["wav"]
                    typer.echo(f"  使用 wav TOS URL 作为 reference_audio：{active_voice_asset}")
                elif "mp3" in fmt_urls:
                    active_voice_asset = fmt_urls["mp3"]
                    typer.echo(
                        f"  仅有 mp3 TOS URL：{active_voice_asset}（Seedance 对 mp3 audio_url 兼容性差，可能被拒）",
                        err=True,
                    )

            prev_label = clip_label

        typer.echo(f"\n{'='*50}")
        typer.echo(f"全部 {len(prompt_files)} 个 clip 生成完毕！输出目录: {out_dir}")
        if active_voice_asset:
            typer.echo(f"使用的音色 asset: {active_voice_asset}")

    @app.command("clip-regen", help="重新生成单个 clip，可指定前一 clip 提供视觉上下文（推荐使用 --prev-clip 抽尾段做 ref_video）。")
    def clip_regen(
        ctx: typer.Context,
        clip: int = typer.Option(..., "--clip", help="要重新生成的 clip 编号（如 4）。"),
        prompt_dir: Path = typer.Option(..., "--prompt-dir", help="包含 视频_ClipXXX.prompt.txt 的目录。"),
        image: list[Path] = typer.Option([], "--image", help="参考图，可重复传入。"),
        asset: list[str] = typer.Option([], "--asset", help="Asset 素材ID，可重复传入。"),
        prev_clip: Path | None = typer.Option(None, "--prev-clip", help="前一 clip 的视频文件，自动抽尾段（默认 5s）作为 reference_video。"),
        prev_tail_seconds: float = typer.Option(5.0, "--prev-tail-seconds", help="从 --prev-clip 抽取的尾段时长（秒）。"),
        first_frame_url: str | None = typer.Option(None, "--first-frame-url", help="首帧图片URL，保证画面连续。"),
        last_frame_url: str | None = typer.Option(None, "--last-frame-url", help="尾帧图片URL（首尾帧驱动）。"),
        ref_video: list[str] = typer.Option([], "--ref-video", help="额外参考视频（本地路径/URL/asset ID）。"),
        ref_audio: list[str] = typer.Option([], "--ref-audio", help="参考音频（本地路径/URL/asset ID），用于音色锁定。"),
        voice_asset: str | None = typer.Option(None, "--voice-asset", help="音色样本 asset ID（等价于 --ref-audio asset://<id>）。"),
        no_audio: bool = typer.Option(False, "--no-audio", help="禁用同步音频生成。"),
        quality: str | None = typer.Option(None, "--quality", help="视频分辨率：480p/720p/1080p。"),
        ratio: str = typer.Option("16:9", "--ratio", help="视频比例。"),
        duration: int = typer.Option(15, "--duration", help="时长（秒）。"),
        model: str | None = typer.Option(None, "--model", help="覆盖视频模型/端点 ID。"),
        prompt_header: str = typer.Option("", "--prompt-header", help="提示词前缀。"),
        output: Path | None = typer.Option(None, "--output", help="输出路径（默认覆盖原文件）。"),
    ) -> None:
        clip_label = f"Clip{clip:03d}"
        prompt_file = prompt_dir / f"视频_{clip_label}.prompt.txt"
        if not prompt_file.exists():
            typer.echo(f"错误：未找到 {prompt_file}", err=True)
            raise typer.Exit(1)

        clip_prompt = prompt_file.read_text(encoding="utf-8").strip()
        full_prompt = f"{prompt_header}\n\n{clip_prompt}" if prompt_header else clip_prompt
        clip_output = output or (prompt_dir / f"视频_{clip_label}.mp4")

        typer.echo(f"正在重新生成 {clip_label} ...")

        videos_to_use: list[str] = list(ref_video)
        if prev_clip and prev_clip.exists():
            tail_dir = prompt_dir / "_tails"
            tail_path = tail_dir / f"{prev_clip.stem}_tail.mp4"
            try:
                _extract_tail_segment(prev_clip, tail_path, tail_seconds=prev_tail_seconds)
                typer.echo(f"  已抽取 {prev_clip.name} 尾段 {prev_tail_seconds:.1f}s → {tail_path.name}")
                videos_to_use.append(str(tail_path))
            except Exception as exc:
                typer.echo(f"  警告：尾段抽取失败：{exc}", err=True)

        audios_to_use: list[str] = list(ref_audio)
        if voice_asset:
            audios_to_use.append(voice_asset)

        if first_frame_url:
            typer.echo("  首帧URL衔接（first_frame）")
        if last_frame_url:
            typer.echo("  尾帧URL固定（last_frame）")

        result = _submit_video_compat(
            ctx=ctx,
            prompt=full_prompt,
            images=list(image),
            asset_ids=asset,
            ratio=ratio,
            duration=duration,
            model=model,
            wait=True,
            output=clip_output,
            run_name=f"clip-regen-{clip_label}",
            return_last_frame=True,
            first_frame_url=first_frame_url,
            last_frame_url=last_frame_url,
            ref_videos=videos_to_use,
            ref_audios=audios_to_use,
            generate_audio=not no_audio,
            quality=quality,
        )

        if result and result.last_frame_url:
            typer.echo(f"  新尾帧URL: {result.last_frame_url}")
        typer.echo(f"{clip_label} 重新生成完毕: {clip_output}")

    @app.command("clip-chain-regen", help="连续重新生成多个 clip，默认用前一 clip 尾段作为 reference_video 衔接（穿帮修复利器）。")
    def clip_chain_regen(
        ctx: typer.Context,
        clips: str = typer.Option(..., "--clips", help="要重新生成的 clip 编号列表，逗号分隔（如 2,3,4）。"),
        prompt_dir: Path = typer.Option(..., "--prompt-dir", help="包含 视频_ClipXXX.prompt.txt 的目录。"),
        image: list[Path] = typer.Option([], "--image", help="参考图（每个 clip 共享），可重复传入。"),
        asset: list[str] = typer.Option([], "--asset", help="Asset 素材ID（每个 clip 共享），可重复传入。"),
        start_frame_url: str | None = typer.Option(None, "--start-frame-url", help="链条起始首帧URL（来自前一 clip 的 last_frame_url）。"),
        regen_prev: bool = typer.Option(False, "--regen-prev", help="先重新生成 clips 列表前一个 clip 以获取 last_frame_url 作为起点。"),
        continuity_mode: str = typer.Option(
            "ref_video",
            "--continuity-mode",
            help=(
                "衔接模式：first_frame / ref_video（默认，更强一致性）/ "
                "auto（先 ref_video，被 ARK 拒绝时自动降级到 first_frame）。"
                "（旧值 both 等价于 auto，已保留兼容。）"
            ),
        ),
        prev_tail_seconds: float = typer.Option(5.0, "--prev-tail-seconds", help="ref_video 模式下从前一 clip 抽取的尾段时长（秒）。"),
        voice_asset: str | None = typer.Option(None, "--voice-asset", help="音色样本 asset ID，每个 clip 都会附加。"),
        ref_audio: list[str] = typer.Option([], "--ref-audio", help="额外参考音频，每个 clip 共享。"),
        no_audio: bool = typer.Option(False, "--no-audio", help="禁用同步音频生成。"),
        quality: str | None = typer.Option(None, "--quality", help="视频分辨率：480p/720p/1080p。"),
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

        if continuity_mode not in {"first_frame", "ref_video", "both", "auto"}:
            typer.echo("错误：--continuity-mode 必须是 first_frame / ref_video / auto 之一。", err=True)
            raise typer.Exit(1)
        if continuity_mode == "both":
            continuity_mode = "auto"

        out_dir = output_dir or prompt_dir

        for cn in clip_nums:
            pf = prompt_dir / f"视频_Clip{cn:03d}.prompt.txt"
            if not pf.exists():
                typer.echo(f"错误：未找到 {pf}", err=True)
                raise typer.Exit(1)

        shared_audios: list[str] = list(ref_audio)
        if voice_asset:
            shared_audios.append(voice_asset)

        last_frame_url: str | None = start_frame_url
        last_video_path: Path | None = None

        prev_num = clip_nums[0] - 1
        if regen_prev and not last_frame_url:
            if prev_num >= 1:
                prev_label = f"Clip{prev_num:03d}"
                prev_prompt_file = prompt_dir / f"视频_{prev_label}.prompt.txt"
                if prev_prompt_file.exists():
                    typer.echo(f"先重新生成 {prev_label} 以获取衔接素材 ...")
                    prev_prompt = prev_prompt_file.read_text(encoding="utf-8").strip()
                    prev_full = f"{prompt_header}\n\n{prev_prompt}" if prompt_header else prev_prompt
                    prev_output = out_dir / f"视频_{prev_label}.mp4"
                    prev_result = _submit_video_compat(
                        ctx=ctx, prompt=prev_full, images=list(image),
                        asset_ids=asset, ratio=ratio, duration=duration,
                        model=model, wait=True, output=prev_output,
                        run_name=f"chain-prev-{prev_label}", return_last_frame=True,
                        ref_audios=shared_audios, generate_audio=not no_audio, quality=quality,
                    )
                    if prev_result and prev_result.last_frame_url:
                        last_frame_url = prev_result.last_frame_url
                        typer.echo(f"  {prev_label} 尾帧URL已获取")
                    if prev_output.exists():
                        last_video_path = prev_output
        elif prev_num >= 1:
            existing_prev = out_dir / f"视频_Clip{prev_num:03d}.mp4"
            if existing_prev.exists():
                last_video_path = existing_prev

        typer.echo(f"将按顺序重新生成 {len(clip_nums)} 个 clip: {', '.join(f'Clip{c:03d}' for c in clip_nums)}")
        typer.echo(f"模式: continuity={continuity_mode}, voice_asset={'有' if voice_asset else '无'}")

        for idx, cn in enumerate(clip_nums):
            clip_label = f"Clip{cn:03d}"
            prompt_file = prompt_dir / f"视频_{clip_label}.prompt.txt"
            clip_prompt = prompt_file.read_text(encoding="utf-8").strip()
            full_prompt = f"{prompt_header}\n\n{clip_prompt}" if prompt_header else clip_prompt
            clip_output = out_dir / f"视频_{clip_label}.mp4"

            typer.echo(f"\n{'='*50}")
            typer.echo(f"[{idx+1}/{len(clip_nums)}] 正在重新生成 {clip_label} ...")

            ff_url: str | None = None
            videos_for_this: list[str] = []

            if continuity_mode == "first_frame" and last_frame_url:
                ff_url = last_frame_url
                typer.echo("  首帧URL衔接")

            if continuity_mode in {"ref_video", "auto"} and last_video_path and last_video_path.exists():
                tail_dir = out_dir / "_tails"
                tail_path = tail_dir / f"{last_video_path.stem}_tail.mp4"
                try:
                    _extract_tail_segment(last_video_path, tail_path, tail_seconds=prev_tail_seconds)
                    videos_for_this.append(str(tail_path))
                    typer.echo(f"  ref_video 衔接：{last_video_path.name} → 尾段 {prev_tail_seconds:.1f}s")
                except Exception as exc:
                    typer.echo(f"  警告：尾段抽取失败：{exc}", err=True)

            try:
                result = _submit_video_compat(
                    ctx=ctx,
                    prompt=full_prompt,
                    images=list(image),
                    asset_ids=asset,
                    ratio=ratio,
                    duration=duration,
                    model=model,
                    wait=True,
                    output=clip_output,
                    run_name=f"chain-regen-{clip_label}",
                    return_last_frame=True,
                    first_frame_url=ff_url,
                    ref_videos=videos_for_this,
                    ref_audios=shared_audios,
                    generate_audio=not no_audio,
                    quality=quality,
                )
            except Exception as exc:
                msg = str(exc)
                can_fallback = (
                    continuity_mode == "auto"
                    and last_frame_url
                    and videos_for_this
                    and (
                        "may contain real person" in msg
                        or "first/last frame content cannot be mixed" in msg
                        or "Sensitive" in msg
                    )
                )
                if not can_fallback:
                    raise
                typer.echo(
                    f"  警告：ref_video 提交被拒（{msg.splitlines()[0][:120]}），降级为 first_frame_url 重试 ..."
                )
                result = _submit_video_compat(
                    ctx=ctx,
                    prompt=full_prompt,
                    images=[],
                    asset_ids=[],
                    ratio=ratio,
                    duration=duration,
                    model=model,
                    wait=True,
                    output=clip_output,
                    run_name=f"chain-regen-{clip_label}-fallback",
                    return_last_frame=True,
                    first_frame_url=last_frame_url,
                    ref_videos=[],
                    ref_audios=[],
                    generate_audio=not no_audio,
                    quality=quality,
                )

            if result and result.last_frame_url:
                last_frame_url = result.last_frame_url
                typer.echo("  尾帧URL已缓存，将用于下一 clip 衔接")
            else:
                last_frame_url = None
            if clip_output.exists():
                last_video_path = clip_output

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

    @app.command(
        "clip-concat",
        help=(
            "拼接 clip 为完整视频。默认 stream copy；启用 --crossfade-seconds 或 --normalize-audio 时切换到 "
            "filter_complex 重编码。使用 --strip-audio 可移除所有音频轨道。"
        ),
    )
    def clip_concat(
        ctx: typer.Context,
        input_dir: Path = typer.Option(..., "--input-dir", "-d", help="包含 视频_ClipXXX.mp4 的目录。"),
        output: Path = typer.Option(..., "--output", "-o", help="输出视频路径。"),
        trim_tail: float = typer.Option(0.0, "--trim-tail", help="裁掉每个 clip 尾部的秒数（可解决叙事泄漏）。"),
        crossfade_seconds: float = typer.Option(
            0.0,
            "--crossfade-seconds",
            help="段间淡变时长（秒，建议 0.3-0.6）。>0 时强制重编码。",
        ),
        normalize_audio: bool = typer.Option(
            False,
            "--normalize-audio/--no-normalize-audio",
            help="启用 loudnorm (I=-16 LRA=11 TP=-1.5)，统一段间音量。",
        ),
        strip_audio: bool = typer.Option(
            False,
            "--strip-audio/--no-strip-audio",
            help="移除所有音频轨道。",
        ),
        audio_fadein: float = typer.Option(
            0.0,
            "--audio-fadein",
            help="每个 clip 音频开头淡入秒数（消除 Seedance 启动底噪，推荐 0.3-0.5）。",
        ),
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
                    dur = _probe_duration(clip, default=15.0)
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

            if audio_fadein > 0 and not strip_audio:
                faded_sources: list[Path] = []
                for src in sources:
                    faded = tmp_dir / f"fadein_{src.name}"
                    fade_cmd = [
                        "ffmpeg", "-y", "-i", str(src),
                        "-af", f"afade=t=in:st=0:d={audio_fadein:.3f}",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        str(faded),
                    ]
                    r = subprocess.run(fade_cmd, capture_output=True, text=True, timeout=120)
                    if r.returncode != 0:
                        typer.echo(f"  音频淡入失败 {src.name}: {r.stderr[-150:]}", err=True)
                        faded_sources.append(src)
                    else:
                        faded_sources.append(faded.resolve())
                sources = faded_sources
                typer.echo(f"  已对 {len(clips)} 个 clip 添加 {audio_fadein}s 音频淡入")

            advanced = (
                crossfade_seconds > 0
                or normalize_audio
            )

            if not advanced:
                filelist = tmp_dir / "concat_list.txt"
                filelist.write_text("\n".join(f"file '{s}'" for s in sources) + "\n")
                cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(filelist)]
                if strip_audio:
                    cmd.extend(["-an", "-c:v", "copy"])
                else:
                    cmd.extend(["-c", "copy"])
                cmd.append(str(output))
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if result.returncode != 0:
                    typer.echo(f"拼接失败: {result.stderr[-200:]}", err=True)
                    raise typer.Exit(1)
                final_dur = _probe_duration(output)
                features_simple = []
                if strip_audio:
                    features_simple.append("无音频")
                if audio_fadein > 0:
                    features_simple.append(f"音频淡入 {audio_fadein}s")
                mode_label = " · ".join(features_simple) if features_simple else "stream copy"
                typer.echo(f"拼接完成（{mode_label}）: {output} ({len(clips)} 个 clip, {final_dur:.1f}s)")
                return

            try:
                final_dur, _ = _run_concat_with_filters(
                    sources,
                    output,
                    crossfade=crossfade_seconds,
                    normalize_audio=normalize_audio,
                )
            except RuntimeError as exc:
                typer.echo(f"拼接失败: {exc}", err=True)
                raise typer.Exit(1)

            features = []
            if crossfade_seconds > 0:
                features.append(f"xfade {crossfade_seconds:.2f}s")
            if normalize_audio:
                features.append("loudnorm")
            typer.echo(
                f"拼接完成（重编码 · {' / '.join(features)}）: {output} "
                f"({len(clips)} 个 clip, {final_dur:.1f}s)"
            )
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

    @app.command("clip-extract-tail", help="从 mp4 抽取尾段（默认 5s），可选自动上传 TOS 用于做 reference_video。")
    def clip_extract_tail(
        ctx: typer.Context,
        input_file: Path = typer.Option(..., "--input", "-i", help="输入视频文件（mp4）。"),
        output: Path | None = typer.Option(None, "--output", "-o", help="输出尾段文件（默认 <input>_tail.mp4）。"),
        tail_seconds: float = typer.Option(5.0, "--tail-seconds", help="尾段时长（秒，2-15）。"),
        upload_tos: bool = typer.Option(False, "--upload/--no-upload", help="是否上传到 TOS 并返回 URL。"),
    ) -> None:
        obj: AppContext = ctx.obj
        input_file = input_file.resolve()
        if not input_file.exists():
            typer.echo(f"错误：文件不存在 {input_file}", err=True)
            raise typer.Exit(1)
        if output is None:
            output = input_file.with_name(f"{input_file.stem}_tail.mp4")
        output = output.resolve()

        try:
            _extract_tail_segment(input_file, output, tail_seconds=tail_seconds)
        except Exception as exc:
            typer.echo(f"抽取失败：{exc}", err=True)
            raise typer.Exit(1)

        url: str | None = None
        if upload_tos:
            url = _upload_to_tos(output, kind="video")

        payload = {"input": str(input_file), "output": str(output), "tail_seconds": tail_seconds, "url": url}
        pretty = [f"输入: {input_file.name}", f"尾段输出: {output}", f"时长: {tail_seconds:.1f}s"]
        if url:
            pretty.append(f"TOS URL: {url}")
        _emit(obj, payload, pretty)

    @app.command("voice-extract", help="从视频提取一段对白音频（默认 6-12s 区间），可选自动上传 TOS。")
    def voice_extract(
        ctx: typer.Context,
        input_file: Path = typer.Option(..., "--input", "-i", help="输入视频文件（mp4）。"),
        output: Path | None = typer.Option(None, "--output", "-o", help="输出音频文件（默认 <input>_voice.mp3）。"),
        start: float = typer.Option(6.0, "--start", help="起始时间（秒）。"),
        duration: float = typer.Option(8.0, "--duration", help="时长（秒，2-15）。"),
        fmt: str = typer.Option("mp3", "--fmt", help="输出格式：mp3 / wav。"),
        upload_tos: bool = typer.Option(False, "--upload/--no-upload", help="是否上传到 TOS 并返回 URL。"),
    ) -> None:
        obj: AppContext = ctx.obj
        input_file = input_file.resolve()
        if not input_file.exists():
            typer.echo(f"错误：文件不存在 {input_file}", err=True)
            raise typer.Exit(1)
        if output is None:
            ext = "wav" if fmt.lower() == "wav" else "mp3"
            output = input_file.with_name(f"{input_file.stem}_voice.{ext}")
        output = output.resolve()

        try:
            _extract_voice_audio(input_file, output, start=start, duration=duration, fmt=fmt)
        except Exception as exc:
            typer.echo(f"提取失败：{exc}", err=True)
            raise typer.Exit(1)

        url: str | None = None
        if upload_tos:
            url = _upload_to_tos(output, kind="audio")

        payload = {
            "input": str(input_file),
            "output": str(output),
            "start": start,
            "duration": duration,
            "url": url,
        }
        pretty = [
            f"输入: {input_file.name}",
            f"音频输出: {output}",
            f"区间: {start:.1f}s - {start+duration:.1f}s",
        ]
        if url:
            pretty.append(f"TOS URL: {url}")
        _emit(obj, payload, pretty)

    @app.command(
        "voice-asset-from-clip",
        help=(
            "从视频提取音色 → 上传 TOS → 尝试 asset 入库（失败自动切换格式或回退到直接 TOS URL）。"
            "无论 asset 是否成功，TOS URL 都可直接做 --reference-audio。"
        ),
    )
    def voice_asset_from_clip(
        ctx: typer.Context,
        input_file: Path = typer.Option(..., "--input", "-i", help="输入视频文件（mp4，通常是第 1 个 clip）。"),
        group_id: str = typer.Option(..., "--group-id", help="所属素材组 ID。"),
        name: str = typer.Option("", "--name", help="素材名称（默认 voice-from-<filename>）。"),
        start: float = typer.Option(6.0, "--start", help="起始时间（秒）。"),
        duration: float = typer.Option(8.0, "--duration", help="时长（秒，2-15）。"),
        fmt: str = typer.Option("wav", "--fmt", help="首选音频格式：wav / mp3。失败会自动尝试另一格式。"),
        keep_local: bool = typer.Option(False, "--keep-local/--cleanup", help="是否保留本地音频文件。"),
        wait: bool = typer.Option(True, "--wait/--no-wait", help="等待 asset Active。"),
    ) -> None:
        obj: AppContext = ctx.obj
        input_file = input_file.resolve()
        if not input_file.exists():
            typer.echo(f"错误：文件不存在 {input_file}", err=True)
            raise typer.Exit(1)

        primary = "wav" if fmt.lower() == "wav" else "mp3"
        secondary = "mp3" if primary == "wav" else "wav"
        try_order = [primary, secondary]

        asset_name = name or f"voice-from-{input_file.stem}"
        asset_id: str | None = None
        asset_url: str | None = None
        asset_status: str | None = None
        used_fmt: str | None = None
        last_voice_url: str | None = None
        last_voice_path: Path | None = None
        last_asset_error: Exception | None = None

        for attempt_fmt in try_order:
            voice_path = input_file.with_name(f"{input_file.stem}_voice.{attempt_fmt}")
            try:
                _extract_voice_audio(
                    input_file, voice_path, start=start, duration=duration, fmt=attempt_fmt
                )
            except Exception as exc:
                typer.echo(f"  提取失败（fmt={attempt_fmt}）：{exc}", err=True)
                continue
            typer.echo(f"音色样本已抽取（{attempt_fmt}）：{voice_path.name}（{duration:.1f}s）")

            try:
                voice_url = _upload_to_tos(voice_path, kind="audio")
            except Exception as exc:
                typer.echo(f"  TOS 上传失败（fmt={attempt_fmt}）：{exc}", err=True)
                continue
            last_voice_url = voice_url
            last_voice_path = voice_path

            try:
                client = _build_assets_client()
                asset = client.create_asset(
                    group_id=group_id, url=voice_url, asset_type="Audio", name=asset_name
                )
                typer.echo(f"已入库素材ID: {asset.id}（处理中）")
                if wait:
                    asset = client.wait_for_active(asset.id)
                    typer.echo(f"素材状态: 可用，引用URL: {asset.asset_url}")
                asset_id = asset.id
                asset_url = asset.asset_url
                asset_status = asset.status
                used_fmt = attempt_fmt
                last_asset_error = None
                break
            except Exception as exc:
                last_asset_error = exc
                typer.echo(
                    f"  警告：asset 入库失败（fmt={attempt_fmt}）：{exc}",
                    err=True,
                )
                continue

        if asset_id is None and last_voice_url is None:
            typer.echo("错误：所有格式均提取/上传失败，无法生成音色样本。", err=True)
            raise typer.Exit(1)

        if asset_id is None:
            used_fmt = used_fmt or try_order[-1]
            typer.echo(
                "  asset 入库均失败（"
                f"{type(last_asset_error).__name__ if last_asset_error else 'unknown'}），"
                f"回退使用 TOS URL 直接做 --reference-audio: {last_voice_url}"
            )

        if not keep_local and last_voice_path is not None:
            try:
                last_voice_path.unlink()
            except Exception:
                pass

        payload = {
            "voice_asset_id": asset_id,
            "asset_url": asset_url,
            "tos_url": last_voice_url,
            "status": asset_status,
            "used_fmt": used_fmt,
            "fallback_used": asset_id is None,
        }
        pretty: list[str] = []
        if asset_id is not None:
            pretty.extend([
                f"音色 Asset ID: {asset_id}",
                f"asset:// 引用: {asset_url}",
                f"原始 TOS URL: {last_voice_url}",
                f"使用格式: {used_fmt}",
                f"状态: {asset_status}",
                "",
                "复用方式（推荐）：",
                f"  changdu sequential-generate ... --voice-asset {asset_id}",
                f"  changdu multimodal2video ... --ref-audio {asset_id}",
            ])
        else:
            pretty.extend([
                "音色 Asset 入库失败，已自动回退到 TOS URL 模式：",
                f"  TOS URL: {last_voice_url}",
                f"  使用格式: {used_fmt}",
                "",
                "复用方式（fallback）：",
                f"  changdu sequential-generate ... --reference-audio {last_voice_url}",
                f"  changdu multimodal2video ... --ref-audio {last_voice_url}",
            ])
        _emit(obj, payload, pretty)

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

            # --- Rule 1: Check for subject definition (Seedance 2.0 Section 二) ---
            has_subject_def = bool(re.search(r"将.{0,6}图片\d.{0,20}定义为", raw))
            has_image_ref = bool(re.search(r"图片\d|@图\d", raw))
            if has_image_ref and not has_subject_def:
                issues.append("[主体定义] 引用了图片但未使用「将图片N中的X定义为主体」格式 — 模型可能无法准确绑定角色")

            # --- Rule 2: Flag precise timestamps (Seedance 2.0 Section 三) ---
            has_timeline = bool(re.search(r"\(\d+[–\-]\d+\.?\d*\s*s\)", raw))
            if has_timeline:
                issues.append("[时间轴] 使用了精确时间标记如(0-3s) — Seedance 2.0对精确时间支持不稳定，建议用自然语言顺序描述（先...紧接着...随后...）")

            # --- Rule 2b: Check for three-view reference mentions ---
            if "三视图" in raw or "多视图" in raw:
                issues.append("[参考图] 提到三视图/多视图 — Seedance 2.0明确不建议使用三视图作为人物参考，应使用面部特写+全身照")

            # --- Rule 3: Check for abstract emotion words ---
            abstract_words = ["很悲伤", "非常愤怒", "很高兴", "十分紧张", "很害怕", "震撼", "漂亮", "好看"]
            found_abstract = [w for w in abstract_words if w in raw]
            if found_abstract:
                issues.append(f"[抽象词] 发现模糊情绪词: {', '.join(found_abstract)} — 应替换为具体身体信号")

            # --- Rule 4: Check for too many camera movements overall ---
            cam_words = ["推镜", "拉远", "横移", "摇移", "环绕", "俯拍", "仰拍", "跟拍", "手持"]
            cam_count = sum(1 for w in cam_words if w in raw)
            if cam_count >= 5:
                issues.append(f"[运镜] 全文含{cam_count}种运镜指令 — 15秒内建议不超过3种运镜，过多会导致画面抖动")

            # --- Rule 5: Check for violent action words ---
            violent_words = ["狂奔", "剧烈翻滚", "大跳", "高速旋转", "疯狂", "猛烈冲刺"]
            found_violent = [w for w in violent_words if w in raw]
            if found_violent:
                issues.append(f"[动作] 高强度动作词: {', '.join(found_violent)} — Seedance 偏好缓慢连续动作，可能生成抖动")

            # --- Rule 6: Check for scope boundary ---
            has_scope = "本段仅展示上述动作" in raw or "不展示后续剧情" in raw
            if not has_scope:
                issues.append("[范围] 无范围边界声明 — 可能导致叙事泄漏到下一 clip")

            # --- Rule 7: Check for tail markers (Seedance 2.0 V-2, V-3) ---
            has_no_bgm = "不要BGM" in raw or "不要bgm" in raw.lower()
            has_no_subtitle = "不要字幕" in raw or "无字幕" in raw
            has_strong_subtitle = "避免画面生成字幕" in raw or "保持无字幕" in raw
            has_no_watermark = "不要水印" in raw or "不要logo" in raw
            if not has_no_bgm or not has_no_subtitle:
                issues.append("[尾标] 缺少 '不要BGM，不要字幕' 尾部约束")
            if not has_strong_subtitle:
                issues.append("[字幕] 建议使用更强约束：'保持无字幕，避免画面生成字幕'（Seedance 2.0 FAQ V-2）")
            if not has_no_watermark:
                issues.append("[水印] 缺少 '不要水印，不要logo' 约束（Seedance 2.0 FAQ V-3）")

            # --- Rule 8: Check for transition words between actions ---
            transition_phrases = ["借着", "顺势", "紧接着", "随后", "与此同时", "同时", "然后", "接着"]
            has_transitions = any(p in raw for p in transition_phrases)
            if not has_transitions:
                issues.append("[衔接] 动作间缺少过渡词 — 加入'紧接着/随后/顺势'让模型自然安排节奏（Seedance 2.0推荐）")

            # --- Rule 9: Check for ambiguous appearance descriptions ---
            ambiguous_hair = ["束冠短发", "短发束起", "发髻", "束发"]
            found_ambiguous_hair = [w for w in ambiguous_hair if w in raw]
            has_explicit_hat = any(w in raw for w in ["幞头", "官帽", "头盔", "斗笠", "头巾", "帽子", "头戴"])
            if found_ambiguous_hair and not has_explicit_hat:
                issues.append(f"[头饰] 发型描述模糊: {', '.join(found_ambiguous_hair)} — 易导致帽子时有时无穿帮，应明确写'头戴XX帽'或'无帽露发髻'")

            # --- Rule 10: Check for verbose non-standard meta-tags ---
            meta_tags = ["【角色锚定】", "【妆造锁定】", "【道具锁定】", "【场景锁定】", "【否定约束】",
                         "【动作交接】", "【音色锚定】", "【视频参考说明】"]
            found_tags = [t for t in meta_tags if t in raw]
            if len(found_tags) >= 4:
                issues.append(
                    f"[冗余] 使用了{len(found_tags)}个自定义meta标签 — Seedance 2.0推荐简洁格式：主体定义+运动+环境+运镜+美学，"
                    "过多标签会增加噪声干扰模型理解"
                )

            # --- Rule 11: Check for double-dash which breaks Seedance parsing ---
            if "--" in raw:
                issues.append("[特殊字符] 包含 '--' — Seedance 2.0不解析该符号之后的内容（FAQ 四）")

            # --- Rule 12: Check for double periods ---
            if "。。" in raw:
                issues.append("[格式] 包含重复句号 '。。' — 应修正为单个句号")

            # --- Rule 13: Check character @图片N binding (FAQ: 写成「男生A@图片1」而非「男生A」) ---
            subject_defs = re.findall(r"定义为(\S+)", raw)
            for subj in subject_defs:
                subj_clean = subj.rstrip("。，,.")
                if subj_clean and len(subj_clean) >= 2:
                    occurrences = [m.start() for m in re.finditer(re.escape(subj_clean), raw)]
                    for occ_start in occurrences:
                        preceding = raw[max(0, occ_start - 10):occ_start]
                        if "定义为" in preceding:
                            continue
                        following = raw[occ_start + len(subj_clean):occ_start + len(subj_clean) + 10]
                        if not re.match(r"@图片\d|（图片\d）", following):
                            if not re.match(r"@图\d", following):
                                issues.append(
                                    f"[角色绑定] '{subj_clean}' 出现时未跟随 @图片N — "
                                    "Seedance 2.0要求每次提及角色都用「角色名@图片N」格式（FAQ: 写成「男生A@图片1」而非「男生A」）"
                                )
                                break

            # --- Rule 14: Anti-twin check for multi-character scenes (FAQ V-7) ---
            char_count = len(subject_defs)
            if char_count >= 2:
                has_anti_twin = "不要多人同脸" in raw or "不要在同一画面中复制相同人物" in raw or "杜绝双胞胎" in raw
                if not has_anti_twin:
                    issues.append(
                        f"[双胞胎] 检测到{char_count}个主体定义但缺少反双胞胎约束 — "
                        "多角色场景建议加「视频全程不要在同一画面中复制相同人物，不要多人同脸」（FAQ V-7）"
                    )

            # --- Rule 15: Voice trait description check (FAQ A-3) ---
            voice_refs = re.findall(r"采用音频\d的(.{0,20}?)(?:音色|的音色)", raw)
            for ref_text in voice_refs:
                ref_stripped = ref_text.strip()
                if not ref_stripped or ref_stripped in ("", "的"):
                    issues.append(
                        "[音色] 「采用音频N的音色」缺少音色特征描述 — "
                        "建议加具体描述如「采用音频1的低厚温润中年男声的音色」，能显著提升音色准确性（FAQ A-3）"
                    )
                    break

            # --- Rule 16: Reference image separation check (FAQ: 参考图分工不明确) ---
            if "三视图" not in raw:
                img_def_lines = [line for line in raw.split("\n") if re.search(r"图片\d", line) and "定义为" in line]
                for line in img_def_lines:
                    if re.search(r"(场景|背景|环境).{0,10}(角色|人物|主体|定义为)", line) or \
                       re.search(r"(角色|人物|主体).{0,10}(场景|背景|环境)", line):
                        issues.append(
                            "[参考图分工] 同一图片定义中混合了角色与场景 — "
                            "每张参考图只承担一种职责（面部/全身/场景/道具），禁止混用"
                        )
                        break

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

                # Fix: Add tail markers if missing (Seedance 2.0 V-2, V-3)
                tail_line = "保持无字幕，避免画面生成字幕，不要水印，不要logo，不要BGM。"
                if not has_no_bgm or not has_no_subtitle or not has_no_watermark:
                    if tail_line not in optimized:
                        optimized = optimized.rstrip() + "\n" + tail_line
                        fixes.append("+ 追加Seedance 2.0尾部约束（无字幕/无水印/无BGM）")

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
        typer.echo("【示例7：连续视频生成（推荐：ref_video 衔接 + 音色锁定）】")
        typer.echo("# 一键顺序生成多个 clip，默认用前一 clip 尾段做 reference_video，锁定妆造/站位/音色")
        typer.echo("changdu sequential-generate \\")
        typer.echo("  --prompt-dir ./单集制作/EP001/ \\")
        typer.echo("  --asset <角色三视图ID> --asset <场景ID> \\")
        typer.echo("  --continuity-mode ref_video \\")
        typer.echo("  --voice-asset <音色样本ID> \\")
        typer.echo("  --prev-tail-seconds 5 \\")
        typer.echo("  --ratio 16:9 --duration 15 \\")
        typer.echo('  --prompt-header "图片1是女主三视图，图片2是场景。视频1 是前段尾段，仅作妆造参考。音轨1 锁音色。" \\')
        typer.echo("  --output-dir ./单集制作/EP001/")
        typer.echo("")
        typer.echo("【示例7b：让 sequential-generate 自动在第1段后入库音色，从第2段起复用】")
        typer.echo("changdu sequential-generate \\")
        typer.echo("  --prompt-dir ./单集制作/EP001/ \\")
        typer.echo("  --asset <女主三视图ID> --asset <场景ID> \\")
        typer.echo("  --continuity-mode ref_video \\")
        typer.echo("  --voice-from-clip 1 --voice-group-id <主角素材组ID> \\")
        typer.echo("  --voice-clip-start 6 --voice-clip-duration 8 \\")
        typer.echo("  --ratio 16:9 --duration 15")
        typer.echo("")
        typer.echo("【示例8：手动多模态参考生视频（图 + 视频 + 音频 三类一起喂）】")
        typer.echo('changdu multimodal2video \\')
        typer.echo('  --image 角色三视图.jpg --image 场景.jpg \\')
        typer.echo('  --ref-video ./单集制作/EP001/视频_Clip003.mp4 \\')
        typer.echo('  --voice-asset asset-xxxxxxxx \\')
        typer.echo('  --prompt "图1是女主三视图，图2是场景。视频1 是 Clip003 尾段，仅做妆造与位置参考。音轨1 锁音色。" \\')
        typer.echo('  --ratio 16:9 --duration 15 --wait --output clip004.mp4')
        typer.echo("")
        typer.echo("【示例8b：旧式手动尾帧衔接（仅向下兼容，更建议用 ref_video）】")
        typer.echo('changdu multimodal2video --image 角色.jpg --prompt "..." --wait --output clip001.mp4 --return-last-frame')
        typer.echo('changdu multimodal2video --image 角色.jpg --prompt "..." --wait --output clip002.mp4 --return-last-frame --first-frame-url <上一clip的尾帧URL>')
        typer.echo("")
        typer.echo("【示例9：穿帮修复 — 妆造/角色 用 ref_video + ref_image 双锚定重生】")
        typer.echo("changdu clip-regen \\")
        typer.echo("  --clip 4 --prompt-dir ./单集制作/EP001/ \\")
        typer.echo("  --asset <女主三视图ID> --asset <场景ID> \\")
        typer.echo("  --prev-clip ./单集制作/EP001/视频_Clip003.mp4 \\")
        typer.echo("  --voice-asset <音色样本ID> \\")
        typer.echo("  --prompt-header '图片1是女主三视图，图片2是场景。视频1 是 Clip003 尾段，仅做妆造与位置参考。音轨1 锁音色。' \\")
        typer.echo("  --ratio 16:9 --duration 15")
        typer.echo("")
        typer.echo("【示例9b：链式重生（连续多段 CHARACTER/MAKEUP 穿帮）】")
        typer.echo("changdu clip-chain-regen \\")
        typer.echo("  --clips 7,8,9 --prompt-dir ./单集制作/EP001/ \\")
        typer.echo("  --asset <女主三视图ID> --asset <场景ID> \\")
        typer.echo("  --regen-prev --continuity-mode ref_video \\")
        typer.echo("  --voice-asset <音色样本ID> \\")
        typer.echo("  --ratio 16:9 --duration 15")
        typer.echo("")
        typer.echo("【示例10：抽前段尾段做下一段的 reference_video】")
        typer.echo("changdu clip-extract-tail -i 视频_Clip003.mp4 --tail-seconds 5 --upload")
        typer.echo("")
        typer.echo("【示例11：从视频提取主角音色，并入库为 Audio Asset】")
        typer.echo("changdu voice-asset-from-clip \\")
        typer.echo("  --input ./单集制作/EP001/视频_Clip001.mp4 \\")
        typer.echo("  --group-id <主角素材组ID> --start 6 --duration 8")
        typer.echo("# 输出：音色 Asset ID: asset-xxxxxxxx，可直接在后续命令中用 --voice-asset 引用")
        typer.echo("")
        typer.echo("【示例12：拼接全部 clip 为完整视频（保留音频）】")
        typer.echo("changdu clip-concat \\")
        typer.echo("  --input-dir ./单集制作/EP001/ \\")
        typer.echo("  --output ./单集制作/EP001/完整版.mp4")
        typer.echo("")
        typer.echo("【示例13：拼接 + 裁掉每个 clip 尾部（去叙事泄漏）】")
        typer.echo("changdu clip-concat \\")
        typer.echo("  --input-dir ./单集制作/EP001/ \\")
        typer.echo("  --output ./单集制作/EP001/完整版.mp4 \\")
        typer.echo("  --trim-tail 1.0")
        typer.echo("")
        typer.echo("【示例14：裁剪单个 clip（去头尾叙事泄漏）】")
        typer.echo("changdu clip-trim \\")
        typer.echo("  --input 视频_Clip003.mp4 \\")
        typer.echo("  --output 视频_Clip003_trimmed.mp4 \\")
        typer.echo("  --trim-tail 2.0")
        typer.echo("")
        typer.echo("【示例15：提示词优化（含角色绑定/反双胞胎/音色描述/参考图分工检查）】")
        typer.echo("changdu prompt-optimize --dir ./单集制作/EP003/ --check")
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
    last_frame_url: str | None = None,
    ref_videos: list[str] | None = None,
    ref_audios: list[str] | None = None,
    generate_audio: bool = True,
    quality: str | None = None,
) -> Any:
    """Submit a video generation request. Returns TaskStatusResponse when wait=True, None otherwise."""

    obj: AppContext = ctx.obj
    run_id = obj.trajectory_store.create_run(run_name)
    encoded_images = [encode_image_to_data_url(p) for p in images]
    asset_urls = [f"asset://{aid}" if not aid.startswith("asset://") else aid for aid in (asset_ids or [])]
    all_image_refs = encoded_images + asset_urls

    resolved_videos = [_resolve_media_ref(v, kind="video") for v in (ref_videos or [])]
    resolved_audios = [_resolve_media_ref(a, kind="audio") for a in (ref_audios or [])]

    req = VideoGenerateRequest(
        model=model or obj.config.video_model,
        prompt=prompt,
        ratio=ratio,
        duration=duration,
        images=all_image_refs,
        videos=resolved_videos,
        audios=resolved_audios,
        return_last_frame=return_last_frame,
        first_frame_url=first_frame_url,
        last_frame_url=last_frame_url,
        generate_audio=generate_audio,
        quality=quality,
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
    if result.audio_url:
        out_payload["audio_url"] = result.audio_url
    if result.video_duration:
        out_payload["video_duration"] = result.video_duration
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
