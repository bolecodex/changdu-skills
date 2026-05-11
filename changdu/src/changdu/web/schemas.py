"""Pydantic schemas for the local web studio."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "succeeded", "failed"]


class Artifact(BaseModel):
    name: str
    path: str
    kind: Literal["video", "image", "text", "other"]
    url: str | None = None


class Clip(BaseModel):
    index: int
    label: str
    promptPath: str
    videoPath: str | None = None
    lastFramePath: str | None = None
    status: Literal["missing", "ready", "done"] = "missing"


class Project(BaseModel):
    id: str
    root: str
    promptDir: str
    outputDir: str
    clips: list[Clip]
    artifacts: list[Artifact]


class ScriptProjectRequest(BaseModel):
    projectName: str = "未命名短剧"
    script: str
    outputRoot: str = "outputs/web-projects"
    targetClipCount: int = Field(default=6, ge=1, le=30)
    style: str = "电影写实"


class GenerateRequest(BaseModel):
    promptDir: str
    outputDir: str | None = None
    images: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    ratio: str = "16:9"
    duration: int = 15
    quality: str | None = None
    continuityMode: Literal["first_frame", "ref_video", "auto"] = "auto"
    prevTailSeconds: float = 5.0
    voiceAsset: str | None = None
    voiceFromClip: int | None = None
    voiceGroupId: str | None = None
    noAudio: bool = False
    promptHeader: str = ""


class ConcatRequest(BaseModel):
    inputDir: str
    output: str
    trimTail: float = 0.0
    crossfadeSeconds: float = 0.0
    normalizeAudio: bool = False
    stripAudio: bool = False
    audioFadein: float = 0.0


class PromptCheckRequest(BaseModel):
    promptDir: str | None = None
    input: str | None = None
    style: str = "电影写实"


class PromptBody(BaseModel):
    text: str


class Job(BaseModel):
    id: str
    type: Literal["sequential-generate", "clip-concat"]
    status: JobStatus
    commandPreview: str
    createdAt: str
    startedAt: str | None = None
    finishedAt: str | None = None
    exitCode: int | None = None
    error: str | None = None
