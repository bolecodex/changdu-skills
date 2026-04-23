---
name: anime-action-scene
description: 动漫武打短剧（≤30s）专项 prompt 写作与生成工作流。当需要做日漫/国漫风格的短打戏、追逐戏、对决戏，且要求段间动作与镜头无缝衔接时调用。配套使用 changdu sequential-generate（continuity-mode auto）+ clip-concat（--audio-fadein 消除底噪，crossfade + loudnorm 可选）。
tags: ["anime", "action", "fight", "short-form", "seedance"]
---

# 动漫武打短剧 · S 级连贯性工作流

## 目标

把 30s 以内的动漫武打戏（雪夜竹林、屋顶追击、刀剑对决、术式对轰等场景）拆成 5-7 段、每段 5-6s，最终拼成段间无突兀的成片。

S 级的 5 个硬指标：

1. 同一主角妆造（脸/服/武器/发型）全程一致
2. 同一音色（喘息、喊招、低声台词）全程一致
3. 武打动作首尾相接（前段落地姿态 = 本段起手姿态）
4. 镜头节奏成立（中景 → 特写 → 中景，不是六段都中景或都特写）
5. 段间画面与音频零突兀（crossfade + loudnorm + audio-fadein，**保留 Seedance 自带的人声/打斗音/环境音**）

> **音频策略说明**：Seedance 2.0 生成的音频轨在每段开头可能带有启动底噪（嗡嗡声），使用 `--audio-fadein 0.3` 对每段音频开头做淡入即可消除，无需丢弃整个音轨。仅在后期需要全量配音时才使用 `--strip-audio`。

---

## 何时调用本 skill

- 用户要做"30s 动漫武打/追逐/对决"
- 用户给的是写实风格但希望"动漫化"（anime / cel-shaded / Japanese animation）
- 上一次拼接结果不连贯（动作跳变、画面不衔接）

不适用：

- 写实人物特写（用 `storyboard-to-seedance-prompt`）
- 长剧情对话戏（武打 skill 重动作轻台词）
- 单段视频（直接 `multimodal2video` 即可）

---

## 为什么必须用动漫风（不要写实）

实测踩坑（参见 [`generate-video-by-seedance/SKILL.md`](../generate-video-by-seedance/SKILL.md) 的"已知 API 限制"）：

- Seedance 对**真人视频**安全审核敏感，把上一段尾段（含真人正脸或全身）回喂为 `reference_video` 时频繁被挡（`The request failed because the input video may contain real person`）
- 一旦被挡只能 fallback 到 `first_frame_url`，连贯性立刻塌一半
- **动漫/卡通风格基本不会触发该规则**，`ref_video` 链路畅通，6 段武打才能首尾相接

写 prompt 时**必须**在 prompt 顶部明确风格关键词：

```
【美术风格】日本动漫 / cel-shaded / Japanese animation / cinematic anime,
线条干净，明暗分明，有 motion line 与冲击帧，不是写实质感。
```

如果省略这块，模型经常默认走写实，前 2 段就能把 ref_video 链路打废。

---

## 6 段标准节奏（5s × 6 = 30s，crossfade 0.4s 后约 28s）

| Clip | 节奏 | 内容样式 | 镜头 |
|---|---|---|---|
| C1 | 起 · 对峙 | 双方就位，环境交代，气氛酝酿 | 中景缓推或环绕 |
| C2 | 承 · 攻方先动 | 一方掠出/出招，另一方应对 | 中景 → 特写（武器） |
| C3 | 转 · 短兵相接 | 兵器交击，火花/术式碰撞 | 中近景跟拍 |
| C4 | 转 · 反向反制 | 守方借力反击，攻方退守 | 低角度仰拍或侧拉 |
| C5 | 合 · 决定一击 | 一方命中或锁定胜势 | 特写 → 中景定格 |
| C6 | 收 · 余韵 | 收剑/转身/拉远，留白 | 拉远 + 静帧 |

5 段版（5 × 6s = 30s，crossfade 0.4s 后约 28s）：合并 C3 + C4 为"短兵 + 反击"在同一段，靠特写运镜串。

7 段版（7 × 4.5s = 31.5s，crossfade 0.4s 后约 29s）：在 C2 与 C3 之间插一段"前摇 / 蓄力"特写，节奏更有层次但成本高约 17%。

---

## 单 Clip Prompt 模板（必写 7 块）

每段都用同一个骨架，只换"分镜段"内容：

```
将图片1中的黑色皮甲、银边披风、长发束高马尾的女性定义为女主角。图片2为女主角全身参考。将图片3中的蒙面黑袍、红色腰带、露出眼部带血色伤疤的男性定义为反派。图片4为反派全身参考。图片5为场景参考。

【美术风格】日本动漫 / cel-shaded / cinematic anime, 线条干净, 明暗分明,
有 motion line 与冲击帧, 不是写实质感, 不是 3D 渲染。

【动作交接】上一段以 <X 姿态/位置/兵器朝向> 结束 → 本段从该姿态自然延续。
（C1 写"无前续，从静止对峙开始"。）

【音色锚定】采用音频1的清冽有力青年女声的音色（reference_audio）—— 喊招与喘息保持同一声线。

【镜头语言】<具体运镜：起幅 / 推拉 / 跟随 / 落幅>，<焦段提示：中景/特写>。

【场景与时间】<时间地点光线>，<环境元素>。

【分镜】女主角@图片1 <动作 1>。紧接着反派@图片3 <动作 2>。随后女主角@图片1 <收束姿态，必须可被下一段接>。
本段仅展示上述动作，不展示后续剧情。视频全程不要在同一画面中复制相同人物，不要多人同脸。保持无字幕，避免画面生成字幕，不要水印，不要logo，不要BGM。
```

`asset:char_woman_*` 是占位写法，实际值由 `asset-create` 后填入。

---

## 动作交接帧的 3 个写法

`【动作交接】` 是这套 skill 最核心的一行，决定段与段之间能否"咬住"。

**写法 1：姿态交接**（最常用）

- 上一段末"右脚前蹬，刀尖斜指地面"→ 本段起"右脚前蹬未收，刀身上撩"

**写法 2：兵器轨迹交接**

- 上一段末"刀光从右上向左下劈出，未到底"→ 本段起"刀光延续轨迹砸落，反派抬刀格挡"

**写法 3：镜头交接**

- 上一段末"镜头落幅在女主特写"→ 本段起"特写继续保持 0.5s 后切到反派同高度反打"

写法 3 必须配合 `crossfade-seconds 0.4` 才平滑，否则切镜会有跳帧感。

---

## 镜头语言对照（武打专用）

| 关键词 | 适用段 | 模型理解 |
|---|---|---|
| 中景缓推 | C1 起势 | 摄像机以稳定节奏靠近主体 |
| 跟随镜头 | C2/C3 出招 | 镜头随兵器轨迹运动 |
| 低角度仰拍 | C4/C5 决胜 | 强化反派的压迫或女主的英姿 |
| 冲击帧 (impact frame) | C3/C5 命中瞬间 | 短暂定格 + 全屏白光 + 速度线 |
| 拉远 + 留白 | C6 收尾 | 摄像机从近景拉至全景 |

不要全段都用 `dynamic camera`，节奏会塌。

---

## 实操：30s anime 武打 demo 一键流程

下面是配套的 changdu CLI 调用顺序，跟 `examples/run_30s_anime_action.sh` 一致。

### 1. 生 3 张 anime 参考图

```bash
changdu text2image \
  --prompt "anime cel-shaded three-view of a young female swordsman, ..." \
  --output ./outputs/demo_anime_action/refs/char_woman_swordsman_threeview.jpg \
  --resolution_type 2k

changdu text2image \
  --prompt "anime cel-shaded three-view of a masked assassin, ..." \
  --output ./outputs/demo_anime_action/refs/char_villain_assassin_threeview.jpg \
  --resolution_type 2k

changdu text2image \
  --prompt "anime cel-shaded background of a snowy bamboo forest at night, ..." \
  --output ./outputs/demo_anime_action/refs/scene_bamboo_snow_night.jpg \
  --resolution_type 2k
```

### 2. 资产入库

```bash
GROUP_ID=$(changdu asset-create --name "anime-action-30s" | awk '/^GroupID:/ {print $2}')
changdu asset-upload-images --group-id $GROUP_ID \
  --image ./outputs/demo_anime_action/refs/char_woman_swordsman_threeview.jpg \
  --image ./outputs/demo_anime_action/refs/char_villain_assassin_threeview.jpg \
  --image ./outputs/demo_anime_action/refs/scene_bamboo_snow_night.jpg --type Image
```

### 3. 写 6 段 prompt

每段一个文件 `prompts/视频_Clip00{1..6}.prompt.txt`，按上面的 7 块模板填。

### 3.5（可选）生成角色音色参考视频

在生成 clip 之前，先为主角生成一段音色参考视频，后续所有 clip 自动锚定该音色：

```bash
changdu multimodal2video \
  --image ./outputs/demo_anime_action/refs/char_woman_swordsman_threeview.jpg \
  --prompt "日本动漫cel-shaded风格。女剑士缓缓转身展示全身，然后开口喊道{覆刃·斩月}，声音清冽有力。" \
  --ratio 16:9 --duration 5 --wait \
  --output ./outputs/demo_anime_action/refs/char_woman_voice_ref.mp4

changdu upload-tos --file ./outputs/demo_anime_action/refs/char_woman_voice_ref.mp4
```

### 4. 顺序生成（auto 模式自动 fallback）

**方式 A：使用音色参考视频（推荐）**

```bash
changdu sequential-generate \
  --prompt-dir ./outputs/demo_anime_action/prompts \
  --image ./outputs/demo_anime_action/refs/char_woman_swordsman_threeview.jpg \
  --image ./outputs/demo_anime_action/refs/char_villain_assassin_threeview.jpg \
  --image ./outputs/demo_anime_action/refs/scene_bamboo_snow_night.jpg \
  --ref-audio <女主_voice_ref_TOS_URL> \
  --duration 5 \
  --continuity-mode auto \
  --output-dir ./outputs/demo_anime_action/clips
```

使用步骤 3.5 生成的音色参考视频 TOS URL，每个 clip 都会自动附加该音频作为 `reference_audio`。即使 `auto` 模式触发 fallback（降级为 first_frame_url），音色锚定仍然保留。

**方式 B：从第 1 段自动提取音色（传统方式）**

```bash
changdu sequential-generate \
  --prompt-dir ./outputs/demo_anime_action/prompts \
  --image ./outputs/demo_anime_action/refs/char_woman_swordsman_threeview.jpg \
  --image ./outputs/demo_anime_action/refs/char_villain_assassin_threeview.jpg \
  --image ./outputs/demo_anime_action/refs/scene_bamboo_snow_night.jpg \
  --duration 5 \
  --continuity-mode auto \
  --voice-from-clip 1 \
  --voice-group-id $GROUP_ID \
  --output-dir ./outputs/demo_anime_action/clips
```

`voice-from-clip 1` 从 C1 抽 6-12s 音色样本，asset 入库失败时回退 TOS URL。缺点：C1 的音色质量不确定，且 fallback 模式下音色锚定可能丢失。

### 5. 拼接（保留原声 + 消除底噪）

```bash
changdu clip-concat \
  --input-dir ./outputs/demo_anime_action/clips \
  --output ./outputs/demo_anime_action/final.mp4 \
  --audio-fadein 0.3
```

`--audio-fadein 0.3` 对每段音频开头做 0.3 秒淡入，消除 Seedance 启动底噪，同时保留喊招、打斗音效和环境音。仅在后期需要全量配音时才使用 `--strip-audio`。

---

## 常见踩坑

### 踩坑 1: 第 3 段开始角色脸变形

**原因**：ref_video 没生效（被审核挡走 fallback），ref_image 又没传齐。

**修复**：所有段都传 `--image <三视图>`，`auto` 模式 fallback 时也保留 ref_image。

### 踩坑 2: 武器形态每段都不一样

**原因**：prompt 里只写了"持刀"没写形制。

**修复**：在【角色锚定】写清"双手单刀，刀身长 90cm，刀镡为牡丹纹"，三视图也要画清楚。

### 踩坑 3: 段与段之间动作明显跳

**原因**：【动作交接】写得太空，模型自由发挥。

**修复**：必须写出"上一段末的具体姿态"和"本段起手的具体姿态"，且两者衔接合理（不能上一段刚劈下来本段又抬手起势）。

### 踩坑 4: 每段衔接处有嗡嗡底噪

**原因**：Seedance 2.0 生成的音频轨在每段开头带有启动底噪，拼接后在衔接处尤为明显。

**修复**：使用 `changdu clip-concat --audio-fadein 0.3` 对每段音频开头做淡入处理，消除底噪同时保留原声。仅在后期需要全量配音时才使用 `--strip-audio`。

### 踩坑 5: 写实风格的段被审核挡

**原因**：prompt 没强调 anime / cel-shaded。

**修复**：每段顶部都写【美术风格】块，不只是第 1 段。

---

## 与其他 skills 的关系

- 上游：[`character-design`](../character-design/SKILL.md) 提供角色设计标准
- 上游：[`storyboard-to-seedance-prompt`](../storyboard-to-seedance-prompt/SKILL.md) 提供 prompt 结构
- 同级：[`generate-video-by-seedance`](../generate-video-by-seedance/SKILL.md) 提供 API 限制与多模态字段
- 下游：[`video-postproduction`](../video-postproduction/SKILL.md) 提供 crossfade / loudnorm 后期细节
- 旁路：[`asset-management`](../asset-management/SKILL.md) 提供资产组与音色 asset 复用
