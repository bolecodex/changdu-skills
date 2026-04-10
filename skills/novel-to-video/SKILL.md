---
name: novel-to-video
description: 文学作品到影视视频的自然语言工作流；生成链路统一使用 changdu CLI。
---

# 文学作品到影视视频工作流（changdu 版）

## 核心任务

将小说/故事/剧本转换为完整视频，严格按技能链路执行，不跳步。

## 必须学习的技能

- `novel-reader`：读取与提取角色/场景/道具
- `text-storyboard`：生成文字分镜
- `generate-film-video-prompt`：补强视频提示词
- `storyboard-to-seedance-prompt`：分镜转视频提示词
- `character-design`：角色设计提示词
- `jimeng-skill`：统一生成入口（内部统一走 `changdu` CLI）

## 全局要求

- 开始前先确认画风与比例（默认 `16:9`）。
- 漫剧/条漫场景必须使用非写实描述（赛璐璐、线稿平涂、动漫设定稿）。
- 所有图像与视频生成都通过 `changdu` 执行。

## 工作流（严格顺序）

1. **读取文本**：使用 `novel-reader` 提取角色、场景、道具。
2. **文字分镜**：使用 `text-storyboard` 输出 `单集制作/EPXXX/文字分镜.txt`。
3. **生成角色图**：
   - 先产出 `角色/角色名.prompt.txt`
   - 再执行 `changdu text2image ... --output 角色/角色名.jpg`
4. **生成场景/道具图**：
   - 先产出对应 `*.prompt.txt`
   - 再执行 `changdu text2image ... --output 场景/xxx.jpg` 或 `道具/xxx.jpg`
5. **校验资产**：确认角色/场景/道具图片都已存在，否则禁止进入视频阶段。
6. **生成每个 clip**：
   - 调用 `storyboard-to-seedance-prompt` 产出 `视频_ClipXXX.prompt.txt`
   - 执行 `changdu multimodal2video ... --wait --output 视频_ClipXXX.mp4`
7. **拼接成片**：使用 ffmpeg 拼接全部 clip。

## 推荐目录结构

```
项目名/
├── 角色/
├── 场景/
├── 道具/
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
