#!/usr/bin/env bash
# ============================================================
#  changdu Seedance 2.0 一致性 3-clip 端到端 Demo
#  - 用一张主角三视图 + 自动音色锁定，跑 3 段连贯视频
#  - 演示：multimodal2video + voice-asset-from-clip + sequential-generate(ref_video)
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# 1) 加载 .env
if [[ ! -f .env ]]; then
  echo "[!] 缺少 .env，请先 cp .env.example .env 并填入 ARK Key / TOS 配置" >&2
  exit 1
fi
set -a; . ./.env; set +a

# 2) 让本地静态 ffmpeg / Python 3.11 venv 在 PATH 里
export PATH="$HOME/.local/bin:$PATH"
CHANGDU="$REPO_ROOT/.venv-3.11/bin/changdu"
if [[ ! -x "$CHANGDU" ]]; then
  echo "[!] 找不到 .venv-3.11/bin/changdu，请先 uv venv .venv-3.11 --python 3.11 && uv pip install -e ./changdu" >&2
  exit 1
fi

DEMO_DIR="$REPO_ROOT/outputs/demo_3clip"
REF_IMG="$DEMO_DIR/refs/char_lin_threeview.jpg"
PROMPT_DIR="$DEMO_DIR/prompts"
CLIPS_DIR="$DEMO_DIR/clips"
mkdir -p "$CLIPS_DIR"

if [[ ! -f "$REF_IMG" ]]; then
  echo "[!] 缺少角色三视图 $REF_IMG" >&2
  exit 1
fi

# 3) 创建 asset group（如果脚本被多次调用，只在 .group_id 缺失时建）
GROUP_FILE="$DEMO_DIR/.group_id"
if [[ ! -f "$GROUP_FILE" ]]; then
  echo "[1/5] 创建 asset group..."
  GROUP_OUT=$("$CHANGDU" asset-group-create --name "demo-3clip-林" --description "Seedance 2.0 一致性 demo 主角资产")
  echo "$GROUP_OUT"
  GROUP_ID=$(echo "$GROUP_OUT" | sed -n 's/.*\(group-[A-Za-z0-9_-]\{6,\}\).*/\1/p' | head -1)
  if [[ -z "$GROUP_ID" ]]; then
    echo "[!] 无法从输出解析 group_id，请手动填入 $GROUP_FILE" >&2
    exit 1
  fi
  echo "$GROUP_ID" > "$GROUP_FILE"
else
  GROUP_ID=$(cat "$GROUP_FILE")
fi
echo "  asset_group: $GROUP_ID"

# 4) 上传角色三视图为 image asset（如果还没有）
ASSET_FILE="$DEMO_DIR/.char_asset_id"
if [[ ! -f "$ASSET_FILE" ]]; then
  echo "[2/5] 上传角色三视图为 image asset..."
  ASSET_OUT=$("$CHANGDU" asset-create \
    --group-id "$GROUP_ID" \
    --type Image \
    --file "$REF_IMG" \
    --name "char-lin-threeview")
  echo "$ASSET_OUT"
  CHAR_ASSET=$(echo "$ASSET_OUT" | sed -n 's/.*\(asset-[A-Za-z0-9_-]\{6,\}\).*/\1/p' | head -1)
  if [[ -z "$CHAR_ASSET" ]]; then
    echo "[!] 无法解析 asset_id" >&2
    exit 1
  fi
  echo "$CHAR_ASSET" > "$ASSET_FILE"
else
  CHAR_ASSET=$(cat "$ASSET_FILE")
fi
echo "  char_asset: $CHAR_ASSET"

# 5) 跑 sequential-generate：3 段 + 自动从 clip1 抽音色 + ref_video 衔接
echo "[3/5] 顺序生成 3 段（continuity-mode=ref_video, voice-from-clip=1）..."
"$CHANGDU" sequential-generate \
  --prompt-dir "$PROMPT_DIR" \
  --output-dir "$CLIPS_DIR" \
  --asset "$CHAR_ASSET" \
  --voice-from-clip 1 \
  --voice-group-id "$GROUP_ID" \
  --continuity-mode ref_video \
  --prev-tail-seconds 3.0 \
  --duration 5 \
  --quality 720p \
  --ratio 16:9

# 6) 拼接成片
echo "[4/5] 拼接成片..."
FINAL_MP4="$DEMO_DIR/final.mp4"
"$CHANGDU" clip-concat --input-dir "$CLIPS_DIR" --output "$FINAL_MP4" || {
  echo "[!] clip-concat 失败，尝试 ffmpeg fallback..."
  CONCAT_LIST=$(mktemp)
  for f in "$CLIPS_DIR"/视频_Clip*.mp4; do
    echo "file '$f'" >> "$CONCAT_LIST"
  done
  ffmpeg -y -f concat -safe 0 -i "$CONCAT_LIST" -c copy "$FINAL_MP4"
}

# 7) 汇报
echo "[5/5] 完成！"
echo "  asset group: $GROUP_ID"
echo "  char asset:  $CHAR_ASSET"
echo "  voice asset: 见 sequential-generate 输出（保存在 $CLIPS_DIR/_voice_asset_id.txt 如果有）"
echo "  clips:       $CLIPS_DIR/视频_Clip{001,002,003}.mp4"
echo "  final:       $FINAL_MP4"
