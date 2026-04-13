---
name: asset-management
description: 管理火山方舟素材资产库（Assets），将人物参考图入库后通过 asset:// 引用生成真人剧视频，解决真人肖像内容审核问题。
homepage: https://www.volcengine.com/product/ark
metadata: {}
---

# 素材资产管理（Assets）— 真人剧制作关键能力

## 核心作用

Seedance 2.0 对直接传入的真人照片会进行内容安全审核，可能导致"图片包含真人"拦截。
Assets API 提供**可信素材通道**：将虚拟人像素材入库后获得 Asset ID，以 `asset://<id>` 引用生成视频，绕过逐次审核。

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

### 2. 上传角色素材入库

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

### 3. 用素材生成真人视频

在视频生成命令中用 `--asset` 替代 `--image`：

```bash
changdu multimodal2video \
  --asset asset-2026xxxx-face \
  --asset asset-2026xxxx-costume \
  --asset asset-2026xxxx-scene \
  --prompt "图片1的女孩（妆造参考图片2）站在图片3的场景中，缓缓转身微笑" \
  --ratio 16:9 --duration 15 --wait --output clip001.mp4
```

也可混合使用 `--image` 和 `--asset`：

```bash
changdu multimodal2video \
  --asset asset-2026xxxx-face \
  --image ./新场景.jpg \
  --prompt "图片1的女孩站在图片2的场景中" \
  --wait --output clip.mp4
```

### 4. 查询与管理

```bash
# 查看素材状态
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

## 最佳实践（人物一致性）

根据官方文档，上传素材时应**拆分上传**以提高模型识别精度：

| 素材类型 | 说明 | 建议 |
|----------|------|------|
| 面部特写 | 无表情、正面、高清 | 必须单独一张 |
| 妆造三视图 | 正面+侧面+背面 | 建议单独一张 |
| 服装细节 | 特写 | 可选单独一张 |
| 场景参考 | 背景环境 | 单独一张 |

Prompt 中使用 `图片1`、`图片2` 指代素材，**顺序与 `--asset` 传入顺序一致**。

## 约束

- 素材必须为虚拟人像，不得与真实自然人雷同。
- 每个上传的素材需经预处理（通常 3-10 秒），状态变为 `Active` 后方可使用。
- Asset API 使用 AK/SK 鉴权（非 API Key），视频生成 API 使用 API Key 鉴权。
- 素材的 ProjectName 需与 API Key 所属项目一致。
- 单张图片 < 30MB，单个视频 < 50MB（2-15秒），单个音频 < 15MB（2-15秒）。

## 关联技能

- `generate-video-by-seedance`：视频生成（配合 `--asset` 参数）
- `upload-to-tos`：上传到 TOS（`asset-create --file` 内部依赖）
- `novel-to-video`：全流程工作流（真人剧路径）
