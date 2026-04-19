# changdu-skills

基于 `changdu` CLI 的 AI 图像/视频生成技能包。通过火山方舟 Ark API 调用 Seedream（图像）和 Seedance（视频）模型。

## 一键安装

```bash
npx skills add bolecodex/changdu-skills -y -g
```

安装完成后，skills 会被写入 `~/.agents/skills/`。

## 安装 changdu CLI

skills 依赖 `changdu` 命令行工具，安装方式：

```bash
# 方式一：直接从 GitHub 安装（推荐）
pip install "changdu @ git+https://github.com/bolecodex/changdu-skills.git#subdirectory=changdu"

# 方式二：克隆后本地安装
git clone https://github.com/bolecodex/changdu-skills.git
cd changdu-skills/changdu
pip install .
```

或者运行仓库自带的一键安装脚本：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/bolecodex/changdu-skills/main/scripts/setup.sh)
```

## 配置

```bash
export CHANGDU_ARK_API_KEY="你的火山方舟API Key"

# 可选：指定端点
export CHANGDU_SEEDREAM_ENDPOINT="ep-m-xxxxx"    # 图像端点
export CHANGDU_SEEDANCE_ENDPOINT="ep-m-xxxxx"    # 视频端点
```

## 快速体验

```bash
# 文生图
changdu text2image --prompt "江南水乡，青瓦白墙，水墨画风" --output 水乡.jpg

# 文生视频
changdu text2video --prompt "电影感夜景街道，霓虹灯倒映在湿润地面" --ratio 16:9 --duration 15

# 多模态参考生视频（图 + 视频 + 音频，三类一起喂）
changdu multimodal2video \
  --image 角色.jpg --image 场景.jpg \
  --ref-video ./单集制作/EP001/视频_Clip003.mp4 \
  --voice-asset asset-xxxxxxxx \
  --prompt "图1是主角，图2是场景。视频1 是上一段尾段，仅做妆造与位置参考。音轨1 锁音色。主角在场景中行走。" \
  --ratio 16:9 --duration 15 --wait --output clip004.mp4
```

## 端到端示例：3-clip 连贯生成 + 音色锁定

适用于把一段小说转成 3 段连贯短剧，演示如何同时消除"妆造漂移"和"音色漂移"两类穿帮：

```bash
# 0) 准备：素材组 + 角色三视图入库
changdu asset-group-create --name "示例-角色组"
changdu asset-create --file ./角色/女主_三视图.jpg --group-id <组ID> --type Image --name "女主-妆造"
changdu asset-create --file ./场景/会议室.jpg --group-id <组ID> --type Image --name "会议室"

# 1) 写好 3 个分镜 prompt 文件，预检
changdu prompt-optimize --dir ./单集制作/EP001/ --check

# 2) 单跑 Clip001 拿到一段"音色 + 妆造"基线
changdu multimodal2video \
  --asset <女主妆造ID> --asset <场景ID> \
  --prompt "图片1是女主三视图，图片2是场景。$(cat 单集制作/EP001/视频_Clip001.prompt.txt)" \
  --ratio 16:9 --duration 15 --return-last-frame --wait \
  --output ./单集制作/EP001/视频_Clip001.mp4

# 3) 从 Clip001 抽 6-12s 音色 → TOS → 入库 Audio Asset
changdu voice-asset-from-clip \
  --input ./单集制作/EP001/视频_Clip001.mp4 \
  --group-id <组ID> --start 6 --duration 8
# 输出：音色 Asset ID: asset-yyyyyyyy

# 4) 从 Clip002 起一键续做：默认 ref_video 衔接 + 音色复用
changdu sequential-generate \
  --prompt-dir ./单集制作/EP001/ \
  --asset <女主妆造ID> --asset <场景ID> \
  --continuity-mode ref_video \
  --voice-asset asset-yyyyyyyy \
  --prev-tail-seconds 5 \
  --ratio 16:9 --duration 15 \
  --prompt-header "图片1是女主三视图，图片2是场景。视频1 是前段尾段，仅作妆造参考。音轨1 锁音色。"

# 5) 拼接成片（保留音视频）
changdu clip-concat --input-dir ./单集制作/EP001/ --output ./单集制作/EP001/完整版.mp4
```

或者把 step 2-4 合并为一条命令（自动在第 1 段后入库音色，从第 2 段起复用）：

```bash
changdu sequential-generate \
  --prompt-dir ./单集制作/EP001/ \
  --asset <女主妆造ID> --asset <场景ID> \
  --continuity-mode ref_video \
  --voice-from-clip 1 --voice-group-id <组ID> \
  --voice-clip-start 6 --voice-clip-duration 8 \
  --ratio 16:9 --duration 15 \
  --prompt-header "图片1是女主三视图，图片2是场景。视频1 是前段尾段。音轨1 锁音色。"
```

> **生产环境推荐用 `--continuity-mode auto`**：先按 `ref_video` 提交，被 ARK 安全策略拒掉（"input video may contain real person"）时自动降级为 `--first-frame-url` 模式重试。这是实测中后段（Clip003+）偶发的真人审核命中场景。

### 实测约束（必读）

- **首尾帧 vs 参考媒体二选一**：Seedance API 拒绝同一请求里同时塞 `first_frame_url` / `last_frame_url` 与 `reference_image` / `reference_video` / `reference_audio`（错误 `first/last frame content cannot be mixed with reference media content`）。`changdu` 在 `VideoGenerateRequest.to_api_payload` 处客户端拦截并抛 `ValueError`，避免浪费调用费。
- **真人视频回灌偶发审核挡**：把上一段生成的真人视频做 `ref_video` 时，ARK 偶尔返回 `input video may contain real person`。`sequential-generate --continuity-mode auto` 已内置自动降级。
- **音色样本 MP3 入库可能被 Asset Service 拒**：`sequential-generate --voice-from-clip` 现在会先尝试 wav，再尝试 mp3，最终 fallback 到直接用 TOS URL 做 `reference_audio`，保证不阻塞主流程。

## 一键运行 demo

仓库自带两个开箱即跑的 demo：

### Demo A：3-clip 写实连贯生成（约 ¥3-6，6-10 分钟）

适合首次跑通整条链路，验证音色锁定与 `--continuity-mode auto` fallback。

```bash
cp .env.example .env  # 填入 CHANGDU_ARK_API_KEY、TOS bucket 等
./examples/run_3clip_demo.sh
```

产物在 `outputs/demo_3clip/` 下：
- `refs/char_lin_threeview.jpg` — 主角三视图
- `clips/视频_Clip00{1,2,3}.mp4` + `.lastframe.jpg` — 3 段成片与尾帧
- `_voices/voice_from_Clip001.{mp3,wav}` — 自动抽出的音色样本
- `_tails/视频_Clip00*_tail.mp4` — 自动抽出的衔接尾段
- `final.mp4` — 拼接成片（stream copy，无后期）

### Demo B：30s anime 武打 · S 级连贯性（约 ¥8-12，30-45 分钟）

6 段 × 5s 动漫风武打，**只用 Seedance 自动生成的人声 / 环境 / 打斗音**，后期只做 crossfade + loudnorm，不叠加任何外部 BGM。
解决 Demo A 暴露的"段间音频/画面割裂"问题。

```bash
cp .env.example .env
./examples/run_30s_anime_action.sh
```

产物在 `outputs/demo_anime_action/` 下：
- `refs/char_woman_swordsman_threeview.jpg` / `char_villain_assassin_threeview.jpg` / `scene_bamboo_snow_night.jpg` — anime 三视图与场景
- `clips/视频_Clip00{1..6}.mp4` — 6 段武打成片（每段都自带人声 + 环境音 + 打斗音）
- `_voices/voice_from_Clip001.wav` — C1 抽出的音色样本（C2-C6 通过 `reference_audio` 复用）
- `final.mp4` — 拼接成片（crossfade 0.4s + loudnorm，约 28s）

为什么不叠 BGM：实测合成 / 免费 BGM 与 anime 武打的氛围完全不搭（既盖住了 Seedance 自带的金属碰撞声，又稀释了人声），反而让段间割裂感更明显；只做 crossfade + loudnorm 后，段间衔接最自然。

为什么用动漫风：Seedance 对真人视频回喂 `ref_video` 偶尔触发 `may contain real person` 审核，动漫几乎不触发。详见 [`skills/anime-action-scene/SKILL.md`](skills/anime-action-scene/SKILL.md) 与 [`skills/video-postproduction/SKILL.md`](skills/video-postproduction/SKILL.md)。

### 后期叠 BGM（可选，仅在确实需要纯氛围片时用）

如需事后叠加自制 / 授权 BGM，不重跑视频也能单独加：

```bash
changdu clip-add-bgm \
  --input ./outputs/demo_anime_action/final.mp4 \
  --bgm ./your_bgm.mp3 \
  --output ./outputs/demo_anime_action/final_with_bgm.mp4 \
  --bgm-volume 0.22 --bgm-ducking --normalize-audio
```

注意：默认推荐**不加 BGM**，让 Seedance 自带的人声和打斗音保持原始张力。

## 包含的技能

| 技能 | 用途 |
|------|------|
| `jimeng-skill` | 统一生成入口（文生图/图生图/文生视频/多模态生视频） |
| `generate-image-by-seedream` | Seedream 图像生成 |
| `generate-video-by-seedance` | Seedance 2.0 视频生成（含 ref_video / ref_audio / voice_asset 多模态参考） |
| `asset-management` | 火山方舟素材资产库（图/视频/音频通用，含音色样本入库） |
| `novel-to-video` | 小说→影视视频全流程工作流（三锚定：图 + 视频 + 音频） |
| `text-storyboard` | 文字分镜创作 |
| `storyboard-to-seedance-prompt` | 分镜→视频提示词（含妆造/音色/视频参考 7 块约束） |
| `anime-action-scene` | 动漫武打短剧专项 prompt 与生成工作流（30s · 6 段 · S 级连贯性） |
| `video-postproduction` | 多段拼接后期：crossfade / loudnorm / BGM / sidechain ducking |
| `video-review` | 视频连贯性审查（含 MAKEUP / VOICE 类穿帮）与修复 |
| `character-design` | 角色设计 |
| `novel-reader` | 小说读取与元素提取 |
| `ffmpeg-video-processing` | FFmpeg 视频处理 |

## 仓库结构

```
changdu-skills/
├── changdu/              # changdu CLI 源码（Python）
│   ├── pyproject.toml
│   └── src/changdu/
├── skills/               # openclaw 技能文件
│   ├── jimeng-skill/
│   ├── novel-to-video/
│   └── ...
├── scripts/
│   └── setup.sh          # 一键安装脚本
└── README.md
```

## License

MIT
