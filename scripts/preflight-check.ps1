<#
Phase 0 preflight check.

Reports the local toolchain versions this project expects. Never fails the
session: a missing tool is reported, not raised, so the output can be pasted
into a phase handoff.

Usage:  powershell -ExecutionPolicy Bypass -File scripts/preflight-check.ps1
#>

$ErrorActionPreference = 'Continue'

function Show-Tool {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$Command
    )

    Write-Output ''
    Write-Output "== $Label =="
    try {
        & $Command[0] $Command[1..($Command.Count - 1)] 2>&1 | ForEach-Object { Write-Output "   $_" }
        if ($LASTEXITCODE -ne 0) {
            Write-Output "   [warn] exit code $LASTEXITCODE"
        }
    }
    catch {
        Write-Output "   [missing] $($Command[0]) is not on PATH"
    }
}

Write-Output 'Phase 0 preflight'
Write-Output "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Output "OS: $((Get-CimInstance Win32_OperatingSystem).Caption)"

Show-Tool -Label 'Java (expected 21+)' -Command @('java', '-version')
Show-Tool -Label 'Javac (expected 21+)' -Command @('javac', '-version')
Show-Tool -Label 'Maven (expected 3.9+)' -Command @('mvn', '-version')
Show-Tool -Label 'Python (expected 3.12+)' -Command @('python', '--version')
Show-Tool -Label 'Docker CLI' -Command @('docker', '--version')
Show-Tool -Label 'Docker Compose' -Command @('docker', 'compose', 'version')

Write-Output ''
Write-Output '== Docker daemon =='
$daemonVersion = docker info --format '{{.ServerVersion}}' 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Output "   reachable, server $daemonVersion"
}
else {
    Write-Output '   [warn] daemon not reachable. Start Docker Desktop, then: make up'
}

Write-Output ''
Write-Output 'Preflight complete.'