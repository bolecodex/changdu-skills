---
name: novel-to-video
description: 文学作品到影视视频的自然语言工作流；生成链路统一使用 changdu CLI。支持漫剧和真人剧两种模式。
---

# 文学作品到影视视频工作流（changdu 版）

## 核心任务

将小说/故事/剧本转换为完整视频，严格按技能链路执行，不跳步。

## 必须学习的技能

- `novel-reader`：读取与提取角色/场景/道具
- `text-storyboard`：生成文字分镜
- `generate-film-video-prompt`：补强视频提示词
- `storyboard-to-seedance-prompt`：分镜转视频提示词（含防穿帮约束规则）
- `character-design`：角色设计提示词
- `jimeng-skill`：统一生成入口（内部统一走 `changdu` CLI）
- `asset-management`：素材资产管理（真人剧必需）
- `video-review`：连贯性审查与修复（步骤 7.5）

## 两种制作模式

开始前先与用户确认制作模式：

| 模式 | 画风 | 视频生成方式 | 适用场景 |
|------|------|-------------|----------|
| **漫剧模式** | 赛璐璐/动漫/非写实 | `--image` 传入参考图 | 动漫风格短剧 |
| **真人剧模式** | 写实/3D写实 | `--asset` 传入入库素材 | 真人风格短剧 |

## 全局要求

- 开始前先确认画风、比例（默认 `16:9`）和制作模式。
- **漫剧模式**必须使用非写实描述（赛璐璐、线稿平涂、动漫设定稿）。
- **真人剧模式**需先使用 `asset-management` 技能将素材入库。
- 所有图像与视频生成都通过 `changdu` 执行。

## 工作流（严格顺序）

### 步骤 1-4：通用（两种模式相同）

1. **读取文本**：使用 `novel-reader` 提取角色、场景、道具。
2. **文字分镜**：使用 `text-storyboard` 输出 `单集制作/EPXXX/文字分镜.txt`。
3. **生成角色图**：
   - 先产出 `角色/角色名.prompt.txt`
   - 再执行 `changdu text2image ... --output 角色/角色名.jpg`
   - 真人剧建议额外生成面部特写图和三视图
4. **生成场景/道具图**：
   - 先产出对应 `*.prompt.txt`
   - 再执行 `changdu text2image ... --output 场景/xxx.jpg` 或 `道具/xxx.jpg`

### 步骤 5：校验资产

确认角色/场景/道具图片都已存在，否则禁止进入视频阶段。

### 步骤 5.5：【仅真人剧】素材入库

将角色和场景图片入库到 Assets：

```bash
# 创建素材组
changdu asset-group-create --name "项目名-角色组"

# 入库每个角色（面部特写和妆造分开上传）
changdu asset-create --file ./角色/女主_面部.jpg --group-id <组ID> --type Image --name "女主-面部"
changdu asset-create --file ./角色/女主_三视图.jpg --group-id <组ID> --type Image --name "女主-妆造"

# 入库场景
changdu asset-create --file ./场景/会议室.jpg --group-id <组ID> --type Image --name "会议室"
```

记录每个素材的 Asset ID，后续视频生成时使用。

### 步骤 6：生成每个 clip（顺序生成，尾帧衔接）

调用 `storyboard-to-seedance-prompt` 产出 `视频_ClipXXX.prompt.txt`。

#### 步骤 6.5：提示词优化（生成前质量把关）

在生成视频之前，先用 `prompt-optimize` 对所有 prompt 文件进行预检和自动优化：

```bash
# 1) 检查模式：扫描结构/画质/运镜/动作问题
changdu prompt-optimize --dir ./单集制作/EP001/ --check

# 2) 自动优化：追加画质约束、面部稳定、范围边界（输出到新目录确认无误后覆盖）
changdu prompt-optimize --dir ./单集制作/EP001/ --output-dir ./单集制作/EP001/optimized/ --style '电影写实'

# 3) 确认无误后用优化版替换原文件
cp ./单集制作/EP001/optimized/*.prompt.txt ./单集制作/EP001/
```

`prompt-optimize` 基于 Seedance 2.0 提示词指南，自动检查并修复：
- 缺失的角色锚定/道具锁定/场景锁定/否定约束块
- 无时间轴分镜结构
- 抽象情绪词（应替换为具体身体信号）
- 运镜堆叠（单段超过 3 种运镜会导致画面抖动）
- 高强度动作词（Seedance 偏好缓慢连续动作）
- 缺失的范围边界声明（防止叙事泄漏）
- 缺失的 `不要BGM，不要字幕` 尾部约束
- 缺失的动作过渡词（提升连贯性）

**关键原则**：视频必须按 Clip 顺序逐个生成，前一个 clip 的尾帧自动作为下一个 clip 的首帧，保证角色和场景的连贯性。

#### 推荐方式：`sequential-generate` 一键命令

**漫剧模式**（传图片文件）：

```bash
changdu sequential-generate \
  --prompt-dir ./单集制作/EP001/ \
  --image 角色/女主.jpg --image 场景/会议室.jpg \
  --ratio 16:9 --duration 15 \
  --prompt-header "图1是女主，图2是场景。" \
  --output-dir ./单集制作/EP001/
```

**真人剧模式**（传 Asset ID）：

```bash
changdu sequential-generate \
  --prompt-dir ./单集制作/EP001/ \
  --asset <女主面部ID> --asset <女主妆造ID> --asset <场景ID> \
  --ratio 16:9 --duration 15 \
  --prompt-header "图片1的女孩（妆造参考图片2）站在图片3的场景中。" \
  --output-dir ./单集制作/EP001/
```

该命令自动完成：
1. 扫描目录内 `视频_ClipXXX.prompt.txt` 文件（按编号排序）
2. 按顺序逐个生成，每个 clip 启用 `return_last_frame`
3. 将前一 clip 的尾帧 URL 作为下一 clip 的 `first_frame_url`
4. 可选从前一视频中抽取关键帧作为额外参考（默认开启）

#### 手动方式（按需单个生成）

```bash
# 第1个 clip
changdu multimodal2video \
  --image 角色/女主.jpg --image 场景/会议室.jpg \
  --prompt "图1是女主，图2是场景。$(cat 视频_Clip001.prompt.txt)" \
  --ratio 16:9 --duration 15 --wait --output 视频_Clip001.mp4 \
  --return-last-frame
# 输出中包含「尾帧URL: https://...」

# 第2个 clip：用上一 clip 的尾帧URL
changdu multimodal2video \
  --image 角色/女主.jpg --image 场景/会议室.jpg \
  --prompt "图1是女主，图2是场景。$(cat 视频_Clip002.prompt.txt)" \
  --ratio 16:9 --duration 15 --wait --output 视频_Clip002.mp4 \
  --return-last-frame --first-frame-url <上一clip输出的尾帧URL>
```

### 步骤 7：拼接初版

使用 ffmpeg 拼接全部 clip 为初版视频。

### 步骤 7.5：连贯性审查与修复

调用 `video-review` 技能对初版视频进行审查和修复：

1. **提取关键帧**：对每个 clip 提取首帧/中帧/尾帧到 `analysis/` 目录
2. **识别穿帮**：逐帧对比相邻 clip 衔接处，检查角色外貌、道具、场景、色调一致性
3. **生成修复计划**：按 TRIM / REGEN / COLOR / TRANSITION / ACCEPT 分类
4. **执行修复**：
   - 对叙事泄漏的 clip 使用 `changdu clip-transition --trim-a-tail` 裁剪尾部
   - 对角色/道具/场景穿帮的 clip 修改 prompt（强化角色锚定、道具锁定、场景锁定）后使用 `changdu clip-regen` 重新生成
   - 对衔接生硬处使用 `changdu clip-transition --transition fade` 添加转场
   - 对全片色调不统一使用 `changdu color-match` 调色
5. **重新拼接**修复后的 clip
6. **二次审查**确认问题已修复（最多迭代 2 轮）

```bash
# 示例：修复第4个 clip（角色外貌穿帮）
# 1) 先修改 视频_Clip004.prompt.txt，加入正确的角色锚定块
# 2) 重新生成
changdu clip-regen \
  --clip 4 --prompt-dir ./单集制作/EP001/ \
  --asset <角色ID> --asset <场景ID> \
  --prev-clip ./单集制作/EP001/视频_Clip003.mp4 \
  --ratio 16:9 --duration 15

# 示例：裁剪 clip1 尾部 + 添加转场
changdu clip-transition \
  --clip-a 视频_Clip001.mp4 --clip-b 视频_Clip002.mp4 \
  --transition fade --duration 0.5 --trim-a-tail 2.0 \
  --output fixed/merged_001_002.mp4

# 示例：全片色调统一
changdu color-match \
  --input-dir ./单集制作/EP001/ \
  --output-dir ./单集制作/EP001/graded/ \
  --brightness -0.05 --contrast 1.1 --saturation 0.9
```

### 步骤 8：最终拼接成片

使用 ffmpeg 拼接全部修复后的 clip 为最终视频。

## 推荐目录结构

```
项目名/
├── 角色/
│   ├── 女主.jpg
│   ├── 女主_面部.jpg      # 真人剧：面部特写
│   └── 女主_三视图.jpg    # 真人剧：妆造三视图
├── 场景/
├── 道具/
├── assets.json             # 真人剧：记录 Asset ID 映射
└── 单集制作/
    └── EP001/
        ├── 文字分镜.txt
        ├── 视频_Clip001.prompt.txt
        ├── 视频_Clip001.mp4
        └── ...
```

## 断点续做

- 先扫描目录，定位已完成到哪一步。
- 从缺失产物的第一步继续，不重复覆盖已完成成果。
- 真人剧模式：检查 `assets.json` 中已入库的素材 ID，跳过已入库素材。
