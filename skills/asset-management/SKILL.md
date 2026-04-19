---
name: asset-management
description: 管理火山方舟素材资产库（Assets：图片/音频/视频），通过 asset:// 引用喂给 Seedance 2.0 多模态视频生成，解决真人肖像审核 + 妆造漂移 + 音色漂移三类问题。
homepage: https://www.volcengine.com/product/ark
metadata: {}
---

# 素材资产管理（Assets）— 真人剧制作关键能力

## 核心作用

Seedance 2.0 reference-to-video 模型支持单次请求混传 ≤9 张图 + ≤3 段视频 + ≤3 段音频。Assets API 提供**可信素材通道**：把素材入库后用 `asset://<id>` 引用，相比直接传 URL 有三大好处：

1. **绕过逐次内容审核** —— 避免"图片包含真人"拦截
2. **统一管理跨集复用素材** —— 角色三视图、音色样本、参考视频一次入库多集复用
3. **作为多模态参考素材的稳定通道** —— `reference_image / reference_video / reference_audio` 都接受 `asset://`

## 前置条件

```bash
export VOLC_ACCESSKEY="你的火山引擎 Access Key"
export VOLC_SECRETKEY="你的火山引擎 Secret Key"
export CHANGDU_TOS_BUCKET="你的TOS桶名"         # asset-create --file 需要
export CHANGDU_ARK_API_KEY="你的火山方舟API Key"  # 视频生成需要
```

## 完整工作流（真人剧）

### 1. 创建素材组

每个项目/角色组创建一个 Asset Group：

```bash
changdu asset-group-create --name "寸金入骨-角色组"
```

返回 `素材组ID: group-2026xxxx-xxxxx`。

### 2. 上传图片素材入库（妆造抗穿帮关键）

上传面部特写、三视图、服装细节等。每种参考**单独一张图**效果最佳：

```bash
# 从本地文件上传（自动走 TOS）
changdu asset-create --file ./角色/女主_面部特写.jpg --group-id <素材组ID> --type Image --name "沈锦-面部"
changdu asset-create --file ./角色/女主_三视图.jpg --group-id <素材组ID> --type Image --name "沈锦-妆造"
changdu asset-create --file ./场景/会议室.jpg --group-id <素材组ID> --type Image --name "会议室场景"

# 从 URL 上传
changdu asset-create --url "https://example.com/actor.jpg" --group-id <素材组ID> --type Image
```

命令默认 `--wait`，等待处理完成后返回引用 URL：

```
素材ID: asset-2026xxxx-xxxxx  状态: 可用
引用URL: asset://asset-2026xxxx-xxxxx
```

### 3. 上传音色样本入库（VOICE 抗穿帮关键）

主角的音色样本入库后，在每段 clip 生成时用 `--voice-asset` 或 `--ref-audio` 引用，是消除"音色每段不同"穿帮的核心手段。

#### 3.1 已有外部音频文件

```bash
changdu asset-create \
  --file ./音色/沈锦_台词样本.mp3 \
  --group-id <素材组ID> \
  --type Audio \
  --name "沈锦-音色v1"
```

#### 3.2 一键从已生成的视频里抽音色 + 入库（推荐）

如果第一段视频已经生成，并且其中的音色满意，可以一键完成"抽音色 → 上传 TOS → 入库 Audio Asset"：

```bash
changdu voice-asset-from-clip \
  --input ./单集制作/EP001/视频_Clip001.mp4 \
  --group-id <素材组ID> \
  --start 6 --duration 8 \
  --name "沈锦-音色-from-Clip001"
```

输出包含可直接复用的 ID：

```
音色 Asset ID: asset-xxxxxxxx
asset:// 引用: asset://asset-xxxxxxxx
复用方式：
  changdu sequential-generate ... --voice-asset asset-xxxxxxxx
  changdu multimodal2video ... --ref-audio asset-xxxxxxxx
```

#### 3.3 音色样本注意事项

- 时长 2-15s，建议 6-10s
- 必须是单一说话人，背景越干净越好（避免 BGM 混入）
- 同一个角色建议入库 1-2 个音色样本，不要超过 3 个

### 4. 上传参考视频入库（运镜/动作模板，可选）

如果有"想要的运镜风格""指定的动作动力学"等参考视频，也可以入库后用 `--ref-video` 引用：

```bash
changdu asset-create \
  --file ./参考视频/慢推镜样本.mp4 \
  --group-id <素材组ID> \
  --type Video \
  --name "运镜-慢推"
```

注意视频参考素材：
- 时长 ≤ 15s，文件 ≤ 50MB
- 模型会"借鉴"画面风格、运镜节奏、人物动作的动力学，但不会照抄画面内容
- 必须在 prompt 的【视频参考说明】块用自然语言告诉模型该 ref_video 的"语义角色"，否则可能出现内容串流

### 5. 用素材生成真人视频（多模态混传）

在视频生成命令中用 `--asset` 替代 `--image`，并叠加 `--ref-video` / `--ref-audio` / `--voice-asset`：

```bash
changdu multimodal2video \
  --asset asset-2026xxxx-face \
  --asset asset-2026xxxx-costume \
  --asset asset-2026xxxx-scene \
  --ref-video asset-2026xxxx-prevtail \
  --voice-asset asset-2026xxxx-voice \
  --prompt "图片1的女孩（妆造参考图片2）站在图片3的场景中。视频1 是上一段尾段，仅做妆造与位置参考。音轨1 锁音色。$(cat 视频_Clip004.prompt.txt)" \
  --ratio 16:9 --duration 15 --wait --output clip004.mp4
```

也可混合使用 `--image` 和 `--asset`：

```bash
changdu multimodal2video \
  --asset asset-2026xxxx-face \
  --image ./新场景.jpg \
  --prompt "图片1的女孩站在图片2的场景中" \
  --wait --output clip.mp4
```

### 6. 查询与管理

```bash
# 查看素材状态（图片/音频/视频通用）
changdu asset-get --id <素材ID>

# 列出全部素材
changdu asset-list

# 按素材组过滤
changdu asset-list --group-id <素材组ID>

# 列出素材组
changdu asset-group-list

# 删除素材
changdu asset-delete --id <素材ID>
```

## 最佳实践（人物一致性 + 妆造一致性 + 音色一致性）

根据官方文档，上传素材时应**拆分上传**以提高模型识别精度：

| 素材类型 | 说明 | 建议 | 抗穿帮维度 |
|----------|------|------|---------|
| 图：面部特写 | 无表情、正面、高清 | 必须单独一张 | CHARACTER |
| 图：妆造三视图 | 正面+侧面+背面 | 建议单独一张 | MAKEUP |
| 图：服装细节 | 特写 | 可选单独一张 | PROP |
| 图：场景参考 | 背景环境 | 单独一张 | SCENE |
| 音：音色样本 | 6-10s 干净人声 | 主角 1-2 段 | VOICE |
| 视：前段尾段 | ≤5s 自动抽取 | 由 `clip-extract-tail` 产出 | CHARACTER+MAKEUP+SCENE 三合一 |
| 视：运镜模板 | ≤15s 风格参考 | 可选 | DETAIL（运镜风格） |

Prompt 中使用 `图片1` / `视频1` / `音轨1` 指代素材，**顺序与 `--asset` / `--ref-video` / `--ref-audio` 传入顺序一致**；同时建议在 prompt 内的【视频参考说明】【音色锚定】块用自然语言告诉模型每个素材的语义角色。

## 约束

- 图片素材应为虚拟人像，不得与真实自然人雷同。
- 每个上传的素材需经预处理（通常 3-10 秒），状态变为 `Active` 后方可使用。
- Asset API 使用 AK/SK 鉴权（非 API Key），视频生成 API 使用 API Key 鉴权。
- 素材的 ProjectName 需与 API Key 所属项目一致。
- 大小限制：单张图片 < 30MB，单个视频 < 50MB（2-15s），单个音频 < 15MB（2-15s）。
- 单次视频生成请求最多 9 张图 + 3 段视频 + 3 段音频。

## 关联技能

- `generate-video-by-seedance`：视频生成（配合 `--asset` / `--ref-video` / `--ref-audio` 参数）
- `upload-to-tos`：上传到 TOS（`asset-create --file` 内部依赖）
- `novel-to-video`：全流程工作流（真人剧路径，含音色样本入库流程）
- `video-review`：穿帮审查与修复（含 VOICE / MAKEUP 类）
