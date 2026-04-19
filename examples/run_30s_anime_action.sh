#!/usr/bin/env bash
# ============================================================
#  changdu Seedance 2.0 · 30s 动漫武打 · S 级连贯性 Demo
#
#  6 段 × 5s anime 风武打：
#    - 自动生 3 张 anime 参考图（角色 + 反派 + 场景）
#    - sequential-generate (continuity-mode auto + voice-from-clip 1)
#    - 升级版 clip-concat：crossfade 0.4s + loudnorm
#    - 不叠加任何外部 BGM —— 只用 Seedance 自带的人声/环境/打斗音
#
#  环境变量：
#    SKIP_REF_GEN=1      跳过参考图生成（已有时）
#    SKIP_CLIP_GEN=1     跳过 clip 生成（已有时）
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
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[!] 找不到 ffmpeg，请先安装（推荐 brew 或下载静态 build 到 ~/.local/bin/）" >&2
  exit 1
fi

DEMO_DIR="$REPO_ROOT/outputs/demo_anime_action"
REFS_DIR="$DEMO_DIR/refs"
PROMPTS_DIR="$DEMO_DIR/prompts"
CLIPS_DIR="$DEMO_DIR/clips"
PROMPT_TEMPLATE_DIR="$REPO_ROOT/examples/prompts/anime_action"
mkdir -p "$REFS_DIR" "$PROMPTS_DIR" "$CLIPS_DIR"

WOMAN_REF="$REFS_DIR/char_woman_swordsman_threeview.jpg"
VILLAIN_REF="$REFS_DIR/char_villain_assassin_threeview.jpg"
SCENE_REF="$REFS_DIR/scene_bamboo_snow_night.jpg"

# 3) 生 3 张 anime 参考图（已存在则跳过）
if [[ "${SKIP_REF_GEN:-0}" != "1" ]]; then
  if [[ ! -f "$WOMAN_REF" ]]; then
    echo "[1/5] 生成女主三视图 (anime)..."
    "$CHANGDU" text2image \
      --prompt "anime cel-shaded three-view illustration of a young female swordsman, character sheet style, front side and back views in one row, black leather armor with silver-trimmed cloak, high ponytail black hair, holding a single katana with floral hilt guard, neutral standing pose, clean line art, white background, masterpiece, sharp focus, no realistic skin, no photo" \
      --resolution_type 2k \
      --output "$WOMAN_REF"
  else
    echo "[1/5] 复用已有女主三视图: $WOMAN_REF"
  fi

  if [[ ! -f "$VILLAIN_REF" ]]; then
    echo "[1/5] 生成反派三视图 (anime)..."
    "$CHANGDU" text2image \
      --prompt "anime cel-shaded three-view illustration of a male swordsman antagonist, character sheet style, front side and back views in one row, long flowing black hair, dark navy haori with silver embroidery, single long straight sword at waist, neutral confident stance, clean line art, white background, masterpiece, no realistic skin, no photo" \
      --resolution_type 2k \
      --output "$VILLAIN_REF"
  else
    echo "[1/5] 复用已有反派三视图: $VILLAIN_REF"
  fi

  if [[ ! -f "$SCENE_REF" ]]; then
    echo "[1/5] 生成雪夜竹林场景图 (anime background)..."
    "$CHANGDU" text2image \
      --prompt "anime cel-shaded background painting of a snowy bamboo forest at night, moonlight piercing through bamboo leaves, soft falling snow, cold blue and silver palette, no characters, wide shot, painterly, masterpiece, no photo" \
      --resolution_type 2k \
      --output "$SCENE_REF"
  else
    echo "[1/5] 复用已有场景图: $SCENE_REF"
  fi
else
  echo "[1/5] 跳过参考图生成（SKIP_REF_GEN=1）"
fi

for f in "$WOMAN_REF" "$VILLAIN_REF" "$SCENE_REF"; do
  if [[ ! -f "$f" ]]; then
    echo "[!] 缺少参考图 $f" >&2
    exit 1
  fi
done

# 4) 准备 6 段 prompt（从模板复制，已存在则跳过）
if [[ ! -d "$PROMPT_TEMPLATE_DIR" ]]; then
  echo "[!] 缺少 prompt 模板目录 $PROMPT_TEMPLATE_DIR" >&2
  exit 1
fi
echo "[2/5] 准备 6 段武打分镜 prompt..."
for i in 1 2 3 4 5 6; do
  src="$PROMPT_TEMPLATE_DIR/视频_Clip00${i}.prompt.txt"
  dst="$PROMPTS_DIR/视频_Clip00${i}.prompt.txt"
  if [[ ! -f "$dst" ]]; then
    cp "$src" "$dst"
    echo "  cp $(basename "$src") → prompts/"
  fi
done

# 5) 创建 asset group（仅给 voice-from-clip 抽出的音色 asset 用）
GROUP_FILE="$DEMO_DIR/.group_id"
if [[ ! -f "$GROUP_FILE" ]]; then
  echo "[3/5] 创建 asset group..."
  GROUP_OUT=$("$CHANGDU" asset-group-create \
    --name "anime-action-30s" \
    --description "30s anime swordfight demo - voice asset group")
  echo "$GROUP_OUT"
  GROUP_ID=$(echo "$GROUP_OUT" | sed -n 's/.*\(group-[A-Za-z0-9_-]\{6,\}\).*/\1/p' | head -1)
  if [[ -z "$GROUP_ID" ]]; then
    echo "[!] 无法解析 group_id，请手动写入 $GROUP_FILE" >&2
    exit 1
  fi
  echo "$GROUP_ID" > "$GROUP_FILE"
else
  GROUP_ID=$(cat "$GROUP_FILE")
fi
echo "  asset_group: $GROUP_ID"

# 6) sequential-generate 6 段
if [[ "${SKIP_CLIP_GEN:-0}" != "1" ]]; then
  echo "[4/5] 顺序生成 6 段（continuity-mode=auto, voice-from-clip=1, duration=5）..."
  "$CHANGDU" sequential-generate \
    --prompt-dir "$PROMPTS_DIR" \
    --output-dir "$CLIPS_DIR" \
    --image "$WOMAN_REF" \
    --image "$VILLAIN_REF" \
    --image "$SCENE_REF" \
    --voice-from-clip 1 \
    --voice-group-id "$GROUP_ID" \
    --continuity-mode auto \
    --prev-tail-seconds 3.0 \
    --duration 5 \
    --quality 720p \
    --ratio 16:9
else
  echo "[4/5] 跳过 clip 生成（SKIP_CLIP_GEN=1）"
fi

# 7) clip-concat：crossfade + loudnorm，不叠加任何外部 BGM
echo "[5/5] 拼接成片（crossfade 0.4s + loudnorm，使用 Seedance 自带音轨）..."
FINAL_MP4="$DEMO_DIR/final.mp4"
"$CHANGDU" clip-concat \
  --input-dir "$CLIPS_DIR" \
  --output "$FINAL_MP4" \
  --crossfade-seconds 0.4 \
  --normalize-audio

echo ""
echo "============================================================"
echo " 完成！"
echo "   asset group: $GROUP_ID"
echo "   refs:        $REFS_DIR/*.jpg"
echo "   prompts:     $PROMPTS_DIR/视频_Clip00{1..6}.prompt.txt"
echo "   clips:       $CLIPS_DIR/视频_Clip00{1..6}.mp4"
echo "   final:       $FINAL_MP4"
echo ""
echo " 如确实想后期叠 BGM，再单独跑（可选）："
echo "   $CHANGDU clip-add-bgm \\"
echo "     --input $FINAL_MP4 \\"
echo "     --bgm <your_bgm.mp3> \\"
echo "     --output ${DEMO_DIR}/final_with_bgm.mp4 \\"
echo "     --bgm-volume 0.22 --bgm-ducking --normalize-audio"
echo "============================================================"
