# LUMU 一键安装器 (Windows)
# 官网自包含分发：从 lumux.cn 下载安装包，全程不经过 GitHub
# 安装:  iwr https://lumux.cn/install.ps1 -useb | iex
# 更新:  lumu update
$ErrorActionPreference = "Stop"

# 兼容 TLS 1.2/1.3，避免老系统下载 HTTPS 时报 "connection was closed"
try {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}

$LUMU_DIR = if ($env:LUMU_DIR) { $env:LUMU_DIR } else { Join-Path $HOME "LUMU" }
$DL = "https://lumux.cn/downloads/lumu-latest.zip"

function Test-Py {
  $p = Get-Command python -ErrorAction SilentlyContinue
  if (-not $p) {
    Write-Host "✗ 未找到 python。请先安装 Python 3.11+ 并勾选 'Add to PATH': https://www.python.org/downloads/"
    Write-Host "  安装后请重开 PowerShell 再运行本命令。"
    exit 1
  }
  try {
    $v = (python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null).Trim()
  } catch {
    Write-Host "✗ 执行 python 失败，请确认 Python 3.11+ 已正确安装并加入 PATH。"
    exit 1
  }
  if (-not $v -or $v -notmatch '^\d+\.\d+$' -or [version]$v -lt [version]"3.11") {
    Write-Host "✗ Python 版本过低或无法识别 ($v)，需要 3.11+"
    exit 1
  }
  Write-Host "✓ Python $v"
}

function Get-Zip {
  $z = Join-Path $env:TEMP ("lumu_" + [guid]::NewGuid().ToString("N") + ".zip")
  Write-Host "→ 从官网下载安装包..."
  # 关键：必须 -UseBasicParsing，否则全新 Windows 会报 connection closed
  Invoke-WebRequest -UseBasicParsing -Uri $DL -OutFile $z -ErrorAction Stop
  return $z
}

function Apply-Package($zipPath) {
  $tmp = Join-Path $env:TEMP ("lumu_" + [guid]::NewGuid().ToString("N"))
  Expand-Archive -Path $zipPath -DestinationPath $tmp -Force
  $root = $tmp
  if (-not (Test-Path (Join-Path $root "run.py"))) {
    $rf = Get-ChildItem -Path $tmp -Recurse -Filter run.py | Select-Object -First 1
    if ($rf) { $root = Split-Path $rf.FullName }
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
  $z = Get-Zip
  Apply-Package $z
  Write-Host "→ 已更新到官网最新版"
} elseif (Test-Path (Join-Path $LUMU_DIR "run.py")) {
  Write-Host "→ 已安装。运行 'lumu update' 升级到官网最新版。"
} else {
  if (-not (Test-Path $LUMU_DIR)) { New-Item -ItemType Directory -Path $LUMU_DIR | Out-Null }
  $z = Get-Zip
  Apply-Package $z
}

# venv + 依赖
if (-not (Test-Path (Join-Path $LUMU_DIR ".venv"))) {
  Write-Host "→ 创建虚拟环境..."
  python -m venv (Join-Path $LUMU_DIR ".venv")
}
Write-Host "→ 安装依赖（首次稍慢，请稍候）..."
& (Join-Path $LUMU_DIR ".venv\Scripts\python.exe") -m pip install -r (Join-Path $LUMU_DIR "requirements.txt")

# 保存 install.ps1 到本地，供 lumu update 调用（iex 运行时 Path 为空，跳过即可）
$me = $MyInvocation.MyCommand.Path
if ($me) {
  try { Copy-Item $me (Join-Path $LUMU_DIR "install.ps1") -Force } catch {}
}

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
