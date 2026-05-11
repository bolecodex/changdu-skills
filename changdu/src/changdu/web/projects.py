"""Project and artifact scanning helpers."""

from __future__ import annotations

import base64
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from changdu.web.schemas import Artifact, Clip, Project, ScriptProjectRequest

PROMPT_RE = re.compile(r"视频_Clip(\d+)\.prompt\.txt$")
CLIP_RE = re.compile(r"视频_Clip(\d+)\.mp4$")


def workspace_root() -> Path:
    return Path.cwd().resolve()


def safe_resolve(raw: str | Path, *, must_exist: bool = False) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = workspace_root() / path
    resolved = path.resolve()
    root = workspace_root()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Path is outside workspace: {raw}")
    if must_exist and not resolved.exists():
        raise ValueError(f"Path does not exist: {raw}")
    return resolved


def project_id_for(path: Path) -> str:
    encoded = base64.urlsafe_b64encode(str(path.resolve()).encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def path_for_project_id(project_id: str) -> Path:
    padded = project_id + ("=" * (-len(project_id) % 4))
    decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    return safe_resolve(decoded, must_exist=True)


def artifact_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".mp4", ".mov", ".webm"}:
        return "video"
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return "image"
    if ext in {".txt", ".md", ".json", ".jsonl"}:
        return "text"
    return "other"


def file_url(path: Path) -> str:
    return f"/api/files?path={quote(str(path.resolve()))}"


def scan_artifacts(root: Path) -> list[Artifact]:
    if not root.exists():
        return []
    artifacts: list[Artifact] = []
    allowed = {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".txt", ".md", ".json", ".jsonl"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        kind = artifact_kind(path)
        artifacts.append(
            Artifact(
                name=str(path.relative_to(root)),
                path=str(path),
                kind=kind,  # type: ignore[arg-type]
                url=file_url(path) if kind in {"video", "image", "text"} else None,
            )
        )
    return artifacts


def scan_project(root: str | Path) -> Project:
    prompt_dir = safe_resolve(root, must_exist=True)
    output_dir = prompt_dir

    clips: list[Clip] = []
    for prompt in sorted(prompt_dir.iterdir()):
        match = PROMPT_RE.match(prompt.name)
        if not match:
            continue
        index = int(match.group(1))
        label = f"Clip{index:03d}"
        video = output_dir / f"视频_{label}.mp4"
        last_frame = output_dir / f"视频_{label}.lastframe.jpg"
        clips.append(
            Clip(
                index=index,
                label=label,
                promptPath=str(prompt),
                videoPath=str(video) if video.exists() else None,
                lastFramePath=str(last_frame) if last_frame.exists() else None,
                status="done" if video.exists() else "ready",
            )
        )

    return Project(
        id=project_id_for(prompt_dir),
        root=str(prompt_dir),
        promptDir=str(prompt_dir),
        outputDir=str(output_dir),
        clips=clips,
        artifacts=scan_artifacts(output_dir),
    )


def create_project_from_script(req: ScriptProjectRequest) -> Project:
    script = req.script.strip()
    if not script:
        raise ValueError("Script is required.")

    output_root = safe_resolve(req.outputRoot)
    output_root.mkdir(parents=True, exist_ok=True)
    slug = _slugify(req.projectName)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_dir = output_root / f"{stamp}-{slug}"
    project_dir.mkdir(parents=True, exist_ok=False)

    (project_dir / "剧本.txt").write_text(script + "\n", encoding="utf-8")
    intermediate_dir = project_dir / "中间产物"
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    segments = split_script(script, req.targetClipCount)
    storyboard_lines = [
        f"# {req.projectName}",
        "",
        f"- 目标段数：{len(segments)}",
        f"- 视觉风格：{req.style}",
        "",
    ]
    for index, segment in enumerate(segments, start=1):
        label = f"Clip{index:03d}"
        prompt = build_prompt(label=label, segment=segment, style=req.style)
        (project_dir / f"视频_{label}.prompt.txt").write_text(prompt, encoding="utf-8")
        storyboard_lines.extend([f"## {label}", "", segment, ""])

    (intermediate_dir / "分镜.md").write_text("\n".join(storyboard_lines), encoding="utf-8")
    (intermediate_dir / "制作说明.md").write_text(
        "此目录由 Changdu Web 制作台从剧本文本生成。\n"
        "请在生成前检查每个 prompt 的角色锚定、场景描述、对白和范围边界。\n",
        encoding="utf-8",
    )
    return scan_project(project_dir)


def split_script(script: str, target_count: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", script) if p.strip()]
    if not paragraphs:
        paragraphs = [script.strip()]
    if len(paragraphs) >= target_count:
        buckets = [[] for _ in range(target_count)]
        for index, para in enumerate(paragraphs):
            bucket_index = min(target_count - 1, index * target_count // len(paragraphs))
            buckets[bucket_index].append(para)
        return ["\n\n".join(bucket).strip() for bucket in buckets if bucket]

    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?])", script) if s.strip()]
    if len(sentences) <= 1:
        return paragraphs
    count = min(target_count, len(sentences))
    buckets = [[] for _ in range(count)]
    for index, sentence in enumerate(sentences):
        bucket_index = min(count - 1, index * count // len(sentences))
        buckets[bucket_index].append(sentence)
    return ["".join(bucket).strip() for bucket in buckets if bucket]


def build_prompt(*, label: str, segment: str, style: str) -> str:
    clean = " ".join(segment.split())
    return (
        f"{label}。\n"
        f"根据本段剧本生成一个连贯短视频片段：{clean}\n"
        "画面应明确交代主体、场景、动作、情绪和镜头顺序。"
        "角色外貌、服装、道具和空间关系保持稳定；动作之间使用自然过渡，不使用精确时间轴。\n"
        "本段仅展示上述剧情，不提前展示后续剧情。\n"
        f"{style}风格，高清细节丰富，电影质感，色彩自然，光影柔和。\n"
        "面部稳定不变形，五官清晰，人体结构正常，动作自然流畅。\n"
        "保持无字幕，避免画面生成字幕，不要水印，不要logo，不要BGM。\n"
    )


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.strip(), flags=re.UNICODE)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned[:40] or "project"
