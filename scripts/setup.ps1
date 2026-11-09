<#
.SYNOPSIS
    Creates the Python virtual environment, installs the backend (CPU-only PyTorch)
    and the frontend, and creates .env from .env.example when it is missing.

.PARAMETER Onnx
    Also install the ONNX Runtime backend for faster CPU inference.

.PARAMETER Render
    Also install Playwright and Chromium for scraping pages that need JavaScript.

.PARAMETER SkipFrontend
    Skip `npm install` for the frontend.
#>
[CmdletBinding()]
param(
    [switch]$Onnx,
    [switch]$Render,
    [switch]$SkipFrontend
)

. (Join-Path $PSScriptRoot "_common.ps1")
$root = Get-RepoRoot
Set-Location $root

Write-Step "Checking Python"
$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) {
    $basePython = "py"
    $baseArgs = @("-3.13")
    & py -3.13 --version *> $null
    if ($LASTEXITCODE -ne 0) { $baseArgs = @("-3") }
} else {
    $basePython = "python"
    $baseArgs = @()
}
$version = & $basePython @baseArgs -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$version -lt [version]"3.11") {
    throw "Python 3.11 or newer is required (found $version)."
}
Write-Host "Using Python $version"

$venv = Join-Path $root ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    Write-Step "Creating virtual environment in .venv"
    Invoke-Checked $basePython @baseArgs -m venv $venv
}
$python = Get-VenvPython

Write-Step "Upgrading pip"
Invoke-Checked $python -m pip install --upgrade pip

Write-Step "Installing CPU-only PyTorch"
Invoke-Checked $python -m pip install torch --index-url https://download.pytorch.org/whl/cpu

$extras = @("dev")
if ($Onnx) { $extras += "onnx" }
if ($Render) { $extras += "render" }
$spec = "backend[" + ($extras -join ",") + "]"
Write-Step "Installing backend ($spec)"
Invoke-Checked $python -m pip install -e $spec

if ($Render) {
    Write-Step "Installing Chromium for Playwright"
    Invoke-Checked $python -m playwright install chromium
}

if (-not $SkipFrontend) {
    Write-Step "Installing frontend dependencies"
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Warning "npm not found. Install the current Node.js LTS from https://nodejs.org and re-run."
    } else {
        Push-Location (Join-Path $root "frontend")
        try {
            if (Test-Path "package-lock.json") { Invoke-Checked npm ci } else { Invoke-Checked npm install }
        } finally {
            Pop-Location
        }
    }
}

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Write-Host "Created .env from .env.example. Add your API keys there."
}

foreach ($dir in @("data\raw", "data\processed", "data\index", "reports")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $root $dir) | Out-Null
}

Write-Step "Done"
Write-Host "Next: add API keys to .env, then run scripts\ingest.ps1 and scripts\dev.ps1"
