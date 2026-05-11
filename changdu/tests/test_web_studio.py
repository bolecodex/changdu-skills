from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from changdu.web.app import create_app
from changdu.web.jobs import JobManager, build_concat_command, build_generate_command
from changdu.web.projects import create_project_from_script, safe_resolve, scan_project
from changdu.web.schemas import ConcatRequest, GenerateRequest, ScriptProjectRequest


def test_scan_project_detects_prompts_clips_and_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prompt_dir = tmp_path / "EP001"
    prompt_dir.mkdir()
    (prompt_dir / "视频_Clip001.prompt.txt").write_text("clip 1", encoding="utf-8")
    (prompt_dir / "视频_Clip002.prompt.txt").write_text("clip 2", encoding="utf-8")
    (prompt_dir / "视频_Clip001.mp4").write_bytes(b"fake")
    (prompt_dir / "视频_Clip001.lastframe.jpg").write_bytes(b"fake")

    project = scan_project("EP001")

    assert project.promptDir == str(prompt_dir)
    assert [clip.label for clip in project.clips] == ["Clip001", "Clip002"]
    assert project.clips[0].status == "done"
    assert project.clips[1].status == "ready"
    assert {artifact.name for artifact in project.artifacts} >= {
        "视频_Clip001.mp4",
        "视频_Clip001.lastframe.jpg",
    }


def test_safe_resolve_rejects_paths_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("nope", encoding="utf-8")

    with pytest.raises(ValueError, match="outside workspace"):
        safe_resolve(outside)


def test_create_project_from_script_writes_intermediate_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    project = create_project_from_script(
        ScriptProjectRequest(
            projectName="测试短剧",
            script="第一场，女主走进会议室。\n\n第二场，男主递出合同。\n\n第三场，两人对峙。",
            outputRoot="outputs/web-projects",
            targetClipCount=3,
            style="都市写实",
        )
    )

    root = Path(project.promptDir)
    assert (root / "剧本.txt").exists()
    assert (root / "中间产物" / "分镜.md").exists()
    assert [clip.label for clip in project.clips] == ["Clip001", "Clip002", "Clip003"]
    assert "都市写实风格" in (root / "视频_Clip001.prompt.txt").read_text(encoding="utf-8")
    assert {artifact.name for artifact in project.artifacts} >= {
        "剧本.txt",
        "中间产物/分镜.md",
        "视频_Clip001.prompt.txt",
    }


def test_build_generate_command_maps_request_to_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prompt_dir = tmp_path / "EP001"
    image = tmp_path / "char.jpg"
    prompt_dir.mkdir()
    image.write_bytes(b"fake")

    cmd = build_generate_command(
        GenerateRequest(
            promptDir="EP001",
            outputDir="EP001",
            images=["char.jpg"],
            assets=["asset-123"],
            ratio="9:16",
            duration=10,
            quality="720p",
            continuityMode="auto",
            prevTailSeconds=4.5,
            voiceAsset="asset-voice",
            noAudio=True,
            promptHeader="图片1是主角。",
        )
    )

    assert "sequential-generate" in cmd
    assert cmd[cmd.index("--prompt-dir") + 1] == str(prompt_dir)
    assert cmd[cmd.index("--image") + 1] == str(image)
    assert cmd[cmd.index("--asset") + 1] == "asset-123"
    assert cmd[cmd.index("--ratio") + 1] == "9:16"
    assert cmd[cmd.index("--duration") + 1] == "10"
    assert "--no-audio" in cmd
    assert cmd[cmd.index("--prompt-header") + 1] == "图片1是主角。"


def test_build_concat_command_maps_request_to_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    input_dir = tmp_path / "EP001"
    input_dir.mkdir()

    cmd = build_concat_command(
        ConcatRequest(
            inputDir="EP001",
            output="outputs/final.mp4",
            trimTail=0.2,
            crossfadeSeconds=0.4,
            normalizeAudio=True,
            stripAudio=False,
            audioFadein=0.3,
        )
    )

    assert "clip-concat" in cmd
    assert cmd[cmd.index("--input-dir") + 1] == str(input_dir)
    assert cmd[cmd.index("--output") + 1] == str(tmp_path / "outputs" / "final.mp4")
    assert "--normalize-audio" in cmd
    assert "--no-strip-audio" in cmd


def test_job_manager_lifecycle_and_logs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def run_job():
        manager = JobManager(root=tmp_path / "runs")
        job = manager.create("clip-concat", [sys.executable, "-c", "print('hello web')"])
        for _ in range(40):
            current = manager.get(job.id)
            if current.status in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.05)
        current = manager.get(job.id)
        logs, next_offset = manager.read_logs(job.id)
        return current, logs, next_offset

    job, logs, next_offset = asyncio.run(run_job())
    assert job.status == "succeeded"
    assert job.exitCode == 0
    assert "hello web" in logs
    assert next_offset > 0


def test_api_prompt_roundtrip_and_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prompt_dir = tmp_path / "EP001"
    prompt_dir.mkdir()
    (prompt_dir / "视频_Clip001.prompt.txt").write_text("old", encoding="utf-8")
    (prompt_dir / "视频_Clip001.mp4").write_bytes(b"fake")

    client = TestClient(create_app(JobManager(root=tmp_path / "runs")))
    project = client.get("/api/projects", params={"root": "EP001"}).json()

    body = client.get(f"/api/prompts/{project['id']}/Clip001").json()
    assert body["text"] == "old"

    response = client.put(f"/api/prompts/{project['id']}/Clip001", json={"text": "new"})
    assert response.status_code == 200
    assert (prompt_dir / "视频_Clip001.prompt.txt").read_text(encoding="utf-8") == "new"

    artifacts = client.get("/api/artifacts", params={"project_id": project["id"]}).json()["artifacts"]
    assert artifacts[0]["kind"] == "video"


def test_api_create_project_from_script(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(create_app(JobManager(root=tmp_path / "runs")))

    response = client.post(
        "/api/projects/from-script",
        json={
            "projectName": "通用入口",
            "script": "开场，主角站在雨夜街头。随后，电话响起。",
            "outputRoot": "outputs/web-projects",
            "targetClipCount": 2,
            "style": "悬疑写实",
        },
    )

    assert response.status_code == 200
    project = response.json()
    assert len(project["clips"]) == 2
    assert Path(project["promptDir"]).exists()
