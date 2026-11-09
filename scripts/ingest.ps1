<#
.SYNOPSIS
    Runs incremental ingestion: optional scraping, then parsing, chunking and indexing
    of everything under data\raw (and the fictional sample set with -Sample).
    -Rules extracts eligibility rules for new or changed schemes; review them with
    .venv\Scripts\yojana-review interactive.

.EXAMPLE
    scripts\ingest.ps1 -Sample
    scripts\ingest.ps1 -Scrape -MaxPages 20 -Rules
#>
[CmdletBinding()]
param(
    [switch]$Scrape,
    [int]$MaxPages = 0,
    [switch]$Sample,
    [switch]$Force,
    [switch]$Rules
)

. (Join-Path $PSScriptRoot "_common.ps1")
$root = Get-RepoRoot
$python = Get-VenvPython

$cliArgs = @("-m", "yojana.ingest.pipeline")
if ($Scrape) { $cliArgs += "--scrape" }
if ($MaxPages -gt 0) { $cliArgs += @("--max-pages", "$MaxPages") }
if ($Sample) { $cliArgs += "--sample" }
if ($Force) { $cliArgs += "--force" }
if ($Rules) { $cliArgs += "--rules" }

Push-Location $root
try {
    Write-Step "Ingesting documents"
    Invoke-Checked $python @cliArgs
} finally {
    Pop-Location
}
