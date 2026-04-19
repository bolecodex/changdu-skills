"""Tests for the upgraded ``clip-concat`` pipeline helper.

We test the pure ``_build_concat_filter_complex`` helper directly to avoid
shelling out to ``ffmpeg``; ffmpeg invocation is covered by manual end-to-end
runs (see ``examples/run_30s_anime_action.sh``).
"""

from __future__ import annotations

import pytest

from changdu.commands.compat import _build_concat_filter_complex


def test_single_clip_no_advanced_options_returns_passthrough():
    fc, vlabel, alabel, total = _build_concat_filter_complex([8.0])
    assert fc == ""
    assert vlabel == "[0:v]"
    assert alabel == "[0:a]"
    assert total == pytest.approx(8.0)


def test_six_clips_with_crossfade_emits_xfade_chain_and_acrossfade_chain():
    durations = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
    fc, vlabel, alabel, total = _build_concat_filter_complex(
        durations, crossfade=0.4
    )
    assert "xfade=transition=fade:duration=0.400" in fc
    assert "acrossfade=d=0.400:c1=tri:c2=tri" in fc
    assert fc.count("xfade=transition=fade") == 5
    assert fc.count("acrossfade=") == 5
    assert vlabel == "[v05]"
    assert alabel == "[a05]"
    assert total == pytest.approx(6 * 5.0 - 5 * 0.4)


def test_crossfade_offsets_are_cumulative():
    """Each xfade offset must equal sum(prev durations) - i*crossfade so
    the transitions land exactly on the tail of the previous clip.
    """

    fc, _, _, _ = _build_concat_filter_complex(
        [4.0, 6.0, 5.0], crossfade=0.5
    )
    assert "xfade=transition=fade:duration=0.500:offset=3.500" in fc
    assert "xfade=transition=fade:duration=0.500:offset=9.000" in fc


def test_no_crossfade_with_advanced_options_uses_concat_filter():
    fc, vlabel, alabel, _ = _build_concat_filter_complex(
        [5.0, 5.0], crossfade=0.0, normalize_audio=True
    )
    assert "concat=n=2:v=1:a=1" in fc
    assert "loudnorm=I=-16:LRA=11:TP=-1.5" in fc
    assert vlabel == "[vcat]"
    assert alabel == "[anorm]"


def test_loudnorm_appended_after_concat_or_xfade():
    fc, _, alabel, _ = _build_concat_filter_complex(
        [5.0, 5.0], crossfade=0.4, normalize_audio=True
    )
    assert "loudnorm" in fc
    assert alabel == "[anorm]"


def test_bgm_with_ducking_emits_split_sidechain_amix():
    fc, _, alabel, total = _build_concat_filter_complex(
        [5.0, 5.0],
        crossfade=0.4,
        normalize_audio=True,
        bgm_enabled=True,
        bgm_volume=0.28,
        bgm_ducking=True,
        bgm_fadein=1.5,
        bgm_fadeout=2.0,
    )
    assert "asplit=2[amain][asc]" in fc
    assert "volume=0.280" in fc
    assert "afade=t=in:st=0:d=1.500" in fc
    fade_out_start = total - 2.0
    assert f"afade=t=out:st={fade_out_start:.3f}:d=2.000" in fc
    assert "sidechaincompress=threshold=0.05:ratio=8" in fc
    assert "amix=inputs=2:duration=first" in fc
    assert alabel == "[afinal]"


def test_bgm_without_ducking_skips_sidechaincompress():
    fc, _, alabel, _ = _build_concat_filter_complex(
        [5.0, 5.0],
        crossfade=0.4,
        bgm_enabled=True,
        bgm_volume=0.30,
        bgm_ducking=False,
    )
    assert "sidechaincompress" not in fc
    assert "amix=inputs=2:duration=first" in fc
    assert alabel == "[afinal]"


def test_bgm_input_index_matches_clip_count():
    """BGM must always be appended as the (n+1)-th input so the filter
    references match the ``-i`` order in the ffmpeg command line.
    """

    fc, _, _, _ = _build_concat_filter_complex(
        [5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
        crossfade=0.4,
        bgm_enabled=True,
    )
    assert "[6:a]volume=" in fc


def test_zero_durations_raises():
    with pytest.raises(ValueError):
        _build_concat_filter_complex([])


def test_single_clip_with_bgm_still_works():
    """Used by ``clip-add-bgm``: one clip + one BGM, no crossfade."""

    fc, vlabel, alabel, total = _build_concat_filter_complex(
        [12.5],
        bgm_enabled=True,
        bgm_volume=0.25,
        bgm_ducking=True,
    )
    assert vlabel == "[0:v]"
    assert alabel == "[afinal]"
    assert "[1:a]volume=0.250" in fc
    assert total == pytest.approx(12.5)
