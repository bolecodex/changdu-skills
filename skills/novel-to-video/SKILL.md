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
3. **生成角色图**（Seedance 2.0 最佳实践）：
   - 每个角色生成**面部特写**（大头照）+ **全身像**两张独立图片
   - **禁止使用三视图/多视图**作为人物参考（FAQ V-1/V-7：会导致ID漂移和双胞胎）
   - 面部特写应占画面80%以上，避免过多背景干扰
   - 执行 `changdu text2image ... --output 角色/角色名_face.jpg`
   - 执行 `changdu text2image ... --output 角色/角色名_fullbody.jpg`
#### 步骤 3.5：生成角色音色参考视频

为每个有台词的角色生成一段 5 秒的音色参考视频，用于后续所有 clip 的音色锚定：

```bash
changdu multimodal2video \
  --image 角色/<角色名>_face.jpg --image 角色/<角色名>_fullbody.jpg \
  --prompt "将图片1中的[2-3个核心特征]定义为[角色名]。图片2为[角色名]全身参考。[风格声明]。[角色名]缓缓转身，从正面到侧面再到背面，展示全身形象。她开口说道{[代表性台词]}，[音色特征描述]。保持无字幕，避免画面生成字幕，不要水印，不要logo。" \
  --ratio 16:9 --duration 5 --wait \
  --output 角色/<角色名>_voice_ref.mp4
```

**要点**：
- 台词选取该角色在剧中的代表性台词（1-2 句即可）
- `--duration 5` 足够包含转身 + 说话
- 视频用于提取音色特征，同时也可作为角色形象参考
- 生成后上传到 TOS 获取 URL，记录到 `assets.json` 的 `voice_ref_url` 字段

```bash
changdu upload-tos --file 角色/<角色名>_voice_ref.mp4
```

#### 步骤 3.6：生成妆造变化的参考资产

如果 `novel-reader` 提取到角色在剧中有妆造变化（换装、变妆、受伤等），需要为每种不同的妆造分别生成完整的参考资产：

```bash
# 为角色的某个特定妆造生成面部特写
changdu text2image \
  --prompt "[角色基础外貌描述]，[该妆造的具体变化描述]，面部特写，纯白背景" \
  --resolution_type 2k \
  --output 角色/<角色名>_<妆造名>_face.jpg

# 生成该妆造的全身像
changdu text2image \
  --prompt "[角色基础外貌描述]，[该妆造的具体变化描述]，全身站姿，纯白背景" \
  --resolution_type 2k \
  --output 角色/<角色名>_<妆造名>_fullbody.jpg

# 生成该妆造的音色参考视频
changdu multimodal2video \
  --image 角色/<角色名>_<妆造名>_face.jpg --image 角色/<角色名>_<妆造名>_fullbody.jpg \
  --prompt "将图片1中的[核心特征]定义为[角色名]。图片2为全身参考。[风格声明]。[角色名]缓缓转身展示全身形象，开口说道{[代表性台词]}。保持无字幕，不要水印，不要logo。" \
  --ratio 16:9 --duration 5 --wait \
  --output 角色/<角色名>_<妆造名>_voice_ref.mp4
```

**要点**：
- 每种妆造都需要独立的 face + fullbody + voice_ref 三件套
- 在 `assets.json` 中用 `looks` 数组管理，标注每种妆造适用的集数/场号
- 生成 clip 时，根据当前集数选择正确的妆造参考图传入 `--image`
- 在 prompt 的主体定义行中标注当前使用的妆造，如「图片1为[角色名]（[妆造名]造型）面部参考」

在 `assets.json` 中记录：
```json
{
  "characters": {
    "<角色名>": {
      "default_look": {
        "face_file": "角色/<角色名>_face.jpg",
        "fullbody_file": "角色/<角色名>_fullbody.jpg",
        "voice_ref_video": "角色/<角色名>_voice_ref.mp4",
        "voice_ref_url": "<TOS_URL>"
      },
      "looks": [
        {
          "name": "<妆造名称>",
          "episodes": ["EP005-EP008"],
          "description": "<外观变化描述>",
          "face_file": "角色/<角色名>_<妆造名>_face.jpg",
          "fullbody_file": "角色/<角色名>_<妆造名>_fullbody.jpg",
          "voice_ref_video": "角色/<角色名>_<妆造名>_voice_ref.mp4",
          "voice_ref_url": "<TOS_URL>"
        }
      ]
    }
  }
}
```

4. **生成场景图**：
   - 先产出对应 `*.prompt.txt`
   - 再执行 `changdu text2image ... --output 场景/xxx.jpg`

#### 步骤 4.5：生成场景360度参考视频

为每个主要场景生成一段 5 秒的360度缓慢旋转视频，展示完整空间布局。此视频在后续 clip 生成时作为 `--ref-video` 传入，帮助模型理解空间关系和人物站位：

```bash
changdu multimodal2video \
  --image 场景/<场景名>.jpg \
  --prompt "[风格声明]。镜头在[场景名]内做360度缓慢环绕旋转，依次展示[关键物品A]位置、[关键物品B]、[关键物品C]、[入口/出口位置]。镜头运动平稳流畅，展示完整的空间布局和物品摆放位置。保持无字幕，不要水印，不要logo。" \
  --ratio 16:9 --duration 5 --wait \
  --output 场景/<场景名>_360.mp4
```

**要点**：
- 以场景参考图为输入，生成环绕展示全空间的视频
- prompt 中明确描述空间中的关键物品和它们的相对位置
- `--duration 5` 足够展示一个完整的环绕旋转
- 生成后上传到 TOS 获取 URL，在 clip 生成时通过 `--ref-video` 传入
- 在 clip 的 prompt 中加入「参考视频N中的场景空间布局，保持人物站位一致」

```bash
changdu upload-tos --file 场景/<场景名>_360.mp4
```

在 `assets.json` 中记录场景视频：
```json
{
  "scenes": {
    "<场景名>": {
      "image": "场景/<场景名>.jpg",
      "video_360": "场景/<场景名>_360.mp4",
      "video_360_url": "<TOS_URL>"
    }
  }
}
```

5. **生成道具参考图**：
   - 从 novel-reader 提取的道具信息中，为每个重要道具生成参考图
   - 道具图要求：纯白背景、清晰展示道具外观（形状、颜色、材质、尺寸）、多角度（正面+侧面）
   - 执行 `changdu text2image ... --output 道具/xxx.jpg`

```bash
changdu text2image \
  --prompt "纯白背景，产品展示图。[道具外观描述：形状、颜色、材质、尺寸、独特标记]。正面和侧面两个角度展示，无文字无水印。" \
  --resolution_type 2k \
  --output 道具/<道具名>.jpg
```

**要点**：
- 道具图必须是纯白背景、清晰的产品展示风格
- prompt 中写清道具的形状、颜色、材质、尺寸、独特标记等视觉细节
- 在后续 clip 的 prompt 中，用 `道具名@图片N` 绑定
- 记录到 `assets.json` 的 `props` 字段

```json
{
  "props": {
    "<道具名>": {
      "image": "道具/<道具名>.jpg",
      "description": "[道具外观描述]"
    }
  }
}
```

### 步骤 5：校验资产

确认以下资产都已生成，否则禁止进入视频阶段：
- 每个角色的面部特写 + 全身像 + 音色参考视频
- 有妆造变化的角色：每个妆造的面部特写 + 全身像 + 音色参考视频
- 每个主要场景的参考图 + 360度旋转视频
- 每个重要道具的参考图

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
- 缺失的主体定义（应使用「将图片N中的X定义为主体」格式）
- 精确时间戳标记（Seedance 2.0对精确时间支持不稳定，应用自然语言过渡）
- 三视图/多视图引用（不建议使用，应改用面部特写+全身照）
- 抽象情绪词（应替换为具体身体信号）
- 运镜堆叠（15秒内不超过3种运镜）
- 高强度动作词（Seedance 偏好缓慢连续动作）
- 缺失的范围边界声明（防止叙事泄漏）
- 弱字幕/水印约束（应使用「保持无字幕，避免画面生成字幕，不要水印，不要logo」）
- 缺失的动作过渡词（紧接着/随后/顺势）
- 冗余的自定义meta标签（过多会干扰模型理解）
- 特殊字符 `--`（Seedance不解析该符号之后的内容）

**关键原则**：视频必须按 Clip 顺序逐个生成，前一个 clip 的尾帧自动作为下一个 clip 的首帧，保证角色和场景的连贯性。

#### 推荐方式：`sequential-generate` 一键命令

**漫剧模式**（传图片文件 + 音色参考 + 场景视频）：

```bash
changdu sequential-generate \
  --prompt-dir ./单集制作/EP001/ \
  --image 角色/女主_face.jpg --image 角色/女主_fullbody.jpg --image 场景/会议室.jpg \
  --ref-video <会议室_360_TOS_URL> \
  --ref-audio <女主_voice_ref_TOS_URL> \
  --ratio 16:9 --duration 15 \
  --prompt-header "将图片1中的[特征]定义为女主。图片2为女主全身参考。图片3为场景参考。参考视频1中的场景空间布局，保持人物站位一致。" \
  --output-dir ./单集制作/EP001/
```

**真人剧模式**（传图片 + 场景视频 + 音色参考）：

```bash
changdu sequential-generate \
  --prompt-dir ./单集制作/EP001/ \
  --image 角色/女主_face.jpg --image 角色/女主_fullbody.jpg --image 场景/场景.jpg --image 道具/U盘.jpg \
  --ref-video <场景_360_TOS_URL> \
  --ref-audio <女主_voice_ref_TOS_URL> \
  --ratio 16:9 --duration 15 \
  --prompt-header "将图片1中的[特征]定义为女主。图片2为女主全身参考。图片3为场景参考。图片4为U盘道具参考。参考视频1中的场景空间布局，保持人物站位一致。" \
  --output-dir ./单集制作/EP001/
```

> **音色锚定说明**：`--ref-audio` 传入步骤 3.5 生成的角色音色参考视频的 TOS URL，Seedance 会从中提取音色特征。同时在 prompt 中用 `采用音频1的[音色特征描述]的音色` 引用该音频（如"采用音频1的低沉坚韧青年女声的音色"），双重锚定确保音色一致性（参考 Seedance FAQ A-3）。多角色场景可传入多个 `--ref-audio`，在 prompt 中用 `音频1`、`音频2` 分别指代。

> **场景视频说明**：`--ref-video` 传入步骤 4.5 生成的场景360度旋转视频的 TOS URL。在 prompt 中声明「参考视频N中的场景空间布局，保持人物站位一致」，帮助模型理解空间关系。注意：如果同时使用 `--ref-video` 做前段尾段衔接（`sequential-generate` 的 `continuity-mode ref_video`），场景视频和衔接视频会共用 `--ref-video` 槽位（最多 3 段），需在 prompt 中分别说明每个视频的语义角色。

该命令自动完成：
1. 扫描目录内 `视频_ClipXXX.prompt.txt` 文件（按编号排序）
2. 按顺序逐个生成，每个 clip 启用 `return_last_frame`
3. 将前一 clip 的尾帧 URL 作为下一 clip 的 `first_frame_url`
4. 可选从前一视频中抽取关键帧作为额外参考（默认开启）
5. `--ref-audio` 会自动附加到每个 clip 的 `reference_audio`，保持全集音色一致

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

使用 `clip-concat` 拼接全部 clip，推荐 `--audio-fadein 0.3` 消除 Seedance 启动底噪同时保留原声（台词、音效）：

```bash
changdu clip-concat \
  --input-dir ./单集制作/EP001/ \
  --output ./单集制作/EP001/完整版.mp4 \
  --audio-fadein 0.3
```

> **注意**：不要使用 `--strip-audio`，否则会丢失 Seedance 生成的角色台词和音效。仅在后期需要全量配音配乐时才使用 `--strip-audio`。

### 步骤 7.5：连贯性审查与修复

调用 `video-review` 技能对视频进行审查。**穿帮修复 = 修改 prompt + Seedance 重新生成**，不使用 FFmpeg 调色/转场。

1. **提取关键帧**：对每个 clip 提取首帧/中帧/尾帧到 `analysis/` 目录
2. **识别穿帮**：逐帧对比相邻 clip 衔接处，检查角色外貌、道具、场景一致性
3. **修复**（只有两种方式）：
   - **REGEN**：修改 prompt 强化约束块 → `changdu clip-regen` 用 Seedance 重新生成
   - **TRIM**：叙事泄漏 → `changdu clip-trim --trim-tail Xs` 裁剪
4. **重新拼接** → `changdu clip-concat`

```bash
# 穿帮修复：修改 prompt 后重新生成第4个 clip
changdu clip-regen \
  --clip 4 --prompt-dir ./单集制作/EP001/ \
  --asset <角色ID> --asset <场景ID> \
  --prompt-header '图片1是男主面部，图片2是场景。' \
  --ratio 16:9 --duration 15

# 叙事泄漏：裁剪 clip 尾部
changdu clip-trim \
  --input 视频_Clip003.mp4 \
  --output 视频_Clip003.mp4 \
  --trim-tail 2.0

# 重新拼接
changdu clip-concat \
  --input-dir ./单集制作/EP001/ \
  --output ./单集制作/EP001/最终版.mp4 \
  --audio-fadein 0.3
```

## Seedance 2.0 提示词最佳实践

基于官方提示词指南和 FAQ，撰写视频提示词时遵循以下规则：

### 参考图分工原则

每张参考图只承担**一种**职责，禁止混用：

| 图片职责 | 用途 | 示例 |
|----------|------|------|
| 面部特写 | 锁定角色五官ID | 角色_face.jpg，放图片1（最高优先级） |
| 全身妆造 | 锁定服装/体态 | 角色_fullbody.jpg，放图片2 |
| 场景空间 | 锁定环境/空间布局 | 场景.jpg |
| 道具参考 | 锁定道具外观 | 道具/<道具名>.jpg |
| 站位草稿 | 表达人物空间关系 | 站位草稿.jpg（可选） |

**禁止**将人物图、场景图、站位草稿、道具图混在同一张图片中。空间关系优先通过参考图/参考视频表达，减少复杂文字描述。

### 提示词格式

```
将图片1中的[2-3个核心特征]定义为[角色名]。图片2为[角色名]全身参考。图片3为[场景名]场景参考。图片4为[道具名]道具参考（如有）。参考视频1中的场景空间布局，保持人物站位一致（如有场景视频）。

[风格声明，如：电影写实风格 / 日本动漫cel-shaded风格]

[场景描述]。[镜头类型]角色名@图片N[动作]，采用音频N的[音色特征]的音色说{台词原文}。紧接着[下一动作]。随后[下一动作]。最后[结束动作]定格。

本段仅展示上述动作，不展示后续剧情。视频全程不要在同一画面中复制相同人物，不要多人同脸。保持无字幕，避免画面生成字幕，不要水印，不要logo，不要BGM。
```

> **台词全链路保留**：剧本中的角色对白必须经过 `text-storyboard`（原文保留）→ `storyboard-to-seedance-prompt`（转写为 `{}` 格式）完整传递到最终 prompt 中。禁止在任何环节将台词概括为"低语道歉""质问"等动作描述。

### 关键规则

1. **主体定义**：每次引用参考图中的角色，必须用「将图片N中的X定义为主体」格式绑定
2. **@图片N 绑定不可省略**：每次角色出镜都必须用 `角色名@图片N` 格式标注（如 `女主@图片1`），绝不能只写角色名。道具出现时同理（如 `信物@图片4`）。这是 Seedance 2.0 核心规则
3. **描述顺序**：镜头 → 主体 → 空间 → 音频，按事件发生顺序描述
4. **自然语言过渡**：使用「紧接着/随后/顺势」连接动作，不使用精确时间戳
5. **简洁优先**：避免冗长meta标签，直接描述画面内容
6. **参考图规范**：面部特写放图片1（最高优先级），全身照放图片2，场景放图片3，道具放后续编号
7. **台词格式**：使用 `{}` 包裹台词内容。台词必须从剧本原文完整保留，经过 `text-storyboard` → `storyboard-to-seedance-prompt` 全链路不得丢失。示例：剧本 `女主低声说："对不起"` → 文字分镜保留原文 → Seedance prompt 写为 `女主@图片1低声说{对不起}`
8. **音色锚定**：当角色有音色参考音频时，台词前加 `采用音频N的[音色特征描述]的音色`，如 `采用音频1的温柔低沉女声的音色说{对不起}`。**必须包含具体音色特征描述词**（低厚温润/清冽有力/沙哑低沉等），不要只写"采用音频N的音色"——加上特征描述能显著提升音色参考准确性（参考 FAQ A-3）
9. **特殊符号**：音乐用 `()`，音效用 `<>`，字幕用 `【】`，禁止使用 `--`
10. **反双胞胎**：多角色同画面时，在 prompt 末尾追加「视频全程不要在同一画面中复制相同人物，不要多人同脸」
11. **场景视频参考**：有360度场景视频时，在 prompt 中声明「参考视频N中的场景空间布局，保持人物站位一致」，通过 `--ref-video` 传入

### 常见问题防范

| 问题 | 防范措施 |
|------|----------|
| ID漂移（换脸） | 面部特写单独裁剪作为参考图，放图片1最前面；禁止使用三视图/多视图 |
| 双胞胎 | 不用三视图；每次提及角色时用 `@图片N` 标注；多角色场景加"不要多人同脸" |
| 参考图混用 | 每张图只承担一种职责（面部/全身/场景/道具），禁止混在一张图中 |
| 风格漂移 | 在提示词开头明确风格，如「2D日漫风格」；参考图先转目标风格再生视频 |
| 生成字幕 | 加「保持无字幕，避免画面生成字幕」；输入图片/视频去除已有文字 |
| 生成水印/logo | 加「不要水印，不要logo」 |
| 音色不准 | 加音色特征描述词（如"低厚温润中年男声"）；台词风格与参考音频风格一致 |
| 站位漂移 | 用场景360度视频做 `--ref-video`，prompt 中声明保持站位一致 |
| 道具不一致 | 生成道具参考图，在 prompt 中绑定 `道具名@图片N` |

## 推荐目录结构

```
项目名/
├── 角色/
│   ├── <角色名>_face.jpg                    # 面部特写（占画面80%）
│   ├── <角色名>_fullbody.jpg                # 全身参考（含服装道具）
│   ├── <角色名>_voice_ref.mp4               # 音色参考视频（5秒，转身+说台词）
│   ├── <角色名>_<妆造名>_face.jpg           # 妆造变化：该造型面部特写（如有）
│   ├── <角色名>_<妆造名>_fullbody.jpg       # 妆造变化：该造型全身（如有）
│   └── <角色名>_<妆造名>_voice_ref.mp4      # 妆造变化：该造型音色参考（如有）
├── 场景/
│   ├── <场景名>.jpg                          # 场景参考图
│   └── <场景名>_360.mp4                      # 场景360度旋转视频
├── 道具/
│   └── <道具名>.jpg                          # 道具参考图（纯白背景）
├── assets.json                               # 记录角色/场景/道具/妆造的完整资产映射
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
