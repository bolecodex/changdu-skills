---
name: upload-to-tos
description: 使用 changdu CLI 将生成好的图片或视频上传到火山引擎 TOS 对象存储，获取公开访问 URL。
homepage: https://www.volcengine.com/product/tos
metadata: {}
---

# 上传文件到 TOS（changdu upload）

使用 `changdu upload` 命令将本地文件上传到火山引擎 TOS 对象存储桶，并返回公开可访问的 URL。

## 前置条件

1. 确保已安装 changdu CLI。
2. 设置火山引擎 AK/SK 和 TOS 桶信息：

```bash
export VOLC_ACCESSKEY="你的火山引擎 Access Key"
export VOLC_SECRETKEY="你的火山引擎 Secret Key"
export CHANGDU_TOS_BUCKET="你的TOS桶名"
```

可选配置：

```bash
export CHANGDU_TOS_ENDPOINT="tos-cn-beijing.volces.com"   # 默认北京
export CHANGDU_TOS_REGION="cn-beijing"                     # 默认北京
```

## 上传单个文件

```bash
changdu upload ./outputs/clip.mp4
```

默认以文件名作为对象 Key，ACL 为公开读，上传后直接返回 URL。

## 指定前缀（归类到目录）

```bash
changdu upload ./outputs/clip001.mp4 --prefix "videos/ep001/"
```

上传后对象 Key 为 `videos/ep001/clip001.mp4`。

## 上传图片

```bash
changdu upload ./outputs/poster.jpg --prefix "images/"
```

## 自定义 Key

```bash
changdu upload ./outputs/final.mp4 --key "drama/寸金入骨/ep001.mp4"
```

## 上传为私有文件

```bash
changdu upload ./outputs/clip.mp4 --private
```

私有文件不会生成公开 URL，需要通过签名访问。

## 批量上传（结合 Shell）

```bash
for f in ./outputs/*.mp4; do
  changdu upload "$f" --prefix "videos/batch/"
done
```

## 常用参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `FILE` | 要上传的本地文件路径（必填） | — |
| `--bucket` | TOS 桶名（或 `CHANGDU_TOS_BUCKET`） | — |
| `--key` | 自定义对象 Key | 文件名 |
| `--prefix` | Key 前缀（如 `videos/`） | 空 |
| `--public / --private` | 访问权限 | `--public` |
| `--ak` | Access Key（或 `VOLC_ACCESSKEY`） | — |
| `--sk` | Secret Key（或 `VOLC_SECRETKEY`） | — |
| `--tos-endpoint` | TOS 端点（或 `CHANGDU_TOS_ENDPOINT`） | `tos-cn-beijing.volces.com` |
| `--region` | 地域（或 `CHANGDU_TOS_REGION`） | `cn-beijing` |

## 输出示例

```
桶: my-bucket
Key: videos/ep001/clip001.mp4
URL: https://my-bucket.tos-cn-beijing.volces.com/videos/ep001/clip001.mp4
状态: 上传成功
```

## 典型工作流

1. 用 changdu 生成视频：

```bash
changdu text2video --prompt "夜景街道，电影感" --wait --output ./out/clip.mp4
```

2. 上传到 TOS 获取 URL：

```bash
changdu upload ./out/clip.mp4 --prefix "videos/"
```

3. 使用返回的 URL 进行后续分发或嵌入。

## 约束

- 上传前文件必须存在，否则报错。
- 同名对象会被覆盖（除非桶开启了版本控制）。
- AK/SK 需具有 `tos:PutObject` 权限。
