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
$knowledgeBaseDir = Join-Path $repoRoot "omnicovas/knowledge_base"
# Shipped galactic knowledge packs only; the restricted folder is never collected.
$galacticKnowledgeDir = Join-Path $repoRoot "omnicovas/data/galactic_knowledge"
# Independent exobiology journal evidence (FU-021). Original OmniCOVAS aggregate; the
# retired legacy occurrence ruleset is never collected.
$exobiologyEvidencePath = Join-Path $repoRoot "omnicovas/data/exobiology_journal_evidence_v1.json"
$resourceBudgetPath = Join-Path $repoRoot "resource_budget.yaml"

if (-not (Test-Path -LiteralPath $entryPoint)) {
    throw "Sidecar entry point missing: $entryPoint"
}
if (-not (Test-Path -LiteralPath $knowledgeBaseDir)) {
    throw "Knowledge base directory missing: $knowledgeBaseDir"
}
if (-not (Test-Path -LiteralPath $galacticKnowledgeDir)) {
    throw "Galactic knowledge directory missing: $galacticKnowledgeDir"
}
if (-not (Test-Path -LiteralPath $exobiologyEvidencePath)) {
    throw "Exobiology evidence asset missing: $exobiologyEvidencePath"
}
if (-not (Test-Path -LiteralPath $resourceBudgetPath)) {
    throw "Resource budget missing: $resourceBudgetPath"
}

$mode = if ($DryRun) { "DRY-RUN" } else { "BUILD" }
Write-Host "TAURI SIDECAR BUILD"
Write-Host "Source repo:   $repoRoot"
Write-Host "Entry point:   $entryPoint"
Write-Host "Target triple: $TargetTriple"
Write-Host "Output path:   $outputPath"
Write-Host "Mode:          $mode"

$pyinstallerArgs = @(
    "--clean",
    "--onefile",
    "--add-data",
    "$knowledgeBaseDir$([IO.Path]::PathSeparator)omnicovas/knowledge_base",
    "--add-data",
    "$galacticKnowledgeDir$([IO.Path]::PathSeparator)omnicovas/data/galactic_knowledge",
    "--add-data",
    "$exobiologyEvidencePath$([IO.Path]::PathSeparator)omnicovas/data",
    "--add-data",
    "$resourceBudgetPath$([IO.Path]::PathSeparator).",
    "--hidden-import",
    "aiosqlite",
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

$venvPyInstaller = Join-Path $repoRoot ".venv/Scripts/pyinstaller.exe"
if (Test-Path -LiteralPath $venvPyInstaller) {
    $runner = $venvPyInstaller
    $runnerArgs = $pyinstallerArgs
} else {
    $runner = "uv"
    $runnerArgs = @("run", "pyinstaller") + $pyinstallerArgs
}

Write-Host "Command: $runner $($runnerArgs -join ' ')"

if ($DryRun) {
    Write-Host "Dry run only; no sidecar binary generated."
    Write-Host "RESULT: PASS"
    exit 0
}

New-Item -ItemType Directory -Force -Path $binDir | Out-Null
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

& $runner @runnerArgs
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
