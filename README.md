# changdu-skills

基于 `changdu` CLI 的 AI 图像/视频生成技能包。通过火山方舟 Ark API 调用 Seedream（图像）和 Seedance（视频）模型。

## 一键安装

```bash
npx skills add bolecodex/changdu-skills -y -g
```

安装完成后，skills 会被写入 `~/.agents/skills/`。

## 安装 changdu CLI

skills 依赖 `changdu` 命令行工具，安装方式：

```bash
# 方式一：直接从 GitHub 安装（推荐）
pip install "changdu @ git+https://github.com/bolecodex/changdu-skills.git#subdirectory=changdu"

# 方式二：克隆后本地安装
git clone https://github.com/bolecodex/changdu-skills.git
cd changdu-skills/changdu
pip install .
```

或者运行仓库自带的一键安装脚本：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/bolecodex/changdu-skills/main/scripts/setup.sh)
```

## 配置

```bash
export CHANGDU_ARK_API_KEY="你的火山方舟API Key"

# 可选：指定端点
export CHANGDU_SEEDREAM_ENDPOINT="ep-m-xxxxx"    # 图像端点
export CHANGDU_SEEDANCE_ENDPOINT="ep-m-xxxxx"    # 视频端点
```

## 快速体验

```bash
# 文生图
changdu text2image --prompt "江南水乡，青瓦白墙，水墨画风" --output 水乡.jpg

# 文生视频
changdu text2video --prompt "电影感夜景街道，霓虹灯倒映在湿润地面" --ratio 16:9 --duration 15

# 多图参考生视频
changdu multimodal2video \
  --image 角色.jpg --image 场景.jpg \
  --prompt "图1是主角，图2是场景。主角在场景中行走。" \
  --ratio 16:9 --duration 15 --wait --output clip.mp4
```

## 包含的技能

| 技能 | 用途 |
|------|------|
| `jimeng-skill` | 统一生成入口（文生图/图生图/文生视频/多图生视频） |
| `generate-image-by-seedream` | Seedream 图像生成 |
| `generate-video-by-seedance` | Seedance 视频生成 |
| `novel-to-video` | 小说→影视视频全流程工作流 |
| `text-storyboard` | 文字分镜创作 |
| `storyboard-to-seedance-prompt` | 分镜→视频提示词 |
| `character-design` | 角色设计 |
| `novel-reader` | 小说读取与元素提取 |
| `ffmpeg-video-processing` | FFmpeg 视频处理 |

## 仓库结构

```
changdu-skills/
├── changdu/              # changdu CLI 源码（Python）
│   ├── pyproject.toml
│   └── src/changdu/
├── skills/               # openclaw 技能文件
│   ├── jimeng-skill/
│   ├── novel-to-video/
│   └── ...
├── scripts/
│   └── setup.sh          # 一键安装脚本
└── README.md
```

## License

MIT
