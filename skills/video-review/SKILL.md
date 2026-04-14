---
name: video-review
description: 审查多 clip 视频的连贯性问题（穿帮），通过修改 prompt 并用 Seedance 重新生成来修复，而非 FFmpeg 后处理。
---

# 视频连贯性审查与修复

## 核心原则

**穿帮修复 = 修改 prompt + Seedance 重新生成**，而不是 FFmpeg 滤镜/转场/调色。

FFmpeg 只用于两件事：
1. 提取关键帧（分析用）
2. 拼接最终成片（`changdu clip-concat`，保留音视频）

## 前置条件

- 已安装 changdu CLI 和 ffmpeg
- 视频目录中包含 `视频_ClipXXX.mp4` 和 `视频_ClipXXX.prompt.txt`

## 工作流

### Step 1：提取关键帧

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

对相邻 clip 的衔接帧（Clip N 尾帧 vs Clip N+1 首帧）检查 5 类问题：

| 类别 | 检查内容 | 严重程度 |
|------|---------|---------|
| **TRANSITION** | 前一 clip 尾部提前展示下一 clip 内容（叙事泄漏） | 高 |
| **CHARACTER** | 角色外观不一致（发型、伤疤、面部特征变化） | 高 |
| **PROP** | 道具变化（武器形状、数量、位置不一致） | 中 |
| **SCENE** | 场景布局不一致（柱子数量、墙壁颜色变化） | 中 |
| **DETAIL** | 其他细节（月亮形状、光照方向不一致） | 低 |

### Step 3：生成修复计划

每个穿帮点只有两种修复方式：

| 修复方式 | 适用场景 | 操作 |
|----------|---------|------|
| **REGEN** | 角色/道具/场景穿帮 | 修改 prompt → `changdu clip-regen` 重新生成 |
| **TRIM** | 叙事泄漏（clip 尾部多余内容） | `changdu clip-trim --trim-tail Xs` 裁剪 |

**不使用** FFmpeg 调色、xfade 转场等后处理。这些操作会破坏音频、引入新的不一致。

输出修复计划：

```
修复计划：
- Clip003: TRIM（尾部 2s 叙事泄漏）
- Clip004: REGEN（角色外貌穿帮 → 强化角色锚定块后重新生成）
- Clip006: REGEN（主角缺失 → 修改 prompt 确保主角全程在场）
```

### Step 4：提示词预检

修复前先检查所有 prompt 质量：

```bash
changdu prompt-optimize --dir ./ --check
```

### Step 5：执行修复

#### 5.1 重新生成（REGEN）— 穿帮修复的核心方式

先修改 `视频_ClipXXX.prompt.txt`，根据穿帮类型强化对应约束块：

- **角色穿帮** → 在【角色锚定】中更精确描述当前状态
- **道具穿帮** → 在【道具锁定】中明确形状/数量/位置
- **场景穿帮** → 在【场景锁定】中增加更多固定细节
- **主角缺失** → 在分镜描述中每个时段都明确提及主角

然后用 Seedance 重新生成：

```bash
changdu clip-regen \
  --clip 4 --prompt-dir ./ \
  --asset <角色ID> --asset <场景ID> \
  --prompt-header '图片1是男主面部，图片2是场景。' \
  --ratio 16:9 --duration 15
```

重新生成后，再次提取关键帧确认问题已修复。

#### 5.2 裁剪叙事泄漏（TRIM）

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

对修复后的视频重复 Step 1-2，确认问题已解决。最多迭代 2 轮。

## 修改 prompt 的要诀

1. **角色锚定**：在 prompt 开头明确当前外观状态（如"束冠短发，左颊有血痕，右手持单刀"）
2. **道具锁定**：明确列出每个角色手持/佩戴的道具及尺寸形状
3. **场景锁定**：用固定短语描述场景，同一场景的 clip 使用完全相同的描述
4. **范围限制**：只描述当前 15 秒内的事，加"本段仅展示上述动作"
5. **否定约束**：对容易出错的细节加否定描述
6. **主角在场**：每个时段的分镜描述中都要提到主角的动作/位置

## 关联技能

- `storyboard-to-seedance-prompt`（提示词规范）
- `novel-to-video`（整体工作流）
- `changdu` CLI 命令：
  - `clip-regen`：用 Seedance 重新生成穿帮 clip
  - `clip-trim`：裁剪叙事泄漏
  - `clip-concat`：拼接成片（保留音视频）
  - `prompt-optimize`：提示词质量检查
