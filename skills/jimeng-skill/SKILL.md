---
name: jimeng-skill
description: 统一使用 changdu CLI 调用火山方舟 Seedream / Seedance，实现即梦同类图像与视频生成能力。
---

# changdu 统一生成技能

## 目标

- 生图与生视频统一走 `changdu` CLI。
- 默认能力：
  - 图像：Seedream
  - 视频：Seedance 2.0

## 前置条件

```bash
test -n "$CHANGDU_ARK_API_KEY" || test -n "$ARK_API_KEY"
```

推荐端点（可按项目覆盖）：

```bash
export CHANGDU_SEED_TEXT_ENDPOINT="ep-m-20260328105436-n2x7w"
export CHANGDU_SEEDREAM_ENDPOINT="ep-m-20260403105201-9p9g6"
export CHANGDU_SEEDANCE_ENDPOINT="ep-m-20260326222518-52x8x"
```

## 生图

文生图：

```bash
changdu text2image \
  --prompt "你的提示词，明确比例和画风" \
  --resolution_type 2k \
  --output "输出.jpg"
```

图生图：

```bash
changdu image2image \
  --image "/path/to/a.jpg" \
  --image "/path/to/b.jpg" \
  --prompt "将图1风格调整为图2风格" \
  --resolution_type 2k \
  --output "结果.jpg"
```

## 生视频

文生视频：

```bash
changdu text2video \
  --prompt "电影感夜景街道，16:9" \
  --ratio 16:9 \
  --duration 15
```

多图参考生视频：

```bash
HEAD="图1是女主参考，图2是男主参考，图3是场景参考。"
changdu multimodal2video \
  --image "./角色/女主.jpg" \
  --image "./角色/男主.jpg" \
  --image "./场景/场景.jpg" \
  --prompt "${HEAD}$(python3 -c 'print(open(\"视频_Clip001.prompt.txt\",encoding=\"utf-8\").read())')" \
  --ratio 16:9 \
  --duration 15 \
  --wait \
  --output "./单集制作/EP001/视频_Clip001.mp4"
```

## 任务查询

```bash
changdu query_result --submit_id <任务ID>
changdu query_result --submit_id <任务ID> --wait --output "结果.mp4"
```

## 错误处理

- 鉴权失败：检查 `CHANGDU_ARK_API_KEY`。
- 端点无权限：检查对应 `CHANGDU_SEEDREAM_ENDPOINT` / `CHANGDU_SEEDANCE_ENDPOINT` 是否可用。
- 多图一致性差：固定参考图顺序，且 prompt 明确“图1/图2/图3”角色关系。
