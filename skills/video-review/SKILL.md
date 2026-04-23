---
name: video-review
description: 审查多 clip 视频的连贯性问题（含妆造与音色穿帮），通过修改 prompt + 多模态参考素材并用 Seedance 重新生成来修复，而非 FFmpeg 后处理。
---

# 视频连贯性审查与修复

## 核心原则

**穿帮修复 = 修改 prompt + 加上正确的 reference_image / reference_video / reference_audio + Seedance 重新生成**，而不是 FFmpeg 滤镜/转场/调色。

FFmpeg 只用于三件事：
1. 提取关键帧（人工/AI 比对用）
2. 抽前段尾段（做下一段的 `reference_video`，由 `changdu clip-extract-tail` 包装）
3. 拼接最终成片（`changdu clip-concat`，保留音视频）

## 前置条件

- 已安装 changdu CLI 和 ffmpeg
- 视频目录中包含 `视频_ClipXXX.mp4` 和 `视频_ClipXXX.prompt.txt`
- 主角已有"角色三视图"图片素材（建议先用 `asset-create --type Image` 入库）
- 第 1 个 clip 完成后已用 `changdu voice-asset-from-clip` 提取并入库主角音色样本（可选但强烈推荐）

## 工作流

### Step 1：提取关键帧（视觉比对）

对每个 clip 提取首帧、中帧、尾帧用于人工/AI 比对：

```bash
mkdir -p analysis
for clip in 视频_Clip*.mp4; do
  stem="${clip%.mp4}"
  ffmpeg -y -i "$clip" -vf "select=eq(n\,0)" -vframes 1 -q:v 1 "analysis/${stem}_first.jpg"
  ffmpeg -y -sseof -1 -i "$clip" -update 1 -q:v 1 "analysis/${stem}_last.jpg"
  total=$(ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of csv=p=0 "$clip")
  mid=$((total / 2))
  ffmpeg -y -i "$clip" -vf "select=eq(n\,$mid)" -vframes 1 -q:v 1 "analysis/${stem}_mid.jpg"
done
```

### Step 2：逐对比较，识别穿帮

对相邻 clip 的衔接帧（Clip N 尾帧 vs Clip N+1 首帧）以及音轨进行检查，常见 9 类问题：

| 类别 | 检查内容 | 严重程度 |
|------|---------|---------|
| **TRANSITION** | 前一 clip 尾部提前展示下一 clip 内容（叙事泄漏） | 高 |
| **CHARACTER** | 角色外观不一致（发型、伤疤、面部特征变化） | 高 |
| **MAKEUP** | 妆容/眉形/口红色/盘发等细节漂移（即便整张脸"像"也算穿帮） | 高 |
| **TWIN** | 同一画面出现两个几乎一模一样的角色（双胞胎问题） | 高 |
| **PROP** | 道具变化（武器形状、数量、位置不一致）或道具与参考图不符 | 中 |
| **SCENE** | 场景布局不一致（柱子数量、墙壁颜色变化）或人物站位与场景空间不符 | 中 |
| **VOICE** | 角色音色变化（同一人物不同 clip 听感不同、性别错乱、口音切换） | 高 |
| **BINDING** | prompt 中角色/道具出现时缺少 `@图片N` 绑定，导致模型无法锚定参考图 | 高 |
| **DETAIL** | 其他细节（月亮形状、光照方向不一致） | 低 |

**音色检查方式**：

```bash
# 抽取每个 clip 的音轨片段做比对
mkdir -p analysis_audio
for clip in 视频_Clip*.mp4; do
  stem="${clip%.mp4}"
  ffmpeg -y -ss 6 -i "$clip" -t 6 -vn -acodec libmp3lame -q:a 2 "analysis_audio/${stem}_voice.mp3"
done
# 人耳过一遍，或者上传到 ASR/声纹比对工具
```

### Step 3：生成修复计划

每个穿帮点的修复方式：

| 修复方式 | 适用穿帮类别 | 操作 |
|----------|---------|------|
| **REGEN** | CHARACTER / MAKEUP / PROP / SCENE / DETAIL | 修改 prompt 强化对应锚定块 + `clip-regen` 重新生成 |
| **REGEN-CHAIN** | 同一处穿帮波及连续多个 clip | 修改 prompt 后用 `clip-chain-regen` 链式重生（默认 ref_video 衔接） |
| **VOICE-FIX** | VOICE 类穿帮 | 用第 1 个 clip 提取音色样本 + `clip-regen --voice-asset <id>` 重生该 clip；同时在 prompt 中补充音色特征描述词 |
| **BINDING-FIX** | BINDING 类穿帮 | 检查 prompt 中所有角色/道具是否都用了 `@图片N` 格式，补全遗漏的绑定 |
| **TWIN-FIX** | TWIN 类穿帮 | 在 prompt 末尾追加"视频全程不要在同一画面中复制相同人物，不要多人同脸"；检查是否使用了三视图（禁止）；确保每个角色有独立的面部特写参考图 |
| **TRIM** | 叙事泄漏（clip 尾部多余内容） | `changdu clip-trim --trim-tail Xs` 裁剪 |

**不使用** FFmpeg 调色、xfade 转场等后处理。这些操作会破坏音频、引入新的不一致。

输出修复计划：

```
修复计划：
- Clip003: TRIM（尾部 2s 叙事泄漏）
- Clip004: REGEN-MAKEUP（眼影色变化 → 强化【妆造锁定】+ 加 ref_video 抽 Clip003 尾段 + 重生）
- Clip005: VOICE-FIX（女主音色变粗 → 加 --voice-asset asset-qingluo-voice 重生）
- Clip006: REGEN（主角缺失 → 修改 prompt 确保主角全程在场）
- Clip007-009: REGEN-CHAIN（连续 3 段服装色差 → clip-chain-regen --continuity-mode ref_video）
```

### Step 4：提示词预检

修复前先检查所有 prompt 质量（含妆造/音色/视频参考三条新规则）：

```bash
changdu prompt-optimize --dir ./ --check
```

### Step 5：执行修复

#### 5.1 重新生成（REGEN）— 穿帮修复的核心方式

先修改 `视频_ClipXXX.prompt.txt`，根据穿帮类型强化对应约束块：

- **角色穿帮（CHARACTER）** → 在【角色锚定】中更精确描述当前状态
- **妆造穿帮（MAKEUP）** → 把妆容/发型/五官精修拆出独立【妆造锁定】块，写明眉形/眼影/口红/盘发
- **道具穿帮（PROP）** → 在【道具锁定】中明确形状/数量/位置
- **场景穿帮（SCENE）** → 在【场景锁定】中增加更多固定细节
- **主角缺失** → 在分镜描述中每个时段都明确提及主角

然后用 Seedance 重新生成。**CHARACTER / MAKEUP 类穿帮强烈推荐使用 `--prev-clip` 自动抽尾段做 reference_video，再叠加 ref_image 做"双锚定"**，效果远胜单首帧：

```bash
changdu clip-regen \
  --clip 4 --prompt-dir ./ \
  --asset <角色三视图ID> --asset <场景ID> \
  --prev-clip ./视频_Clip003.mp4 \
  --prev-tail-seconds 5 \
  --voice-asset <音色样本ID> \
  --prompt-header '图片1是男主三视图，图片2是场景。视频1 是 Clip003 尾段，请保持人物外观、妆造与位置连续。' \
  --ratio 16:9 --duration 15
```

重新生成后，再次提取关键帧确认问题已修复。

#### 5.2 链式重生（REGEN-CHAIN）

当连续多个 clip 都被同一处穿帮污染时，用 `clip-chain-regen` 一次性重生：

```bash
changdu clip-chain-regen \
  --clips 7,8,9 --prompt-dir ./ \
  --asset <角色三视图ID> --asset <场景ID> \
  --regen-prev \
  --continuity-mode ref_video \
  --voice-asset <音色样本ID> \
  --prompt-header '图片1是男主三视图，图片2是场景。' \
  --ratio 16:9 --duration 15
```

#### 5.3 音色修复（VOICE-FIX）

第 1 步——若还没有音色样本，从最早一段音色正确的 clip 提取并入库：

```bash
changdu voice-asset-from-clip \
  --input ./视频_Clip001.mp4 \
  --group-id <主角素材组ID> \
  --start 6 --duration 8
# 输出：音色 Asset ID: asset-xxxxx
```

第 2 步——给穿帮的 clip 重生时加 `--voice-asset` 或 `--ref-audio`：

```bash
changdu clip-regen \
  --clip 5 --prompt-dir ./ \
  --asset <角色三视图ID> --asset <场景ID> \
  --voice-asset asset-xxxxx \
  --prev-clip ./视频_Clip004.mp4 \
  --prompt-header '图片1是女主三视图。视频1 是 Clip004 尾段，仅作妆造与位置参考。音轨1 锁定女主音色。' \
  --ratio 16:9 --duration 15
```

同一集后续如果仍出现 VOICE 漂移，建议直接走链式：

```bash
changdu clip-chain-regen --clips 5,6,7 --prompt-dir ./ \
  --asset <角色ID> --voice-asset asset-xxxxx \
  --continuity-mode ref_video --ratio 16:9 --duration 15
```

#### 5.4 裁剪叙事泄漏（TRIM）

```bash
changdu clip-trim \
  --input 视频_Clip003.mp4 \
  --output 视频_Clip003.mp4 \
  --trim-tail 2.0
```

### Step 6：重新拼接

用 `clip-concat` 拼接所有 clip（保留完整音视频）：

```bash
changdu clip-concat \
  --input-dir ./ \
  --output 最终版.mp4
```

### Step 7：二次审查

对修复后的视频重复 Step 1-2（含音轨抽取），确认问题已解决。最多迭代 2 轮。

## 修改 prompt 的要诀

1. **角色锚定**：在 prompt 开头明确当前外观状态（如"束冠短发，左颊有血痕，右手持单刀"）
2. **@图片N 绑定**：确保 prompt 中每次提及角色都用 `角色名@图片N` 格式，每次提及道具都用 `道具名@图片N` 格式，绝不能省略
3. **妆造锁定**：把眉形 / 眼影 / 口红 / 盘发 / 鬓角等细节单独成块，避免被其他描述淹没。角色有妆造变化时，确保使用对应妆造的参考图
4. **道具锁定**：明确列出每个角色手持/佩戴的道具及尺寸形状；有道具参考图时在 prompt 开头绑定（如「图片4为U盘道具参考」）
5. **场景锁定**：用固定短语描述场景，同一场景的 clip 使用完全相同的描述；有场景360度视频时通过 `--ref-video` 传入
6. **范围限制**：只描述当前 15 秒内的事，加"本段仅展示上述动作"
7. **否定约束**：对容易出错的细节加否定描述
8. **反双胞胎**：多角色同画面时加"视频全程不要在同一画面中复制相同人物，不要多人同脸"
9. **主角在场**：每个时段的分镜描述中都要提到主角的动作/位置
10. **音色锚定**：凡有台词必须显式声明 `reference_audio: <voice_asset_id>`，并在生成命令侧 `--voice-asset` 传入。prompt 中必须加音色特征描述（如"低厚温润中年男声的音色"），不只写"音频N的音色"
11. **视频参考说明**：传 `--ref-video` 时必须用一句自然语言说明每个参考视频的语义角色（"视频1 是上一段尾部，仅作外观与位置参考，不要复刻其运镜"）
12. **参考图分工**：每张图只承担一种职责（面部/全身/场景/道具），禁止混用

## 关联技能

- `storyboard-to-seedance-prompt`（提示词规范，含妆造/音色/视频参考三块）
- `novel-to-video`（整体工作流）
- `asset-management`（音色样本与视频参考素材入库）
- `changdu` CLI 命令：
  - `clip-extract-tail`：抽前段尾段做 reference_video
  - `voice-extract` / `voice-asset-from-clip`：抽音色 / 一键入库
  - `clip-regen`：用 Seedance 重新生成穿帮 clip（支持 `--prev-clip`、`--voice-asset`、`--ref-video`、`--ref-audio`）
  - `clip-chain-regen`：链式重生（默认 `--continuity-mode ref_video`）
  - `clip-trim`：裁剪叙事泄漏
  - `clip-concat`：拼接成片（保留音视频）
  - `prompt-optimize`：提示词质量检查（含妆造/音色/视频参考三条新规则）
