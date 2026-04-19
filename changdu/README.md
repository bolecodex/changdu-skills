# changdu

火山方舟 Seedream / Seedance 图像视频生成 CLI。

- 图像生成：Seedream（文生图、图生图）
- 视频生成：Seedance 2.0（文生视频、多图参考视频）

## 安装

```bash
# 从 GitHub 安装
pipx install "changdu @ git+https://github.com/bolecodex/changdu-skills.git#subdirectory=changdu"

# 或本地安装
cd changdu
pip install .
```

## 环境变量

```bash
# 必需
export CHANGDU_ARK_API_KEY="你的火山方舟API Key"

# 可选端点（在火山方舟控制台创建，不设置则使用模型名直连）
export CHANGDU_SEED_TEXT_ENDPOINT="你的文本端点ID"
export CHANGDU_SEEDREAM_ENDPOINT="你的图像端点ID"
export CHANGDU_SEEDANCE_ENDPOINT="你的视频端点ID"

# 可选基础地址
export CHANGDU_ARK_BASE_URL="https://ark.cn-beijing.volces.com"
```

`ARK_API_KEY` 也可作为 fallback。

也可以通过命令行参数临时覆盖：

```bash
changdu --api-key "xxx" --seedream-endpoint "ep-xxx" auth check
```

## 快速开始

```bash
# 验证配置
changdu auth check

# 文生图
changdu text2image --prompt "江南水乡，水墨画风" --output 水乡.jpg

# 文生视频
changdu text2video --prompt "夜景街道，电影感" --ratio 16:9 --duration 15 --wait --output clip.mp4

# 多模态参考生视频（图 + 视频 + 音频）
changdu multimodal2video \
  --image 角色.jpg --image 场景.jpg \
  --ref-video ./单集制作/EP001/视频_Clip003.mp4 \
  --voice-asset asset-xxxxxxxx \
  --prompt "图1是主角，图2是场景。视频1 是上一段尾段，仅作妆造与位置参考。音轨1 锁音色。" \
  --ratio 16:9 --duration 15 --wait --output clip004.mp4

# 查询任务
changdu query_result --submit_id <任务ID>

# 查看示例
changdu examples
```

## Seedance 2.0 多模态新特性（v0.2 起）

| 能力 | 命令 / 参数 |
|------|-------------|
| 参考视频（最多 3 段，每段 ≤15s） | `--ref-video <path/url/asset-id>` |
| 参考音频（最多 3 段，每段 ≤15s） | `--ref-audio <path/url/asset-id>` |
| 音色锁定（reference_audio 别名） | `--voice-asset <asset-id>` |
| 尾帧驱动 | `--last-frame-url <url>` |
| 禁用同步音频 | `--no-audio` |
| 指定输出分辨率 | `--quality 480p/720p/1080p` |
| 抽前段尾段做下一段 reference_video | `changdu clip-extract-tail -i a.mp4 --tail-seconds 5` |
| 从视频提取音色样本 | `changdu voice-extract -i a.mp4 --start 6 --duration 8` |
| 一键音色 → TOS → 入库 Audio Asset | `changdu voice-asset-from-clip -i a.mp4 --group-id <组ID>` |
| 连续生成（默认 ref_video 衔接 + 音色复用） | `changdu sequential-generate --continuity-mode ref_video --voice-asset <id>` |
| 自动在第 N 段后入库音色，从 N+1 起复用 | `changdu sequential-generate --voice-from-clip 1 --voice-group-id <组ID>` |
