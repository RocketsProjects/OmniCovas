#Requires -Version 5.1
<#
Build the OmniCOVAS Python core sidecar expected by Tauri externalBin.

The output is intentionally generated local build output under src-tauri/bin/
and remains ignored by Git. Run this before `npm.cmd run tauri build` in a
fresh public, preview, or private checkout.
#>

[CmdletBinding()]
param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
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

$repoRoot = Get-RepoRoot
$entryPoint = Join-Path $repoRoot "omnicovas/scripts/omnicovas_sidecar.py"
$binDir = Join-Path $repoRoot "src-tauri/bin"
$workDir = Join-Path $repoRoot "build/tauri-sidecar"
$sidecarStem = "omnicovas-sidecar-$TargetTriple"
$extension = if ($TargetTriple -like "*windows*" -or $TargetTriple -like "*msvc*") { ".exe" } else { "" }
$outputPath = Join-Path $binDir "$sidecarStem$extension"

if (-not (Test-Path -LiteralPath $entryPoint)) {
    throw "Sidecar entry point missing: $entryPoint"
}

$mode = if ($DryRun) { "DRY-RUN" } else { "BUILD" }
Write-Host "TAURI SIDECAR BUILD"
Write-Host "Source repo:   $repoRoot"
Write-Host "Entry point:   $entryPoint"
Write-Host "Target triple: $TargetTriple"
Write-Host "Output path:   $outputPath"
Write-Host "Mode:          $mode"

$pyinstallerArgs = @(
    "run",
    "pyinstaller",
    "--clean",
    "--onefile",
    "--name",
    $sidecarStem,
    "--distpath",
    $binDir,
    "--workpath",
    $workDir,
    "--specpath",
    $workDir,
    $entryPoint
)

Write-Host "Command: uv $($pyinstallerArgs -join ' ')"

if ($DryRun) {
    Write-Host "Dry run only; no sidecar binary generated."
    Write-Host "RESULT: PASS"
    exit 0
}

New-Item -ItemType Directory -Force -Path $binDir | Out-Null
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

& uv @pyinstallerArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "RESULT: FAIL"
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $outputPath)) {
    Write-Host "Expected sidecar was not created: $outputPath"
    Write-Host "RESULT: FAIL"
    exit 1
}

Write-Host "RESULT: PASS"
exit 0
