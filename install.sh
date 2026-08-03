#!/usr/bin/env bash
# LUMU 一键安装器 (macOS / Linux)
# 用法:  curl -fsSL https://lumux.cn/install.sh | bash
set -euo pipefail

LUMU_DIR="${LUMU_DIR:-$HOME/LUMU}"
REPO_URL="https://github.com/zhikekj-ui/LUMU.git"
MIN_MAJOR=3
MIN_MINOR=11

echo "────────────────────────────────────────"
echo "  LUMU 一键安装"
echo "────────────────────────────────────────"

# 1) 检查 Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ 未找到 python3。请先安装 Python ${MIN_MAJOR}.${MIN_MINOR}+：https://www.python.org/downloads/"
  exit 1
fi
if ! python3 -c "import sys; sys.exit(0 if sys.version_info[:2] >= ($MIN_MAJOR, $MIN_MINOR) else 1)"; then
  PY_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  echo "✗ Python 版本过低 ($PY_VER)，需要 ${MIN_MAJOR}.${MIN_MINOR}+"
  exit 1
fi
echo "✓ Python $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

# 2) 克隆或更新
if [ -d "$LUMU_DIR/.git" ]; then
  echo "→ 已存在，更新代码..."
  git -C "$LUMU_DIR" pull --ff-only || echo "（更新失败，使用现有代码继续）"
else
  echo "→ 克隆代码到 $LUMU_DIR"
  git clone "$REPO_URL" "$LUMU_DIR"
fi
cd "$LUMU_DIR"

# 3) 虚拟环境
if [ ! -d .venv ]; then
  echo "→ 创建虚拟环境..."
  python3 -m venv .venv
fi

# 4) 安装依赖
echo "→ 安装依赖（首次稍慢，请稍候）..."
.venv/bin/python -m pip install -U pip >/dev/null 2>&1 || true
.venv/bin/pip install -r requirements.txt

# 5) 注册极简启动命令 `lumu`
cat > "$LUMU_DIR/lumu" <<'LAUNCHER'
#!/usr/bin/env bash
# LUMU launcher —— 任何目录敲 `lumu` 即可启动
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/run.py" "$@"
LAUNCHER
chmod +x "$LUMU_DIR/lumu"

# 链接到 PATH
LINKED="$LUMU_DIR/lumu"
if [ -w /usr/local/bin ]; then
  ln -sf "$LUMU_DIR/lumu" /usr/local/bin/lumu
  LINKED=/usr/local/bin/lumu
elif mkdir -p "$HOME/.local/bin" 2>/dev/null; then
  ln -sf "$LUMU_DIR/lumu" "$HOME/.local/bin/lumu"
  LINKED="$HOME/.local/bin/lumu"
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) printf 'export PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc" 2>/dev/null
       printf 'export PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.zshrc" 2>/dev/null ;;
  esac
fi

echo ""
echo "────────────────────────────────────────"
echo "  ✓ 安装完成！"
echo "────────────────────────────────────────"
echo "  启动命令:  lumu"
echo "  界面地址:  http://localhost:38473"
echo "  （若 'lumu' 提示找不到，请重开终端，或直接使用: $LUMU_DIR/lumu）"
echo ""
echo "  首次使用请在界面「设置」里填写你的模型 (API Key / 模型名)。"
