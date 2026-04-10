#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/bolecodex/changdu-skills.git"

echo "========================================="
echo "  changdu-skills 一键安装"
echo "========================================="
echo ""

# --- 1. 检查 Python ---
PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
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

# --- 2. 安装 changdu CLI ---
if command -v changdu &>/dev/null; then
  echo "✅ changdu CLI 已安装: $(which changdu)"
else
  echo "📦 正在安装 changdu CLI..."
  "$PYTHON" -m pip install "changdu @ git+${REPO}#subdirectory=changdu" --quiet
  if command -v changdu &>/dev/null; then
    echo "✅ changdu CLI 安装成功: $(which changdu)"
  else
    echo "⚠️  pip install 成功但 changdu 不在 PATH 中，尝试用 pipx..."
    if command -v pipx &>/dev/null; then
      pipx install "changdu @ git+${REPO}#subdirectory=changdu"
    else
      echo "❌ 请手动将 pip scripts 目录加入 PATH，或安装 pipx 后重试。"
    fi
  fi
fi

# --- 3. 安装 skills（如果通过 curl 直接运行而非 npx skills add） ---
SKILLS_DIR="${HOME}/.agents/skills"
if [ ! -d "$SKILLS_DIR/jimeng-skill" ]; then
  echo ""
  echo "📦 正在安装 skills 到 $SKILLS_DIR ..."
  TMPDIR=$(mktemp -d)
  git clone --depth 1 "$REPO" "$TMPDIR/repo" 2>/dev/null
  if [ -d "$TMPDIR/repo/skills" ]; then
    mkdir -p "$SKILLS_DIR"
    cp -r "$TMPDIR/repo/skills/"* "$SKILLS_DIR/"
    echo "✅ Skills 已安装到 $SKILLS_DIR"
  fi
  rm -rf "$TMPDIR"
else
  echo "✅ Skills 已存在于 $SKILLS_DIR"
fi

# --- 4. 检查配置 ---
echo ""
echo "========================================="
echo "  安装完成！"
echo "========================================="
echo ""

if [ -z "${CHANGDU_ARK_API_KEY:-${ARK_API_KEY:-}}" ]; then
  echo "⚠️  未检测到 API Key，请设置环境变量："
  echo ""
  echo '  export CHANGDU_ARK_API_KEY="你的火山方舟API Key"'
  echo ""
else
  echo "✅ API Key 已配置"
fi

echo ""
echo "快速体验："
echo '  changdu text2image --prompt "一只可爱的猫" --output cat.jpg'
echo '  changdu text2video --prompt "日落海滩" --ratio 16:9 --duration 5'
echo ""
