---
name: video-review
description: 自动审查生成视频的连贯性问题（穿帮），按类别分类并使用 changdu CLI 执行修复。
---

# 视频连贯性审查与修复

## 核心任务

对已生成的多 clip 视频进行连贯性审查，识别穿帮问题，并使用 changdu CLI 的修复工具链执行修复。

## 前置条件

- 已安装 changdu CLI 和 ffmpeg
- 视频目录中包含 `视频_ClipXXX.mp4` 文件
- 对应的 `视频_ClipXXX.prompt.txt` 提示词文件

## 工作流

### Step 1：提取关键帧

对每个 clip 提取首帧、中帧、尾帧：

```bash
for clip in 视频_Clip*.mp4; do
  stem="${clip%.mp4}"
  ffmpeg -y -i "$clip" -vf "select=eq(n\,0)" -vframes 1 -q:v 1 "analysis/${stem}_first.jpg"
  ffmpeg -y -sseof -1 -i "$clip" -update 1 -q:v 1 "analysis/${stem}_last.jpg"
  # 中帧
  total=$(ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of csv=p=0 "$clip")
  mid=$((total / 2))
  ffmpeg -y -i "$clip" -vf "select=eq(n\,$mid)" -vframes 1 -q:v 1 "analysis/${stem}_mid.jpg"
done
```

### Step 2：逐对比较，识别问题

对相邻 clip 的衔接帧进行逐对分析（Clip N 的尾帧 vs Clip N+1 的首帧），检查以下 5 类问题：

| 类别 | 检查内容 | 严重程度 |
|------|---------|---------|
| **TRANSITION** | 前一 clip 尾部提前展示下一 clip 内容（叙事泄漏） | 高 |
| **CHARACTER** | 角色外观不一致（发型、伤疤、头饰、面部特征变化） | 高 |
| **PROP** | 道具变化（武器形状、数量、位置不一致） | 中 |
| **SCENE** | 场景建筑/布局不一致（柱子数量、墙壁颜色、门窗位置） | 中 |
| **DETAIL** | 其他细节错误（月亮形状、天色变化、光照方向不一致） | 低 |

### Step 3：生成修复计划

对每个识别出的问题分配修复动作：

| 修复动作 | 适用场景 | 使用工具 |
|----------|---------|---------|
| **TRIM** | 前一 clip 尾部包含下一 clip 内容 | `changdu clip-transition --trim-a-tail X` |
| **REGEN** | 角色/道具/场景严重不一致，需重新生成 | `changdu clip-regen --clip N --prev-clip ...` |
| **COLOR** | 色调/亮度不一致 | `changdu color-match --input-dir ...` |
| **TRANSITION** | 相邻 clip 衔接生硬 | `changdu clip-transition --transition fade` |
| **ACCEPT** | 不影响观看体验的小瑕疵 | 无需操作 |

输出修复计划为结构化列表：

```
修复计划：
- Clip001→Clip002: TRIM（裁掉 Clip001 尾部 2s）
- Clip003→Clip004: REGEN（Clip004 角色外貌变化，需用改进 prompt 重新生成）
- Clip005→Clip006: COLOR（亮度跳变，需统一调色）
- Clip007→Clip008: TRANSITION（添加淡入淡出转场）
- 全局: COLOR（统一全片月光色调）
```

### Step 3.5：提示词预检与优化

在执行修复之前，先对所有 prompt 文件进行质量检查和自动优化：

```bash
# 检查模式：扫描所有 prompt 的结构/画质/运镜/动作问题
changdu prompt-optimize --dir ./ --check

# 自动修复模式：追加画质约束、面部稳定、范围边界等（保存到新目录）
changdu prompt-optimize --dir ./ --output-dir ./optimized/ --style '古风电影写实'

# 直接覆盖原文件（适合确认无误后使用）
changdu prompt-optimize --dir ./ --style '电影写实'
```

`prompt-optimize` 检查的 8 类问题：
- **缺失约束块**：角色锚定、道具锁定、场景锁定、否定约束是否齐全
- **时间轴结构**：是否使用 `0–5s:` 格式的分镜时序
- **抽象情绪词**：`很悲伤/非常愤怒` → 应改为 `嘴角颤抖/眼眶渐红`
- **运镜堆叠**：单段内超过 3 种运镜方式会导致画面不稳定
- **高强度动作词**：`狂奔/大跳/剧烈翻滚` Seedance 不擅长处理
- **范围边界**：是否有 `本段仅展示上述动作` 防止叙事泄漏
- **尾部约束**：是否有 `不要BGM，不要字幕`
- **动作过渡词**：是否有 `顺势/借着/紧接着` 提升动作连贯性

### Step 4：执行修复

按修复计划逐项执行：

#### 4.1 裁剪修复（TRIM）

```bash
changdu clip-transition \
  --clip-a 视频_Clip001.mp4 --clip-b 视频_Clip002.mp4 \
  --transition fade --duration 0.5 \
  --trim-a-tail 2.0 \
  --output fixed/merged_001_002.mp4
```

#### 4.2 重新生成（REGEN）

先修改对应的 `视频_ClipXXX.prompt.txt`，强化出错部分的描述（参考 `storyboard-to-seedance-prompt` 技能中的角色锚定块、道具锁定行、场景锁定行规则），然后：

```bash
changdu clip-regen \
  --clip 4 --prompt-dir ./ \
  --asset <角色ID> --asset <场景ID> \
  --prev-clip 视频_Clip003.mp4 \
  --ratio 16:9 --duration 15
```

重新生成后，再次提取关键帧确认问题已修复。

#### 4.3 色调统一（COLOR）

```bash
changdu color-match \
  --input-dir ./ \
  --output-dir ./graded/ \
  --brightness -0.05 --contrast 1.1 --saturation 0.9
```

#### 4.4 添加转场（TRANSITION）

```bash
changdu clip-transition \
  --clip-a 视频_Clip005.mp4 --clip-b 视频_Clip006.mp4 \
  --transition fade --duration 0.5 \
  --output fixed/merged_005_006.mp4
```

### Step 5：重新拼接

将所有修复后的 clip 拼接为最终视频：

```bash
# 创建拼接列表
for f in $(ls 视频_Clip*.mp4 | sort); do echo "file '$f'" >> concat_list.txt; done
ffmpeg -f concat -safe 0 -i concat_list.txt -c copy 最终版.mp4
```

### Step 6：二次审查

对修复后的视频重复 Step 1-2，确认问题已解决。如仍有严重问题，回到 Step 4 继续迭代（最多 2 轮）。

## 修复 prompt 的要诀

修改 `视频_ClipXXX.prompt.txt` 时遵循以下原则：

1. **角色锚定**：在 prompt 开头明确角色当前外观状态（如"深蓝飞鱼服男子（束冠短发，左颊有血痕，右手持单刀）"）
2. **道具锁定**：明确列出当前 clip 中每个角色手持/佩戴的道具
3. **场景锁定**：用固定短语描述场景（如"废弃古庙内殿，石柱林立，月光从破损屋顶洒入"）
4. **范围限制**：只描述当前 15 秒内发生的事，不泄漏后续剧情
5. **否定约束**：对容易出错的细节加否定描述（如"天空中一弯细细的残月（非圆月、非满月）"）

## 关联技能

- `storyboard-to-seedance-prompt`（提示词生成规范）
- `novel-to-video`（整体工作流）
- `ffmpeg-video-processing`（视频后处理细节）
- `changdu` CLI（`prompt-optimize`、`clip-regen`、`clip-transition`、`color-match` 命令）
