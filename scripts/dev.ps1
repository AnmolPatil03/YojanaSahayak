<#
.SYNOPSIS
    Starts the FastAPI backend (port 8000) and the Vite dev server (port 5173).
    Press Ctrl+C to stop both.
#>
[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [switch]$NoReload
)

. (Join-Path $PSScriptRoot "_common.ps1")
$root = Get-RepoRoot
$python = Get-VenvPython

$uvicornArgs = @(
    "-m", "uvicorn", "yojana.api.main:app",
    "--app-dir", (Join-Path $root "backend"),
    "--host", "127.0.0.1",
    "--port", "$BackendPort"
)
if (-not $NoReload) {
    $uvicornArgs += @("--reload", "--reload-dir", (Join-Path $root "backend\yojana"))
}

Write-Step "Starting backend on http://127.0.0.1:$BackendPort"
$backend = Start-Process -FilePath $python -ArgumentList $uvicornArgs -WorkingDirectory $root -NoNewWindow -PassThru

try {
    Write-Step "Starting frontend on http://localhost:5173"
    Push-Location (Join-Path $root "frontend")
    $env:VITE_API_PROXY = "http://127.0.0.1:$BackendPort"
    npm run dev
} finally {
    Pop-Location
    if ($backend -and -not $backend.HasExited) {
        Write-Step "Stopping backend"
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $($backend.Id)" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    }
}
