# LUMU One-click Installer (Windows)
# Self-contained distribution: downloads from lumux.cn, no GitHub needed
# Install:  iwr https://lumux.cn/install.ps1 -useb | iex
# Update:  lumu update
$ErrorActionPreference = "Stop"

# ---- Fix console encoding so Chinese displays correctly ----
try {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}
try { chcp 65001 2>$null | Out-Null } catch {}

# ---- Force TLS 1.2/1.3 ----
try {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}

$LUMU_DIR = if ($env:LUMU_DIR) { $env:LUMU_DIR } else { Join-Path $HOME "LUMU" }
$DL = "https://lumux.cn/downloads/lumu-latest.zip"

function Test-Py {
  Write-Host "[1/5] Checking Python..."
  $p = Get-Command python -ErrorAction SilentlyContinue
  if (-not $p) {
    Write-Host "ERROR: python not found in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.11+ from https://www.python.org/downloads/ and check 'Add to PATH'."
    exit 1
  }
  try {
    $v = (python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null).Trim()
  } catch {
    Write-Host "ERROR: python execution failed." -ForegroundColor Red
    exit 1
  }
  if (-not $v -or $v -notmatch '^\d+\.\d+$' -or [version]$v -lt [version]"3.11") {
    Write-Host "ERROR: Python version too low ($v), need 3.11+" -ForegroundColor Red
    exit 1
  }
  Write-Host "OK: Python $v" -ForegroundColor Green
}

function Get-Zip {
  $z = Join-Path $env:TEMP ("lumu_" + [guid]::NewGuid().ToString("N") + ".zip")
  Write-Host "[2/5] Downloading package from lumux.cn..."
  try {
    Invoke-WebRequest -UseBasicParsing -Uri $DL -OutFile $z -ErrorAction Stop
    $size = (Get-Item $z -ErrorAction SilentlyContinue).Length
    if ((-not $size) -or $size -lt 100000) {
      Write-Host "ERROR: Downloaded file too small ($size bytes). Network or URL problem?" -ForegroundColor Red
      exit 1
    }
    Write-Host "OK: Downloaded ($([math]::Round($size/1KB,0)) KB)" -ForegroundColor Green
  } catch {
    Write-Host "ERROR: Download failed: $_" -ForegroundColor Red
    Write-Host "Check your internet connection or proxy settings." -ForegroundColor Yellow
    exit 1
  }
  return $z
}

function Apply-Package($zipPath) {
  Write-Host "[3/5] Extracting package..."
  $tmp = Join-Path $env:TEMP ("lumu_" + [guid]::NewGuid().ToString("N"))
  try {
    Expand-Archive -Path $zipPath -DestinationPath $tmp -Force -ErrorAction Stop
  } catch {
    Write-Host "ERROR: Failed to extract zip: $_" -ForegroundColor Red
    exit 1
  }
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
  Write-Host "OK: Extracted to $LUMU_DIR" -ForegroundColor Green
}

$isUpdate = ($args -contains "update")

Write-Host ""
Write-Host "============================================"
Write-Host "  LUMU Installer (Windows)"
Write-Host "============================================"
Write-Host ""

Test-Py

if ($isUpdate -and (Test-Path (Join-Path $LUMU_DIR "run.py"))) {
  $z = Get-Zip
  Apply-Package $z
  Write-Host "Updated to latest version."
} elseif (Test-Path (Join-Path $LUMU_DIR "run.py")) {
  Write-Host "Already installed. Run 'lumu update' to upgrade."
} else {
  if (-not (Test-Path $LUMU_DIR)) { New-Item -ItemType Directory -Path $LUMU_DIR | Out-Null }
  $z = Get-Zip
  Apply-Package $z
}

# venv + dependencies
if (-not (Test-Path (Join-Path $LUMU_DIR ".venv"))) {
  Write-Host "[4/5] Creating virtual environment..."
  try {
    python -m venv (Join-Path $LUMU_DIR ".venv") -ErrorAction Stop
  } catch {
    Write-Host "ERROR: venv creation failed: $_" -ForegroundColor Red
    exit 1
  }
}
Write-Host "[5/5] Installing dependencies (first time takes a while)..."
try {
  & (Join-Path $LUMU_DIR ".venv\Scripts\python.exe") -m pip install -r (Join-Path $LUMU_DIR "requirements.txt") -ErrorAction Stop
} catch {
  Write-Host "ERROR: pip install failed: $_" -ForegroundColor Red
  Write-Host "Try running manually:" -ForegroundColor Yellow
  Write-Host "  cd $LUMU_DIR"
  Write-Host "  .venv\Scripts\pip install -r requirements.txt"
  exit 1
}

# Save install.ps1 locally for future updates
$me = $MyInvocation.MyCommand.Path
if ($me) {
  try { Copy-Item $me (Join-Path $LUMU_DIR "install.ps1") -Force } catch {}
}

# Register lumu.bat launcher
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
}

Write-Host ""
Write-Host "============================================"
Write-Host "  DONE!" -ForegroundColor Green
Write-Host "============================================"
Write-Host ""
Write-Host "  Start:  lumu"
Write-Host "  UI:     http://localhost:38473"
Write-Host "  Update: lumu update"
Write-Host ""
Write-Host "  Open a NEW PowerShell window and type 'lumu'"
Write-Host "  First time: go to Settings and add your API key."
Write-Host ""
