Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Curapod Appium Test Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ─── Step 1: Find or install Python ───────────────────────────────────────────
Write-Host "`n[1/4] Checking Python..." -ForegroundColor Yellow

$pythonExe = $null
$commonPaths = @(
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python311\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python310\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Python310\python.exe",
    "C:\Python312\python.exe"
)

foreach ($path in $commonPaths) {
    if (Test-Path $path) {
        $pythonExe = $path
        break
    }
}

if (-not $pythonExe) {
    Write-Host "  Python not found. Installing Python 3.11..." -ForegroundColor Yellow
    $installer = "D:\CurapodTest\python-installer.exe"
    if (-not (Test-Path $installer)) {
        Write-Host "  Downloading Python 3.11.9..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $installer -UseBasicParsing
    }
    Write-Host "  Running installer (a progress window will appear)..." -ForegroundColor Yellow
    $installDir = "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python311"
    & $installer /passive InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1 TargetDir=$installDir
    Start-Sleep -Seconds 5
    $pythonExe = "$installDir\python.exe"
}

if (-not (Test-Path $pythonExe)) {
    Write-Host "  ERROR: Python installation failed. Trying alternate path..." -ForegroundColor Red
    # Try finding it anywhere
    $found = Get-ChildItem "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\" -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $pythonExe = $found.FullName }
}

if (-not (Test-Path $pythonExe)) {
    Write-Host "  FATAL: Cannot find python.exe. Please install Python manually from https://python.org" -ForegroundColor Red
    exit 1
}

Write-Host "  Using Python: $pythonExe" -ForegroundColor Green
& $pythonExe --version

# ─── Step 2: Upgrade pip ──────────────────────────────────────────────────────
Write-Host "`n[2/4] Upgrading pip..." -ForegroundColor Yellow
& $pythonExe -m pip install --upgrade pip --quiet
Write-Host "  pip ready." -ForegroundColor Green

# ─── Step 3: Install Python packages ──────────────────────────────────────────
Write-Host "`n[3/4] Installing Python packages..." -ForegroundColor Yellow
& $pythonExe -m pip install Appium-Python-Client==4.3.0 selenium==4.21.0
Write-Host "  Packages installed." -ForegroundColor Green

# ─── Step 4: Install Appium uiautomator2 driver ───────────────────────────────
Write-Host "`n[4/4] Installing Appium uiautomator2 driver..." -ForegroundColor Yellow
$driverCheck = appium driver list --installed 2>&1
if ($driverCheck -match "uiautomator2") {
    Write-Host "  uiautomator2 already installed." -ForegroundColor Green
} else {
    appium driver install uiautomator2
    Write-Host "  uiautomator2 driver installed." -ForegroundColor Green
}

# ─── Done ─────────────────────────────────────────────────────────────────────
Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  ALL DONE! Setup complete." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Start Appium:  appium" -ForegroundColor White
Write-Host "  2. Connect phones via USB" -ForegroundColor White
Write-Host "  3. Run tests:     $pythonExe D:\CurapodTest\appium_parallel_poc.py" -ForegroundColor White
Write-Host ""
