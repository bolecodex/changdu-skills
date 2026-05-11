"""FastAPI application for the local Changdu web studio."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Annotated

import typer
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from changdu.config import load_config
from changdu.errors import ConfigError
from changdu.web.jobs import JobManager, build_concat_command, build_generate_command, changdu_command
from changdu.web.projects import create_project_from_script, path_for_project_id, safe_resolve, scan_artifacts, scan_project, workspace_root
from changdu.web.schemas import ConcatRequest, GenerateRequest, Job, PromptBody, PromptCheckRequest, Project, ScriptProjectRequest


def create_app(job_manager: JobManager | None = None) -> FastAPI:
    load_workspace_env()
    app = FastAPI(title="Changdu Web Studio", version="0.1.0")
    manager = job_manager or JobManager()

    @app.get("/api/health")
    def health() -> dict[str, object]:
        config_ok = True
        config_error: str | None = None
        try:
            cfg = load_config()
        except ConfigError as exc:
            config_ok = False
            config_error = str(exc)
            cfg = None
        return {
            "ok": True,
            "workspace": str(workspace_root()),
            "config": {
                "ok": config_ok,
                "error": config_error,
                "baseUrl": cfg.base_url if cfg else None,
                "imageModel": cfg.image_model if cfg else None,
                "videoModel": cfg.video_model if cfg else None,
                "trajectoryDir": str(cfg.trajectory_dir) if cfg else None,
                "envFile": str(workspace_root() / ".env"),
                "envFileExists": (workspace_root() / ".env").exists(),
            },
            "tools": {
                "ffmpeg": bool(shutil.which("ffmpeg")),
                "ffprobe": bool(shutil.which("ffprobe")),
                "changduModule": True,
                "changduExecutable": shutil.which("changdu"),
            },
        }

    @app.get("/api/projects", response_model=Project)
    def get_project(
        root: Annotated[str, Query(description="Prompt directory to scan.")],
        create: bool = False,
    ) -> Project:
        try:
            path = safe_resolve(root)
            if create:
                path.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                raise ValueError(f"Path does not exist: {root}")
            return scan_project(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/from-script", response_model=Project)
    def project_from_script(req: ScriptProjectRequest) -> Project:
        try:
            return create_project_from_script(req)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/prompts/{project_id}/{clip}")
    def get_prompt(project_id: str, clip: str) -> dict[str, str]:
        path = _prompt_path(project_id, clip)
        return {"path": str(path), "text": path.read_text(encoding="utf-8")}

    @app.put("/api/prompts/{project_id}/{clip}")
    def put_prompt(project_id: str, clip: str, body: PromptBody) -> dict[str, object]:
        path = _prompt_path(project_id, clip)
        path.write_text(body.text, encoding="utf-8")
        return {"ok": True, "path": str(path)}

    @app.post("/api/prompt-check")
    async def prompt_check(req: PromptCheckRequest) -> dict[str, object]:
        cmd = changdu_command() + ["prompt-optimize", "--check", "--style", req.style]
        try:
            if req.input:
                cmd.extend(["--input", str(safe_resolve(req.input, must_exist=True))])
            elif req.promptDir:
                cmd.extend(["--dir", str(safe_resolve(req.promptDir, must_exist=True))])
            else:
                raise ValueError("promptDir or input is required.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(workspace_root()),
        )
        output_bytes, _ = await proc.communicate()
        raw = output_bytes.decode("utf-8", errors="replace")
        issues = [line.strip() for line in raw.splitlines() if line.strip().startswith("[")]
        return {"ok": proc.returncode == 0, "exitCode": proc.returncode, "issues": issues, "raw": raw}

    @app.post("/api/jobs/sequential-generate", response_model=Job)
    def sequential_generate(req: GenerateRequest) -> Job:
        try:
            return manager.create("sequential-generate", build_generate_command(req))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/jobs/clip-concat", response_model=Job)
    def clip_concat(req: ConcatRequest) -> Job:
        try:
            return manager.create("clip-concat", build_concat_command(req))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/jobs", response_model=list[Job])
    def list_jobs() -> list[Job]:
        return manager.list()

    @app.get("/api/jobs/{job_id}", response_model=Job)
    def get_job(job_id: str) -> Job:
        try:
            return manager.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found.") from exc

    @app.get("/api/jobs/{job_id}/logs")
    def get_logs(job_id: str, offset: int = 0) -> dict[str, object]:
        try:
            chunk, next_offset = manager.read_logs(job_id, offset=offset)
            return {"chunk": chunk, "nextOffset": next_offset}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found.") from exc

    @app.get("/api/artifacts")
    def artifacts(project_id: str) -> dict[str, object]:
        try:
            root = path_for_project_id(project_id)
            return {"artifacts": scan_artifacts(root)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/files")
    def files(path: str) -> FileResponse:
        try:
            resolved = safe_resolve(path, must_exist=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="File not found.")
        if resolved.suffix.lower() not in {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".txt", ".md", ".json", ".jsonl"}:
            raise HTTPException(status_code=403, detail="File type is not previewable.")
        return FileResponse(resolved)

    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return app


def _prompt_path(project_id: str, clip: str) -> Path:
    root = path_for_project_id(project_id)
    label = clip if clip.startswith("Clip") else f"Clip{int(clip):03d}"
    path = root / f"视频_{label}.prompt.txt"
    safe_resolve(path, must_exist=True)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Prompt not found.")
    return path


def load_workspace_env() -> None:
    env_path = workspace_root() / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def run_web(host: str = "127.0.0.1", port: int = 7860, reload: bool = False) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise typer.BadParameter("缺少 Web 依赖，请安装 fastapi 和 uvicorn。") from exc

    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    typer.echo(f"Changdu Web 制作台: http://{host}:{port}")
    uvicorn.run("changdu.web.app:create_app", factory=True, host=host, port=port, reload=reload)
