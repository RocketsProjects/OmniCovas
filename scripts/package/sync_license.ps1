#Requires -Version 5.1
<#
Sync root LICENSE.md into the UI asset bundle.

Copies LICENSE.md from the repository root to ui/assets/legal/LICENSE.md so
that the in-app first-run license acknowledgement renders from a bundled static
asset (no bridge required). The bundled copy must be byte-identical to the root
copy; the drift test at tests/test_license_bundle_drift.py enforces this.

Run before `npm run tauri build` or standalone to keep the bundle in sync.
Also called by build_release.ps1 (Pass 2) as step 1.
#>

[CmdletBinding()]
param(
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    $root = (& git rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($root)) {
        throw "No Git root found. Run from inside the OmniCOVAS repository."
    }
    return (Resolve-Path -LiteralPath $root).Path
}

$repoRoot   = Get-RepoRoot
$sourcePath = Join-Path $repoRoot "LICENSE.md"
$destDir    = Join-Path $repoRoot "ui\assets\legal"
$destPath   = Join-Path $destDir "LICENSE.md"

if (-not (Test-Path -LiteralPath $sourcePath)) {
    Write-Host "SYNC_LICENSE: source not found: $sourcePath"
    Write-Host "RESULT: FAIL"
    exit 1
}

$mode = if ($DryRun) { "DRY-RUN" } else { "SYNC" }
Write-Host "SYNC_LICENSE"
Write-Host "Source: $sourcePath"
Write-Host "Dest:   $destPath"
Write-Host "Mode:   $mode"

if ($DryRun) {
    Write-Host "Dry run only; no files written."
    Write-Host "RESULT: PASS"
    exit 0
}

New-Item -ItemType Directory -Force -Path $destDir | Out-Null
Copy-Item -LiteralPath $sourcePath -Destination $destPath -Force

# Verify byte-identical after copy
$srcHash  = (Get-FileHash -LiteralPath $sourcePath  -Algorithm SHA256).Hash
$destHash = (Get-FileHash -LiteralPath $destPath    -Algorithm SHA256).Hash

if ($srcHash -ne $destHash) {
    Write-Host "SYNC_LICENSE: hash mismatch after copy — source=$srcHash dest=$destHash"
    Write-Host "RESULT: FAIL"
    exit 1
}

Write-Host "Verified SHA-256: $srcHash"
Write-Host "RESULT: PASS"
exit 0
