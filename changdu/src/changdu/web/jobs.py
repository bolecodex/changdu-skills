"""Background job execution for the local web studio."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from changdu.web.projects import safe_resolve
from changdu.web.schemas import ConcatRequest, GenerateRequest, Job


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def command_preview(cmd: list[str]) -> str:
    return " ".join(cmd)


def changdu_command() -> list[str]:
    return [sys.executable, "-m", "changdu.cli.main"]


def build_generate_command(req: GenerateRequest) -> list[str]:
    prompt_dir = safe_resolve(req.promptDir, must_exist=True)
    output_dir = safe_resolve(req.outputDir or req.promptDir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = changdu_command() + [
        "sequential-generate",
        "--prompt-dir",
        str(prompt_dir),
        "--output-dir",
        str(output_dir),
        "--ratio",
        req.ratio,
        "--duration",
        str(req.duration),
        "--continuity-mode",
        req.continuityMode,
        "--prev-tail-seconds",
        str(req.prevTailSeconds),
    ]
    for image in req.images:
        if image.strip():
            cmd.extend(["--image", str(safe_resolve(image, must_exist=True))])
    for asset in req.assets:
        if asset.strip():
            cmd.extend(["--asset", asset.strip()])
    if req.quality:
        cmd.extend(["--quality", req.quality])
    if req.voiceAsset:
        cmd.extend(["--voice-asset", req.voiceAsset])
    if req.voiceFromClip is not None:
        cmd.extend(["--voice-from-clip", str(req.voiceFromClip)])
        if req.voiceGroupId:
            cmd.extend(["--voice-group-id", req.voiceGroupId])
    if req.noAudio:
        cmd.append("--no-audio")
    if req.promptHeader:
        cmd.extend(["--prompt-header", req.promptHeader])
    return cmd


def build_concat_command(req: ConcatRequest) -> list[str]:
    input_dir = safe_resolve(req.inputDir, must_exist=True)
    output = safe_resolve(req.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = changdu_command() + [
        "clip-concat",
        "--input-dir",
        str(input_dir),
        "--output",
        str(output),
        "--trim-tail",
        str(req.trimTail),
        "--crossfade-seconds",
        str(req.crossfadeSeconds),
        "--audio-fadein",
        str(req.audioFadein),
    ]
    cmd.append("--normalize-audio" if req.normalizeAudio else "--no-normalize-audio")
    cmd.append("--strip-audio" if req.stripAudio else "--no-strip-audio")
    return cmd


@dataclass
class JobRecord:
    id: str
    type: str
    status: str
    commandPreview: str
    createdAt: str
    logPath: str
    startedAt: str | None = None
    finishedAt: str | None = None
    exitCode: int | None = None
    error: str | None = None

    def public(self) -> Job:
        return Job(**{k: v for k, v in asdict(self).items() if k != "logPath"})  # type: ignore[arg-type]


class JobManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (Path.cwd() / "outputs" / "web-runs")
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobRecord] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        for meta_path in self.root.glob("*/job.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                record = JobRecord(**data)
                if record.status == "running":
                    record.status = "failed"
                    record.error = "Process ended while server was offline."
                    record.finishedAt = record.finishedAt or now_iso()
                self._jobs[record.id] = record
            except Exception:
                continue

    def create(self, job_type: str, cmd: list[str]) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job_dir = self.root / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        record = JobRecord(
            id=job_id,
            type=job_type,
            status="queued",
            commandPreview=command_preview(cmd),
            createdAt=now_iso(),
            logPath=str(job_dir / "job.log"),
        )
        self._jobs[job_id] = record
        self._save(record)
        asyncio.create_task(self._run(record, cmd))
        return record.public()

    def list(self) -> list[Job]:
        return [record.public() for record in sorted(self._jobs.values(), key=lambda j: j.createdAt, reverse=True)]

    def get(self, job_id: str) -> Job:
        if job_id not in self._jobs:
            raise KeyError(job_id)
        return self._jobs[job_id].public()

    def read_logs(self, job_id: str, offset: int = 0) -> tuple[str, int]:
        if job_id not in self._jobs:
            raise KeyError(job_id)
        path = Path(self._jobs[job_id].logPath)
        if not path.exists():
            return "", 0
        data = path.read_bytes()
        offset = max(0, min(offset, len(data)))
        chunk = data[offset:].decode("utf-8", errors="replace")
        return chunk, len(data)

    def _save(self, record: JobRecord) -> None:
        meta_path = Path(record.logPath).with_name("job.json")
        meta_path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")

    async def _run(self, record: JobRecord, cmd: list[str]) -> None:
        record.status = "running"
        record.startedAt = now_iso()
        self._save(record)
        log_path = Path(record.logPath)
        with log_path.open("ab") as log:
            log.write((record.commandPreview + "\n\n").encode("utf-8"))
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(Path.cwd()),
                )
                assert process.stdout is not None
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    log.write(line)
                    log.flush()
                record.exitCode = await process.wait()
                record.status = "succeeded" if record.exitCode == 0 else "failed"
                if record.exitCode != 0:
                    record.error = f"Process exited with code {record.exitCode}."
            except Exception as exc:
                record.status = "failed"
                record.error = str(exc)
                log.write(f"\n[web] {exc}\n".encode("utf-8"))
            finally:
                record.finishedAt = now_iso()
                self._save(record)
