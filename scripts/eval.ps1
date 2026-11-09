<#
.SYNOPSIS
    Runs the evaluation suite (retrieval ablations, answer quality, abstention and
    latency) with the LLM response cache enabled, and writes reports\eval-*.json/.md.

.PARAMETER Sample
    Use data\eval\sample_golden.jsonl (questions about the fictional sample set).
    Ingest the sample first with scripts\ingest.ps1 -Sample.

.PARAMETER NoGeneration
    Only measure retrieval; no LLM calls are made.
#>
[CmdletBinding()]
param(
    [switch]$Sample,
    [switch]$NoGeneration,
    [switch]$NoAblations,
    [switch]$NoCache
)

. (Join-Path $PSScriptRoot "_common.ps1")
$root = Get-RepoRoot
$python = Get-VenvPython

$golden = if ($Sample) { "data\eval\sample_golden.jsonl" } else { "data\eval\golden.jsonl" }
$cliArgs = @("-m", "yojana.eval.run", "--golden", (Join-Path $root $golden))
if ($NoGeneration) { $cliArgs += "--no-generation" }
if ($NoAblations) { $cliArgs += "--no-ablations" }
if ($NoCache) { $cliArgs += "--no-cache" }

Push-Location $root
try {
    $env:YOJANA_LLM_CACHE_ENABLED = "true"
    Write-Step "Running evaluation on $golden"
    Invoke-Checked $python @cliArgs
} finally {
    Pop-Location
}
