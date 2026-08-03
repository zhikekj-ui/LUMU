# LUMU One-click Installer (Windows)
# Self-contained distribution: downloads from lumux.cn, no GitHub needed.
# Python is auto-installed if missing - no manual setup required.
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

# ---- Resolve a usable python executable (full path), or $null ----
function Resolve-Py {
  # Prefer Python Launcher (py.exe) - always the real interpreter on Windows
  try {
    $p = (& py -3 -c "import sys;print(sys.executable)" 2>$null).ToString().Trim()
    if ($p -and (Test-Path $p)) {
      $v = (& $p --version 2>&1).ToString().Trim()
      if ($v -match '(\d+)\.(\d+)' -and [version]"$($Matches[1]).$($Matches[2])" -ge [version]"3.11") {
        return $p
      }
    }
  } catch {}
  # Fall back to python / python3 (skip the Microsoft Store alias)
  foreach ($cmd in @("python", "python3")) {
    try {
      $c = Get-Command $cmd -ErrorAction SilentlyContinue
      if ($c -and $c.Source -notlike "*WindowsApps*") {
        $p = $c.Source
        $v = (& $p --version 2>&1).ToString().Trim()
        if ($v -match '(\d+)\.(\d+)' -and [version]"$($Matches[1]).$($Matches[2])" -ge [version]"3.11") {
          return $p
        }
      }
    } catch {}
  }
  return $null
}

# ---- Auto-install Python if missing (current user, no admin needed) ----
function Install-Python {
  $ver = "3.12.7"
  $url = "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe"
  $inst = Join-Path $env:TEMP "python-$ver-installer.exe"
  try {
    Write-Host "  Downloading Python $ver installer..."
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $inst -ErrorAction Stop
    $sz = (Get-Item $inst -ErrorAction SilentlyContinue).Length
    if ((-not $sz) -or $sz -lt 1MB) { throw "installer too small ($sz bytes)" }
    Write-Host "  Installing Python (silent, one-time)..."
    Start-Process -FilePath $inst -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0" -Wait -ErrorAction Stop
    Remove-Item $inst -Force -ErrorAction SilentlyContinue
    # Refresh PATH so the freshly installed python is found in this session
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    Write-Host "OK: Python installed automatically." -ForegroundColor Green
  } catch {
    Write-Host "ERROR: Failed to auto-install Python: $_" -ForegroundColor Red
    Write-Host "Please install Python 3.11+ manually from https://www.python.org/downloads/ (check 'Add to PATH'), then re-run this installer." -ForegroundColor Yellow
    exit 1
  }
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

# ---- [1/5] Python check (auto-install if missing) ----
Write-Host "[1/5] Checking Python..."
$PYTHON = Resolve-Py
if (-not $PYTHON) {
  Write-Host "  Python not found. Auto-installing (one-time)..."
  Install-Python
  $PYTHON = Resolve-Py
}
if (-not $PYTHON) {
  Write-Host "ERROR: still cannot find Python after install." -ForegroundColor Red
  exit 1
}
$ver = (& $PYTHON --version 2>&1).ToString().Trim()
if ($ver -match '(\d+)\.(\d+)') { $v = "$($Matches[1]).$($Matches[2])" } else { $v = "?" }
Write-Host "OK: Python $v" -ForegroundColor Green

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

# ---- venv + dependencies ----
# NOTE: never pass -ErrorAction to an EXTERNAL program (& python ...) - it is a
# cmdlet-only parameter and would be forwarded to python as a literal argument.
# Native commands are checked via $LASTEXITCODE + artifact existence instead.
$ErrorActionPreference = "Continue"
try { $PSNativeCommandUseErrorActionPreference = $false } catch {}

$venvDir = Join-Path $LUMU_DIR ".venv"
$venvPy  = Join-Path $venvDir "Scripts\python.exe"

# A half-created venv (no python.exe) is worse than none - wipe it.
if ((Test-Path $venvDir) -and (-not (Test-Path $venvPy))) {
  Remove-Item $venvDir -Recurse -Force -ErrorAction SilentlyContinue
}

if (Test-Path $venvPy) {
  Write-Host "[4/5] Virtual environment already exists, skipping."
} else {
  Write-Host "[4/5] Creating virtual environment..."
  & $PYTHON -m venv $venvDir
  if (-not (Test-Path $venvPy)) {
    Write-Host "  First attempt failed, retrying with --copies..." -ForegroundColor Yellow
    Remove-Item $venvDir -Recurse -Force -ErrorAction SilentlyContinue
    & $PYTHON -m venv --copies $venvDir
  }
  if (-not (Test-Path $venvPy)) {
    Write-Host "ERROR: Failed to create virtual environment at $venvDir" -ForegroundColor Red
    Write-Host "Try manually: `"$PYTHON`" -m venv `"$venvDir`"" -ForegroundColor Yellow
    exit 1
  }
  Write-Host "OK: Virtual environment ready" -ForegroundColor Green
}

Write-Host "[5/5] Installing dependencies (first time takes a while)..."
$req = Join-Path $LUMU_DIR "requirements.txt"
if (-not (Test-Path $req)) {
  Write-Host "ERROR: requirements.txt not found in $LUMU_DIR" -ForegroundColor Red
  exit 1
}

# Try a fast domestic mirror first, then fall back to the official PyPI.
$mirrors = @(
  @{ Name = "tsinghua"; Url = "https://pypi.tuna.tsinghua.edu.cn/simple"; Host = "pypi.tuna.tsinghua.edu.cn" },
  @{ Name = "aliyun";   Url = "https://mirrors.aliyun.com/pypi/simple";   Host = "mirrors.aliyun.com" },
  @{ Name = "pypi";     Url = "https://pypi.org/simple";                  Host = "pypi.org" }
)

$firstUrl = $mirrors[0].Url
$firstHost = $mirrors[0].Host
& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check -i $firstUrl --trusted-host $firstHost 2>$null

$pipOk = $false
foreach ($m in $mirrors) {
  $idxUrl = $m.Url
  $idxHost = $m.Host
  Write-Host "  Using index: $($m.Name) ..."
  & $venvPy -m pip install -r $req --disable-pip-version-check -i $idxUrl --trusted-host $idxHost --retries 3 --timeout 60
  if ($LASTEXITCODE -eq 0) { $pipOk = $true; break }
  Write-Host "  $($m.Name) failed, trying next index..." -ForegroundColor Yellow
}

if (-not $pipOk) {
  Write-Host "ERROR: pip install failed on all mirrors." -ForegroundColor Red
  Write-Host "Try manually: cd `"$LUMU_DIR`" ; .venv\Scripts\python.exe -m pip install -r requirements.txt" -ForegroundColor Yellow
  exit 1
}

# Self-verification: the install is only "done" if the app can actually load.
if (-not (Test-Path (Join-Path $LUMU_DIR "run.py"))) {
  Write-Host "ERROR: run.py missing - package incomplete." -ForegroundColor Red
  exit 1
}
& $venvPy -c "import fastapi, uvicorn, httpx" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "ERROR: Core dependencies are not importable - install is incomplete." -ForegroundColor Red
  Write-Host "Try manually: cd `"$LUMU_DIR`" ; .venv\Scripts\python.exe -m pip install -r requirements.txt" -ForegroundColor Yellow
  exit 1
}
Write-Host "OK: Dependencies installed and verified" -ForegroundColor Green
$ErrorActionPreference = "Stop"

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
if "%1"=="update" ( powershell -NoProfile -ExecutionPolicy Bypass -File "%LUMU_DIR%\install.ps1" update & goto :eof )
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
