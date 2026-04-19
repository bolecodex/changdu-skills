---
name: jimeng-skill
description: 统一使用 changdu CLI 调用火山方舟 Seedream / Seedance，实现即梦同类图像与视频生成能力。
---

# changdu 统一生成技能

## 目标

- 生图与生视频统一走 `changdu` CLI。
- 默认能力：
  - 图像：Seedream
  - 视频：Seedance 2.0

## 前置条件

```bash
test -n "$CHANGDU_ARK_API_KEY" || test -n "$ARK_API_KEY"
```

可选端点（在火山方舟控制台获取，按需设置）：

```bash
export CHANGDU_SEED_TEXT_ENDPOINT="你的文本端点ID"
export CHANGDU_SEEDREAM_ENDPOINT="你的图像端点ID"
export CHANGDU_SEEDANCE_ENDPOINT="你的视频端点ID"
```

## 生图

文生图：

```bash
changdu text2image \
  --prompt "你的提示词，明确比例和画风" \
  --resolution_type 2k \
  --output "输出.jpg"
```

图生图：

```bash
changdu image2image \
  --image "/path/to/a.jpg" \
  --image "/path/to/b.jpg" \
  --prompt "将图1风格调整为图2风格" \
  --resolution_type 2k \
  --output "结果.jpg"
```

## 生视频

文生视频：

```bash
changdu text2video \
  --prompt "电影感夜景街道，16:9" \
  --ratio 16:9 \
  --duration 15
```

多模态参考生视频（图 + 视频 + 音频，三类一起喂）：

```bash
HEAD="图1是女主三视图，图2是场景。视频1 是上一段尾段，仅做妆造与位置参考。音轨1 锁音色。"
changdu multimodal2video \
  --image "./角色/女主_三视图.jpg" \
  --image "./场景/场景.jpg" \
  --ref-video "./单集制作/EP001/视频_Clip003.mp4" \
  --voice-asset asset-xxxxxxxx \
  --prompt "${HEAD}$(cat 视频_Clip004.prompt.txt)" \
  --ratio 16:9 \
  --duration 15 \
  --wait \
  --output "./单集制作/EP001/视频_Clip004.mp4"
```

新版关键参数（适用于 `text2video` / `image2video` / `multimodal2video` / `multiframe2video` / `clip-regen` / `clip-chain-regen` / `sequential-generate`）：

| 参数 | 说明 |
|------|------|
| `--ref-video <path/url/asset-id>` | 参考视频（最多 3 段，每段 ≤15s）。本地文件自动 TOS 上传。 |
| `--ref-audio <path/url/asset-id>` | 参考音频（最多 3 段，每段 ≤15s）。 |
| `--voice-asset <asset-id>` | `--ref-audio` 的语义化别名，专用于音色锁定。 |
| `--last-frame-url <url>` | 指定尾帧（首尾帧驱动）。 |
| `--no-audio` | 禁用同步音频生成。 |
| `--quality 480p/720p/1080p` | 指定输出分辨率。 |

连续生成 + 音色锁定的一键命令：

```bash
changdu sequential-generate \
  --prompt-dir ./单集制作/EP001/ \
  --asset <角色三视图ID> --asset <场景ID> \
  --continuity-mode ref_video \
  --voice-from-clip 1 --voice-group-id <主角素材组ID> \
  --ratio 16:9 --duration 15 \
  --prompt-header "图片1是女主三视图，图片2是场景。视频1 是前段尾段，仅做妆造参考。音轨1 锁音色。"
```

## 任务查询

```bash
changdu query_result --submit_id <任务ID>
changdu query_result --submit_id <任务ID> --wait --output "结果.mp4"
```

## 错误处理

- 鉴权失败：检查 `CHANGDU_ARK_API_KEY`。
- 端点无权限：检查对应 `CHANGDU_SEEDREAM_ENDPOINT` / `CHANGDU_SEEDANCE_ENDPOINT` 是否可用。
- 多图一致性差：固定参考图/视频/音频顺序，prompt 明确"图1/图2/视频1/音轨1"指代关系；MAKEUP/VOICE 类穿帮请配合 `--ref-video`+`--voice-asset` 双锚定。
- TOS 未配置：传入本地视频/音频做参考时需要 `VOLC_ACCESSKEY` / `VOLC_SECRETKEY` / `CHANGDU_TOS_BUCKET`。
