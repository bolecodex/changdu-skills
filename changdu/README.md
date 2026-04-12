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

# 多图参考生视频
changdu multimodal2video \
  --image 角色.jpg --image 场景.jpg \
  --prompt "图1是主角，图2是场景。" \
  --ratio 16:9 --duration 15 --wait --output clip.mp4

# 查询任务
changdu query_result --submit_id <任务ID>

# 查看示例
changdu examples
```
