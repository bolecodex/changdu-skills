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
- `storyboard-to-seedance-prompt`：分镜转视频提示词
- `character-design`：角色设计提示词
- `jimeng-skill`：统一生成入口（内部统一走 `changdu` CLI）
- `asset-management`：素材资产管理（真人剧必需）

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

### 步骤 7：拼接成片

使用 ffmpeg 拼接全部 clip。

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
