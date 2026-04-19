---
name: generate-video-by-seedance
description: 使用 changdu CLI 调用 Seedance 2.0 生成视频（文生 / 图生 / 多模态参考：图+视频+音频）。
homepage: https://www.volcengine.com/product/ark
metadata: {}
---

# Seedance 视频生成（统一走 changdu）

本技能统一使用 `changdu` CLI，不再调用独立脚本。Seedance 2.0 reference-to-video 模型一次请求最多可混传 9 张图 + 3 段视频（≤15s）+ 3 段音频（≤15s），是消除穿帮和音色漂移的关键能力。

## 前置条件

```bash
test -n "$CHANGDU_ARK_API_KEY" || test -n "$ARK_API_KEY"
```

可选视频端点（在火山方舟控制台创建后设置）：

```bash
export CHANGDU_SEEDANCE_ENDPOINT="你的视频端点ID"
```

传入本地视频/音频做参考时还需配置 TOS：

```bash
export VOLC_ACCESSKEY="..."
export VOLC_SECRETKEY="..."
export CHANGDU_TOS_BUCKET="..."
```

## 文生视频

```bash
changdu text2video \
  --prompt "电影感夜景街道，镜头缓慢推进" \
  --ratio 16:9 \
  --duration 15
```

## 多模态参考生视频（推荐）

图 + 视频 + 音频三类参考混传：

```bash
changdu multimodal2video \
  --image "/path/to/角色1.jpg" \
  --image "/path/to/角色2.jpg" \
  --image "/path/to/场景.jpg" \
  --ref-video "./单集制作/EP001/视频_Clip003.mp4" \
  --voice-asset asset-xxxxxxxx \
  --prompt "图1为角色A，图2为角色B，图3为场景。视频1 是上一段尾段，仅做妆造与位置参考。音轨1 锁音色。$(cat 视频_Clip004.prompt.txt)" \
  --ratio 16:9 --duration 15 \
  --wait --output "视频_Clip004.mp4"
```

## 查询任务状态

```bash
changdu query_result --submit_id <任务ID>
```

等待并下载：

```bash
changdu query_result --submit_id <任务ID> --wait --output "视频_Clip001.mp4"
```

## 常用参数

| 参数 | 说明 |
|------|------|
| `--model` | 临时覆盖视频模型/端点 ID |
| `--ratio` | 画面比例（`16:9` / `9:16` / `1:1`） |
| `--duration` | 视频时长（秒） |
| `--wait` | 提交后等待到终态 |
| `--output` | 等待成功后保存路径 |
| `--return-last-frame` | 返回尾帧 URL 用于首帧链衔接 |
| `--first-frame-url` | 指定首帧 URL（来自上一段尾帧） |
| `--last-frame-url` | 指定尾帧 URL（首尾帧驱动） |
| `--ref-video <path/url/asset>` | 参考视频（≤3，每段 ≤15s）；本地文件自动 TOS 上传 |
| `--ref-audio <path/url/asset>` | 参考音频（≤3，每段 ≤15s） |
| `--voice-asset <asset-id>` | `--ref-audio` 的语义化别名 |
| `--no-audio` | 禁用同步音频生成 |
| `--quality 480p/720p/1080p` | 指定输出分辨率 |
| `--asset` | Asset ID（图/视频/音频通用，自动转 `asset://`） |

## 连续生成（推荐：ref_video + voice_asset）

```bash
changdu sequential-generate \
  --prompt-dir ./单集制作/EP001/ \
  --asset <角色三视图ID> --asset <场景ID> \
  --continuity-mode ref_video \
  --voice-asset asset-xxxxxxxx \
  --prev-tail-seconds 5 \
  --ratio 16:9 --duration 15 \
  --prompt-header "图片1是女主三视图，图片2是场景。视频1 是前段尾段，仅做妆造参考。音轨1 锁音色。"
```

## 约束

- 多图参考的顺序必须与 prompt 中"图1/图2/图3"描述一致。
- 若传 `--ref-video` 必须在 prompt 中加【视频参考说明】块，自然语言告知模型该视频的语义角色，避免内容串流。
- 若传 `--ref-audio` / `--voice-asset` 且本段含台词，必须加【音色锚定】块。
- 若追求角色一致性，建议固定角色参考图（建议传"角色三视图"）并复用同一视频端点。
- 单次请求最多 9 图 + 3 视频 + 3 音频；图 < 30MB / 视频 < 50MB / 音频 < 15MB。

## 已知 API 限制（实测踩坑）

- **首尾帧与参考媒体互斥**：`--first-frame-url` / `--last-frame-url` **不能** 与 `--image` / `--asset (Image)` / `--ref-video` / `--ref-audio` / `--voice-asset` 同时使用。API 会返回：
  > `first/last frame content cannot be mixed with reference media content`

  `VideoGenerateRequest.to_api_payload` 会在客户端就抛 `ValueError` 拦截，不浪费 ARK 调用费。需要既"延续上一段画面"又"锁角色三视图"时，**优先用 `--ref-video`**（参考媒体模式），不要再传 `--first-frame-url`。
- **生成出来的真人画面再次喂回去做 `--ref-video` 偶尔被审核挡掉**：错误是 `The request failed because the input video may contain real person`。这是 ARK 的安全策略，命中是随机的。`sequential-generate --continuity-mode auto` 已内置自动 fallback：被拒后会清空 reference_image / reference_video / reference_audio，改用 `--first-frame-url`（前段尾帧）模式重试。
- **音色 asset 入库对 MP3 不友好**：Ark Asset Service 偶尔对 MP3 报 `InvalidParameter.FormatUnsupported`。`sequential-generate --voice-from-clip N` 与 `voice-asset-from-clip` 都已实现三层 fallback：先尝试 wav，再尝试 mp3，最终 fallback 到直接用 TOS URL 做 `reference_audio`（不入库），保证音色锁定不会被这个限制中断。
- **真人审核是连贯性 demo 的最大杀手**：`ref_video` 链路一旦被 `may contain real person` 挡下来，整段 fallback 到 `first_frame_url`，画面会从"延续动作"退化为"从一帧重新开始"，连贯性立刻塌一半。规避方案：
  1. **首选 anime / cel-shaded 风格**：动漫/卡通几乎不触发该规则，6 段武打都能走 `ref_video` 链路保持首尾相接。具体写法见 [`anime-action-scene/SKILL.md`](../anime-action-scene/SKILL.md)。
  2. **写实戏接受少量 fallback**：写实人物题材建议把 `--continuity-mode` 设为 `auto` 而不是 `ref_video`，单段 fallback 不致命；多段 fallback 时考虑改写成动漫风重跑。
  3. **三视图永远传**：哪怕走 fallback 模式，仍要保留 `--image <三视图>` 让 ref_image 锁角色（`auto` 模式 fallback 时会清掉 ref_image，所以**首段一定要把三视图加进去并依靠 first 段的画面带住后续段**）。
