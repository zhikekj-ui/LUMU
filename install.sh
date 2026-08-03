#!/usr/bin/env bash
# LUMU 一键安装器 (macOS / Linux)
# 官网自包含分发：从 lumux.cn 下载安装包，全程不经过 GitHub
# 安装:  curl -fsSL https://lumux.cn/install.sh | bash
# 更新:  lumu update   (或 bash install.sh update)
set -euo pipefail

LUMU_DIR="${LUMU_DIR:-$HOME/LUMU}"
DL_URL="https://lumux.cn/downloads/lumu-latest.zip"

echo "────────────────────────────────────────"
echo "  LUMU 一键安装"
echo "────────────────────────────────────────"

# 1) Python 检查
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ 未找到 python3。请先安装 Python 3.11+：https://www.python.org/downloads/"
  exit 1
fi
if ! python3 -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)"; then
  PY_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  echo "✗ Python 版本过低 ($PY_VER)，需要 3.11+"
  exit 1
fi
echo "✓ Python $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

# 2) 下载并应用安装包（保留 .venv / data）
download_and_extract() {
  local tmp dl target root item b
  tmp="$(mktemp -d)"
  dl="$tmp/lumu.zip"
  echo "→ 从官网下载 LUMU 安装包..."
  if ! curl -fsSL "$DL_URL" -o "$dl"; then
    echo "✗ 下载失败，请检查网络或稍后重试"
    rm -rf "$tmp"
    exit 1
  fi
  target="$(mktemp -d)"
  if command -v unzip >/dev/null 2>&1; then
    unzip -q "$dl" -d "$target"
  else
    python3 -c "import zipfile; zipfile.ZipFile('$dl').extractall('$target')"
  fi
  root="$target"
  if [ ! -f "$root/run.py" ]; then
    root="$(find "$target" -maxdepth 2 -name run.py | head -1 | xargs -r dirname)"
  fi
  mkdir -p "$LUMU_DIR"
  for item in "$root"/* "$root"/.[!.]*; do
    [ -e "$item" ] || continue
    b="$(basename "$item")"
    [ "$b" = ".venv" ] && continue
    [ "$b" = "data" ] && continue
    rm -rf "$LUMU_DIR/$b"
    cp -r "$item" "$LUMU_DIR/$b"
  done
  rm -rf "$tmp" "$target"
}

case "${1:-}" in
  update)
    echo "→ 更新到官网最新版..."
    download_and_extract
    ;;
  *)
    if [ -f "$LUMU_DIR/run.py" ]; then
      echo "→ 已安装。运行 'lumu update' 升级到官网最新版。"
    else
      download_and_extract
    fi
    ;;
esac

# 3) 虚拟环境 + 依赖
cd "$LUMU_DIR"
# 半成品 venv（缺 python）比没有更糟，直接重建
if [ -d .venv ] && [ ! -x .venv/bin/python ]; then
  rm -rf .venv
fi
if [ ! -d .venv ]; then
  echo "→ 创建虚拟环境..."
  if ! python3 -m venv .venv || [ ! -x .venv/bin/python ]; then
    rm -rf .venv
    python3 -m venv --copies .venv
  fi
fi
if [ ! -x .venv/bin/python ]; then
  echo "✗ 虚拟环境创建失败，请手动执行: python3 -m venv $LUMU_DIR/.venv"
  exit 1
fi

echo "→ 安装依赖（首次稍慢，请稍候）..."
.venv/bin/python -m pip install -U pip >/dev/null 2>&1 || true
PIP_OK=0
for IDX in "https://pypi.tuna.tsinghua.edu.cn/simple" "https://mirrors.aliyun.com/pypi/simple" "https://pypi.org/simple"; do
  echo "  使用源: $IDX"
  if .venv/bin/python -m pip install -r requirements.txt -i "$IDX" --retries 3 --timeout 60; then
    PIP_OK=1
    break
  fi
  echo "  该源失败，换下一个..."
done
if [ "$PIP_OK" -ne 1 ]; then
  echo "✗ 依赖安装失败（所有源均不可用），请检查网络后手动执行:"
  echo "  cd $LUMU_DIR && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi

# 4) 注册极简启动命令 `lumu`
cat > "$LUMU_DIR/lumu" <<'LAUNCHER'
#!/usr/bin/env bash
# LUMU launcher —— 任何目录敲 `lumu` 启动；`lumu update` 升级到官网最新版
LUMU_DIR="$HOME/LUMU"
DL_URL="https://lumux.cn/downloads/lumu-latest.zip"
case "${1:-}" in
  update)
    TMP="$(mktemp -d)"; TARGET="$(mktemp -d)"
    curl -fsSL "$DL_URL" -o "$TMP/lumu.zip" || { echo "下载失败"; exit 1; }
    (command -v unzip >/dev/null 2>&1 && unzip -q "$TMP/lumu.zip" -d "$TARGET") || python3 -c "import zipfile; zipfile.ZipFile('$TMP/lumu.zip').extractall('$TARGET')"
    ROOT="$TARGET"; [ -f "$ROOT/run.py" ] || ROOT="$(find "$TARGET" -maxdepth 2 -name run.py | head -1 | xargs -r dirname)"
    for item in "$ROOT"/* "$ROOT"/.[!.]*; do [ -e "$item" ] || continue; b="$(basename "$item")"; [ "$b" = ".venv" ] && continue; [ "$b" = "data" ] && continue; rm -rf "$LUMU_DIR/$b"; cp -r "$item" "$LUMU_DIR/$b"; done
    "$LUMU_DIR/.venv/bin/pip" install -r "$LUMU_DIR/requirements.txt" >/dev/null 2>&1 || true
    echo "LUMU 已更新到官网最新版"; rm -rf "$TMP" "$TARGET"
    ;;
  *)
    exec "$LUMU_DIR/.venv/bin/python" "$LUMU_DIR/run.py" "$@"
    ;;
esac
LAUNCHER
chmod +x "$LUMU_DIR/lumu"

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
echo "  升级命令:  lumu update"
echo "  （若 'lumu' 提示找不到，请重开终端，或直接使用: $LUMU_DIR/lumu）"
echo ""
echo "  首次使用请在界面「设置」里填写你的模型 (API Key / 模型名)。"
