<#
.SYNOPSIS
    Runs the MCP stdio server, or prints the Claude Desktop config entry for it.

.PARAMETER PrintConfig
    Print a claude_desktop_config.json snippet with this machine's paths instead of
    starting the server.
#>
[CmdletBinding()]
param(
    [switch]$PrintConfig
)

. (Join-Path $PSScriptRoot "_common.ps1")
$root = Get-RepoRoot
$python = Get-VenvPython

if ($PrintConfig) {
    $entry = [ordered]@{
        mcpServers = [ordered]@{
            "yojana-sahayak" = [ordered]@{
                command = $python
                args    = @("-m", "yojana.mcp_server")
                env     = [ordered]@{ YOJANA_ROOT = $root }
            }
        }
    }
    $entry | ConvertTo-Json -Depth 5
    exit 0
}

$env:YOJANA_ROOT = $root
& $python -m yojana.mcp_server
exit $LASTEXITCODE
