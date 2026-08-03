# LUMU 一键安装器 (Windows)
# 官网自包含分发：从 lumux.cn 下载安装包，全程不经过 GitHub
# 安装:  iwr https://lumux.cn/install.ps1 -useb | iex
# 更新:  lumu update
$ErrorActionPreference = "Stop"

$LUMU_DIR = if ($env:LUMU_DIR) { $env:LUMU_DIR } else { Join-Path $HOME "LUMU" }
$DL = "https://lumux.cn/downloads/lumu-latest.zip"

function Test-Py {
  $p = Get-Command python -ErrorAction SilentlyContinue
  if (-not $p) {
    Write-Host "✗ 未找到 python。请先安装 Python 3.11+ 并勾选 'Add to PATH': https://www.python.org/downloads/"
    exit 1
  }
  $v = python -c "import sys; print('%d.%d' % sys.version_info[:2])"
  if ([version]$v -lt [version]"3.11") { Write-Host "✗ Python 过低 ($v)，需要 3.11+"; exit 1 }
  Write-Host "✓ Python $v"
}

function Apply-Package($zipPath) {
  $tmp = Join-Path $env:TEMP ("lumu_" + [guid]::NewGuid().ToString("N"))
  Expand-Archive -Path $zipPath -DestinationPath $tmp -Force
  $root = $tmp
  if (-not (Test-Path (Join-Path $root "run.py"))) {
    $rf = Get-ChildItem -Path $tmp -Recurse -Filter run.py | Select-Object -First 1
    $root = Split-Path $rf.FullName
  }
  foreach ($item in Get-ChildItem -Path $root) {
    if ($item.Name -eq ".venv" -or $item.Name -eq "data") { continue }
    $dest = Join-Path $LUMU_DIR $item.Name
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Copy-Item $item.FullName -Destination $dest -Recurse -Force
  }
  Remove-Item $tmp -Recurse -Force
}

$isUpdate = ($args -contains "update")

Write-Host "────────────────────────────────────────"
Write-Host "  LUMU 一键安装 (Windows)"
Write-Host "────────────────────────────────────────"

Test-Py

if ($isUpdate -and (Test-Path (Join-Path $LUMU_DIR "run.py"))) {
  Write-Host "→ 更新到官网最新版..."
  $z = Join-Path $env:TEMP "lumu.zip"
  Invoke-WebRequest $DL -OutFile $z
  Apply-Package $z
} elseif (Test-Path (Join-Path $LUMU_DIR "run.py")) {
  Write-Host "→ 已安装。运行 'lumu update' 升级到官网最新版。"
} else {
  Write-Host "→ 从官网下载安装包..."
  $z = Join-Path $env:TEMP "lumu.zip"
  Invoke-WebRequest $DL -OutFile $z
  if (-not (Test-Path $LUMU_DIR)) { New-Item -ItemType Directory -Path $LUMU_DIR | Out-Null }
  Apply-Package $z
}

# venv + 依赖
if (-not (Test-Path (Join-Path $LUMU_DIR ".venv"))) {
  Write-Host "→ 创建虚拟环境..."
  python -m venv (Join-Path $LUMU_DIR ".venv")
}
Write-Host "→ 安装依赖（首次稍慢，请稍候）..."
& (Join-Path $LUMU_DIR ".venv\Scripts\pip.exe") install -r (Join-Path $LUMU_DIR "requirements.txt")

# 保存 install.ps1 到本地，供 lumu update 调用
try { Copy-Item $MyInvocation.MyCommand.Path (Join-Path $LUMU_DIR "install.ps1") -Force } catch {}

# 注册 lumu.bat
$lumat = Join-Path $LUMU_DIR "lumu.bat"
@"
@echo off
set LUMU_DIR=%USERPROFILE%\LUMU
if "%1"=="update" ( powershell -ExecutionPolicy Bypass "%LUMU_DIR%\install.ps1" update & goto :eof )
"%LUMU_DIR%\.venv\Scripts\python.exe" "%LUMU_DIR%\run.py" %*
"@ | Set-Content -Encoding ascii $lumat

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$LUMU_DIR*") {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$LUMU_DIR", "User")
  $env:Path = "$env:Path;$LUMU_DIR"
  Write-Host "→ 已将 LUMU 加入用户 PATH"
}

Write-Host ""
Write-Host "────────────────────────────────────────"
Write-Host "  ✓ 完成！"
Write-Host "────────────────────────────────────────"
Write-Host "  启动命令:  lumu"
Write-Host "  界面地址:  http://localhost:38473"
Write-Host "  升级命令:  lumu update"
Write-Host "  （新开 PowerShell 窗口即可使用 'lumu'；若找不到请重开终端）"
Write-Host ""
Write-Host "  首次使用请在界面「设置」里填写你的模型 (API Key / 模型名)。"
