# LUMU 一键安装器 (Windows)
# 用法:  iwr https://lumux.cn/install.ps1 -useb | iex
$ErrorActionPreference = "Stop"

$LUMU_DIR = if ($env:LUMU_DIR) { $env:LUMU_DIR } else { Join-Path $HOME "LUMU" }
$REPO_URL = "https://github.com/zhikekj-ui/LUMU.git"

Write-Host "────────────────────────────────────────"
Write-Host "  LUMU 一键安装 (Windows)"
Write-Host "────────────────────────────────────────"

# 1) Python 检查
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "✗ 未找到 python。请先安装 Python 3.11+ 并勾选 'Add to PATH': https://www.python.org/downloads/"
    exit 1
}
$ver = python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "✓ Python $ver"

# 2) clone / update
if (Test-Path (Join-Path $LUMU_DIR ".git")) {
    Write-Host "→ 已存在，更新代码..."
    git -C $LUMU_DIR pull --ff-only 2>$null
} else {
    Write-Host "→ 克隆代码到 $LUMU_DIR"
    git clone $REPO_URL $LUMU_DIR
}
Set-Location $LUMU_DIR

# 3) venv
if (-not (Test-Path ".venv")) {
    Write-Host "→ 创建虚拟环境..."
    python -m venv .venv
}

# 4) 安装依赖
Write-Host "→ 安装依赖（首次稍慢，请稍候）..."
.venv\Scripts\python.exe -m pip install -U pip | Out-Null
.venv\Scripts\pip.exe install -r requirements.txt

# 5) 注册 `lumu` 命令
$lumat = Join-Path $LUMU_DIR "lumu.bat"
@"
@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0run.py" %*
"@ | Set-Content -Encoding ascii $lumat

# 加入用户 PATH
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$LUMU_DIR*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$LUMU_DIR", "User")
    $env:Path = "$env:Path;$LUMU_DIR"
    Write-Host "→ 已将 $LUMU_DIR 加入用户 PATH"
}

Write-Host ""
Write-Host "────────────────────────────────────────"
Write-Host "  ✓ 安装完成！"
Write-Host "────────────────────────────────────────"
Write-Host "  启动命令:  lumu"
Write-Host "  界面地址:  http://localhost:38473"
Write-Host "  （新开 PowerShell 窗口即可使用 'lumu'；若找不到请重开终端）"
Write-Host ""
Write-Host "  首次使用请在界面「设置」里填写你的模型 (API Key / 模型名)。"
