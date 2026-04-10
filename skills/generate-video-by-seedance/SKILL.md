---
name: generate-video-by-seedance
description: 使用 changdu CLI 调用 Seedance 生成视频（文生视频 / 图生视频 / 多图参考视频）。
homepage: https://www.volcengine.com/product/ark
metadata: {}
---

# Seedance 视频生成（统一走 changdu）

本技能统一使用 `changdu` CLI，不再调用独立脚本。

## 前置条件

```bash
test -n "$CHANGDU_ARK_API_KEY" || test -n "$ARK_API_KEY"
```

可选视频端点：

```bash
export CHANGDU_SEEDANCE_ENDPOINT="ep-m-20260326222518-52x8x"
```

## 文生视频

```bash
changdu text2video \
  --prompt "电影感夜景街道，镜头缓慢推进" \
  --ratio 16:9 \
  --duration 15
```

## 多图参考生视频

```bash
changdu multimodal2video \
  --image "/path/to/角色1.jpg" \
  --image "/path/to/角色2.jpg" \
  --image "/path/to/场景.jpg" \
  --prompt "图1为角色A，图2为角色B，图3为场景。按分镜生成。" \
  --ratio 16:9 \
  --duration 15 \
  --wait \
  --output "视频_Clip001.mp4"
```

## 查询任务状态

```bash
changdu query_result --submit_id <任务ID>
```

等待并下载：

```bash
changdu query_result --submit_id <任务ID> --wait --output "视频_Clip001.mp4"
```

## 常用参数

- `--model`：临时覆盖视频模型/端点 ID
- `--ratio`：画面比例（`16:9` / `9:16` / `1:1`）
- `--duration`：视频时长（秒）
- `--wait`：提交后等待到终态
- `--output`：等待成功后保存路径

## 约束

- 多图参考的顺序必须与 prompt 中“图1/图2/图3”描述一致。
- 若追求角色一致性，建议固定角色参考图并复用同一视频端点。
