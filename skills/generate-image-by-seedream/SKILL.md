---
name: generate-image-by-seedream
description: 使用 changdu CLI 调用 Seedream 生成或编辑图片（文生图 / 图生图）。
homepage: https://www.volcengine.com/product/ark
metadata: {}
---

# Seedream 图像生成（统一走 changdu）

本技能统一使用 `changdu` CLI，不再调用独立脚本。

## 前置条件

```bash
test -n "$CHANGDU_ARK_API_KEY" || test -n "$ARK_API_KEY"
```

可选图片端点（在火山方舟控制台创建后设置）：

```bash
export CHANGDU_SEEDREAM_ENDPOINT="你的图像端点ID"
```

## 文生图

```bash
changdu text2image \
  --prompt "你的图片描述，需包含画幅和风格信息" \
  --resolution_type 2k \
  --output "输出.jpg"
```

## 图生图（多参考图）

```bash
changdu image2image \
  --image "/path/to/ref1.jpg" \
  --image "/path/to/ref2.png" \
  --prompt "将图1服装替换为图2风格" \
  --resolution_type 2k \
  --output "结果.jpg"
```

## 常用参数

- `--endpoint`：临时覆盖图片模型/端点 ID
- `--ratio`：附加画幅提示（如 `1:1`、`9:16`、`16:9`）
- `--resolution_type`：常用 `2k`
- `--output`：本地输出路径

## 约束

- 参考图必须是本地可读文件路径。
- 提示词需明确画风、主体动作和构图，避免过于抽象。
