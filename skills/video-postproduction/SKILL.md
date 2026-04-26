---
name: video-postproduction
description: 多段视频拼接的后期工艺指南——audio-fadein（消除 Seedance 启动底噪）、crossfade（视频/音频淡变）、loudnorm（音量归一化）。当用户拼完多个 clip 但效果不连贯（音量跳、画面跳、底噪嗡嗡声）时调用，对应 changdu clip-concat 命令。
tags: ["postproduction", "ffmpeg", "crossfade", "loudnorm", "audio-fadein"]
---

# 多段视频后期工艺 · changdu 命令对照

## 何时调用

- Seedance 生成的视频有**每段开头嗡嗡底噪** → `--audio-fadein 0.3`（推荐默认开启，保留原声的同时消除启动噪声）
- 拼接结果有**段间画面硬切** → `--crossfade-seconds 0.3-0.6`
- 拼接结果有**段间音量跳变** → `--normalize-audio`（loudnorm）

> **关于 Seedance 音频的说明**：Seedance 2.0 生成的音频包含角色台词、音效和环境音，是短剧的重要组成部分，默认应当保留。每段开头可能存在启动底噪（嗡嗡声），使用 `--audio-fadein 0.3` 对每段音频开头做 0.3 秒淡入即可消除，无需丢弃整个音轨。仅在明确不需要原声（如后期全量配音配乐）时才使用 `--strip-audio`。

---

## 3 个核心后期工艺

### 1. Audio Fade-in（消除启动底噪，推荐默认）

**问题**：Seedance 2.0 生成的音频轨在每段开头可能带有启动底噪，拼接后在衔接处尤为明显。

**changdu 命令**：

```bash
changdu clip-concat \
  --input-dir ./clips \
  --output ./final.mp4 \
  --audio-fadein 0.3
```

**ffmpeg 实现**：`afade=t=in:st=0:d=0.3`（对每段音频开头做 0.3 秒淡入，消除底噪同时保留台词和音效）

### 1b. Strip Audio（完全去除音频，仅在后期全量配音时使用）

**changdu 命令**：

```bash
changdu clip-concat \
  --input-dir ./clips \
  --output ./final.mp4 \
  --strip-audio
```

**ffmpeg 实现**：`-an -c:v copy`（移除音频流，视频流 stream copy）

### 2. 视频 crossfade（xfade）

**问题**：两个 clip 直接拼接时，画面会在切换瞬间硬切，大脑感知为"剪辑痕迹"。

**原理**：在前段最后 N 秒和后段开头 N 秒做透明度渐变（fade transition），人眼感知为"自然过渡"。

**ffmpeg 实现**：

```
[v0][v1]xfade=transition=fade:duration=0.4:offset=4.6[vout]
```

`offset` = 前段时长 - duration。多段时累加。

**changdu 命令**：

```bash
changdu clip-concat \
  --input-dir ./clips \
  --output ./final.mp4 \
  --crossfade-seconds 0.4
```

**经验值**：

- 武打/快节奏：0.3-0.4s（再长会糊掉动作）
- 抒情/慢节奏：0.5-0.8s
- 完全硬切（特殊风格）：保留 0.0（默认走 stream copy）

### 3. loudnorm（音量归一化）

**问题**：每段 Seedance 生成的 clip 有自己的"基准响度"，拼起来可能 C2 突然大声、C4 突然小声。

**原理**：EBU R128 / ITU BS.1770 响度标准，把整段音轨调整到目标响度（默认 -16 LUFS，平台友好），并限峰 -1.5 dBTP。

**changdu 命令**：

```bash
changdu clip-concat ... --normalize-audio
```

**注意事项**：

- loudnorm 会**轻微降低动态范围**（响段更小、静段更大）
- 推荐：拼接 ≥3 段时**默认开**
- 与 `--strip-audio` 互斥（去掉音频后无需归一化）
- 可与 `--audio-fadein` 同时使用

---

## 命令使用矩阵

| 场景 | 推荐 | 命令 |
|---|---|---|
| 保留原声去底噪（推荐默认） | ⭐**默认** | `changdu clip-concat -d clips -o final.mp4 --audio-fadein 0.3` |
| 保留原声 + crossfade + loudnorm | 多段音量不一致时 | `changdu clip-concat -d clips -o final.mp4 --audio-fadein 0.3 --crossfade-seconds 0.4 --normalize-audio` |
| 仅去段间音量跳变 | 偶用 | `changdu clip-concat -d clips -o final.mp4 --normalize-audio` |
| 仅做 crossfade | 偶用 | `changdu clip-concat -d clips -o final.mp4 --crossfade-seconds 0.4` |
| 完全去除音频（后期配音） | 后期全量配音时 | `changdu clip-concat -d clips -o final.mp4 --strip-audio` |
| 默认快速拼接（stream copy） | 调试 | `changdu clip-concat -d clips -o final.mp4` |
| 单独叠加 BGM | 确实需要氛围音乐时 | `changdu clip-add-bgm -i final.mp4 --bgm bgm.mp3 -o final_with_bgm.mp4 --bgm-volume 0.22 --bgm-ducking --normalize-audio` |

---

## 后期参数推荐表

| 内容类型 | audio-fadein | strip-audio | crossfade | loudnorm |
|---|---|---|---|---|
| 写实剧情 / 对话戏 | ⭐ 0.3s | 关 | — | 推荐开 |
| 动漫武打 / 追逐 | 0.3s | 关 | — | — |
| 后期全量配音配乐 | — | 开 | — | — |

---

## 常见问题排查

### Q1: ffmpeg 报 "Unknown encoder 'libx264'"

`brew install ffmpeg` 默认带 libx264。如用静态 build，确认下载的是 "full" 版本（包含 libx264 + libx265 + aac）。

### Q2: 拼完后段切换处仍有 0.1s 黑帧

`xfade` 的 transition 类型可换：`fade`（默认，最自然）、`fadeblack`（强调切割）、`smoothleft`（横向滑动）。当前 changdu 固定 `fade`。

### Q3: 每段衔接处有嗡嗡底噪

使用 `--audio-fadein 0.3` 对每段音频开头做淡入处理，可消除 Seedance 2.0 的启动底噪，同时保留台词和音效。仅在后期需要全量配音配乐时才使用 `--strip-audio` 完全去除音频。

---

## 与其他 skills 的关系

- 上游：[`anime-action-scene`](../anime-action-scene/SKILL.md) / [`storyboard-to-seedance-prompt`](../storyboard-to-seedance-prompt/SKILL.md) 产出多段 clip 后调用本 skill
- 旁路：[`ffmpeg-video-processing`](../ffmpeg-video-processing/SKILL.md) 通用 ffmpeg 命令参考
- 配套 CLI：`changdu clip-concat`、`changdu clip-add-bgm`、`changdu clip-trim`
