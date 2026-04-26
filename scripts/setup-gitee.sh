#!/usr/bin/env bash
set -euo pipefail

REPO="https://gitee.com/bolecodex/changdu-skills.git"
SKILLS_DIR="${ARKCLAW_SKILLS_DIR:-${HOME}/.agents/skills}"

echo "========================================="
echo "  changdu-skills ArkClaw 一键安装"
echo "========================================="
echo ""

# --- 1. 检查 Python ---
PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ver=$("$cmd" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)
    major=${ver%%.*}
    minor=${ver#*.}
    if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; }; then
      PYTHON="$cmd"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "❌ 需要 Python >= 3.11，请先安装。"
  exit 1
fi
echo "✅ Python: $($PYTHON --version)"

if ! command -v git >/dev/null 2>&1; then
  echo "❌ 需要 git 才能从 Gitee 安装 changdu CLI 和 skills，请先安装 git。"
  exit 1
fi

# --- 2. 安装 changdu CLI ---
if command -v changdu >/dev/null 2>&1; then
  echo "✅ changdu CLI 已安装: $(command -v changdu)"
else
  echo "📦 正在从 Gitee 安装 changdu CLI..."
  "$PYTHON" -m pip install "changdu @ git+${REPO}#subdirectory=changdu" --quiet
  if command -v changdu >/dev/null 2>&1; then
    echo "✅ changdu CLI 安装成功: $(command -v changdu)"
  else
    echo "⚠️  pip install 成功但 changdu 不在 PATH 中，尝试用 pipx..."
    if command -v pipx >/dev/null 2>&1; then
      pipx install "changdu @ git+${REPO}#subdirectory=changdu"
    else
      echo "❌ 请手动将 pip scripts 目录加入 PATH，或安装 pipx 后重试。"
      exit 1
    fi
  fi
fi

# --- 3. 安装 / 更新 ArkClaw skills ---
echo ""
echo "📦 正在同步 skills 到 $SKILLS_DIR ..."
TMPDIR=$(mktemp -d)
cleanup() {
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

git clone --depth 1 "$REPO" "$TMPDIR/repo" >/dev/null 2>&1
if [ ! -d "$TMPDIR/repo/skills" ]; then
  echo "❌ 仓库中未找到 skills 目录。"
  exit 1
fi
mkdir -p "$SKILLS_DIR"
cp -R "$TMPDIR/repo/skills/"* "$SKILLS_DIR/"
echo "✅ Skills 已同步到 $SKILLS_DIR"

# --- 4. 检查配置 ---
echo ""
echo "========================================="
echo "  安装完成！"
echo "========================================="
echo ""

if [ -z "${CHANGDU_ARK_API_KEY:-${ARK_API_KEY:-}}" ]; then
  echo "⚠️  未检测到 API Key。安装完成后请回到 ArkClaw/Codex 项目会话，让 AI 告诉你 .env 的正确路径。"
  echo ""
  echo "把这句话发给 AI："
  echo '  请先确认当前工作区根目录的绝对路径，然后告诉我 changdu-skills 的 .env 应该放在哪里；如果还没有 .env，请基于 changdu-skills 的 .env.example 在正确位置创建一份。'
  echo ""
else
  echo "✅ API Key 已配置"
fi

echo "AI 通常会给出类似这样的路径："
echo "  /你的ArkClaw项目/.env"
echo ""
echo "可选配置："
echo "  CHANGDU_ARK_API_KEY=你的火山方舟APIKey"
echo "  CHANGDU_SEEDREAM_ENDPOINT=你的图像端点ID"
echo "  CHANGDU_SEEDANCE_ENDPOINT=你的视频端点ID"
echo "  VOLC_ACCESSKEY / VOLC_SECRETKEY / CHANGDU_TOS_BUCKET（本地视频/音频参考上传时需要）"
echo ""
echo "快速体验："
echo '  changdu text2image --prompt "一只可爱的猫" --output cat.jpg'
echo '  changdu text2video --prompt "日落海滩" --ratio 16:9 --duration 5'
echo ""
