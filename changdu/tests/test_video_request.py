"""Tests for VideoGenerateRequest.to_api_payload covering Seedance 2.0
multimodal capabilities (text + image + video + audio + first/last frame +
generate_audio + quality + return_last_frame).
"""

from __future__ import annotations

import pytest

from changdu.models.requests import VideoGenerateRequest


MODEL = "doubao-seedance-2-0-260128"


def _build(**kwargs):
    return VideoGenerateRequest(model=MODEL, **kwargs).to_api_payload()


def _content_by_role(payload: dict, role: str) -> list[dict]:
    return [c for c in payload["content"] if c.get("role") == role]


def test_text_only_payload():
    payload = _build(prompt="电影感夜景街道")
    assert payload["model"] == MODEL
    assert payload["ratio"] == "16:9"
    assert payload["duration"] == 15
    assert payload["watermark"] is False
    text_nodes = [c for c in payload["content"] if c["type"] == "text"]
    assert len(text_nodes) == 1
    assert text_nodes[0]["text"] == "电影感夜景街道"
    assert "generate_audio" not in payload
    assert "quality" not in payload
    assert "return_last_frame" not in payload


def test_first_frame_and_reference_media_are_mutually_exclusive():
    """Seedance API explicitly rejects mixing first/last frame with
    reference_image/reference_video/reference_audio
    ("first/last frame content cannot be mixed with reference media content").
    The model layer must fail fast with ValueError so we never spend an
    ARK call on a guaranteed-failing payload.
    """

    with pytest.raises(ValueError, match="first_frame"):
        _build(
            prompt="女主转身",
            first_frame_url="https://cdn.example.com/last.jpg",
            images=["https://cdn.example.com/char.jpg"],
        )

    with pytest.raises(ValueError, match="reference"):
        _build(
            prompt="女主走近",
            first_frame_url="https://cdn.example.com/first.jpg",
            videos=["https://cdn.example.com/tail.mp4"],
        )

    with pytest.raises(ValueError, match="reference"):
        _build(
            prompt="女主低声说",
            last_frame_url="https://cdn.example.com/last.jpg",
            audios=["asset://voice"],
        )


def test_frame_only_mode_is_allowed():
    """Pure first/last frame mode (no reference media) is the supported way
    to chain via frames; the payload should still be emitted cleanly.
    """

    payload = _build(
        prompt="女主转身",
        first_frame_url="https://cdn.example.com/first.jpg",
        last_frame_url="https://cdn.example.com/last.jpg",
    )
    first_frames = _content_by_role(payload, "first_frame")
    last_frames = _content_by_role(payload, "last_frame")
    assert len(first_frames) == 1 and len(last_frames) == 1
    assert _content_by_role(payload, "reference_image") == []
    assert _content_by_role(payload, "reference_video") == []
    assert _content_by_role(payload, "reference_audio") == []


def test_last_frame_url_emitted_with_role():
    payload = _build(
        prompt="女主走入门",
        last_frame_url="https://cdn.example.com/last.jpg",
    )
    last_frames = _content_by_role(payload, "last_frame")
    assert len(last_frames) == 1
    assert last_frames[0]["image_url"]["url"] == "https://cdn.example.com/last.jpg"


def test_multimodal_image_video_audio_payload():
    payload = _build(
        prompt="女主低声说",
        images=["asset://asset-char", "asset://asset-scene"],
        videos=["https://cdn.example.com/clip1_tail.mp4"],
        audios=["asset://asset-voice-v1"],
        return_last_frame=True,
    )
    refs = _content_by_role(payload, "reference_image")
    vids = _content_by_role(payload, "reference_video")
    auds = _content_by_role(payload, "reference_audio")

    assert len(refs) == 2
    assert refs[0]["image_url"]["url"] == "asset://asset-char"

    assert len(vids) == 1
    assert vids[0]["type"] == "video_url"
    assert vids[0]["video_url"]["url"] == "https://cdn.example.com/clip1_tail.mp4"

    assert len(auds) == 1
    assert auds[0]["type"] == "audio_url"
    assert auds[0]["audio_url"]["url"] == "asset://asset-voice-v1"

    assert payload["return_last_frame"] is True


def test_quality_and_no_audio_flags():
    payload = _build(prompt="夜景", quality="1080p", generate_audio=False)
    assert payload["quality"] == "1080p"
    assert payload["generate_audio"] is False


def test_generate_audio_default_not_emitted():
    """generate_audio=True (default) should NOT appear in payload, to keep
    backward compatibility with endpoints that don't recognise the flag.
    """

    payload = _build(prompt="夜景")
    assert "generate_audio" not in payload


def test_quality_default_not_emitted():
    payload = _build(prompt="夜景")
    assert "quality" not in payload


def test_max_three_videos_three_audios_supported():
    """Seedance 2.0 spec allows up to 3 videos and 3 audios; the model layer
    must emit all of them in order.
    """

    payload = _build(
        prompt="混传",
        videos=[
            "https://cdn.example.com/v1.mp4",
            "https://cdn.example.com/v2.mp4",
            "https://cdn.example.com/v3.mp4",
        ],
        audios=[
            "asset://a1",
            "asset://a2",
            "asset://a3",
        ],
    )
    vids = _content_by_role(payload, "reference_video")
    auds = _content_by_role(payload, "reference_audio")
    assert [v["video_url"]["url"] for v in vids] == [
        "https://cdn.example.com/v1.mp4",
        "https://cdn.example.com/v2.mp4",
        "https://cdn.example.com/v3.mp4",
    ]
    assert [a["audio_url"]["url"] for a in auds] == ["asset://a1", "asset://a2", "asset://a3"]


def test_text_node_skipped_when_prompt_blank():
    payload = _build(prompt="   ", images=["asset://x"])
    assert all(c["type"] != "text" for c in payload["content"])
    assert _content_by_role(payload, "reference_image")[0]["image_url"]["url"] == "asset://x"


def test_reference_combo_keeps_role_order_text_then_images_videos_audios():
    """Reference-media mode with all three reference types together keeps
    a deterministic emit order: text first, then reference_image,
    reference_video, reference_audio.
    """

    payload = _build(
        prompt="完整组合",
        images=["asset://char"],
        videos=["https://x/tail.mp4"],
        audios=["asset://voice"],
    )
    types_seq = [(c["type"], c.get("role")) for c in payload["content"]]
    assert types_seq[0] == ("text", None)
    assert ("image_url", "reference_image") in types_seq
    assert ("video_url", "reference_video") in types_seq
    assert ("audio_url", "reference_audio") in types_seq
    img_idx = types_seq.index(("image_url", "reference_image"))
    vid_idx = types_seq.index(("video_url", "reference_video"))
    aud_idx = types_seq.index(("audio_url", "reference_audio"))
    assert img_idx < vid_idx < aud_idx
