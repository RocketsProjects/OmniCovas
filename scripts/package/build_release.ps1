#Requires -Version 5.1
<#
Build OmniCOVAS release artifacts and collect them into dist/release/.

Steps (in order):
  1. Sync ui/assets/legal/LICENSE.md from root LICENSE.md (drift guard).
  2. Build the Python core sidecar via build_tauri_sidecar.ps1.
  3. Run `npm run tauri build` (produces OmniCovas.exe, NSIS setup, MSI).
  4. Create dist/release/.
  5. Copy/rename the main app binary  -> dist/release/OmniCovas.exe
  6. Copy the sidecar companion       -> dist/release/omnicovas-sidecar.exe
  7. Copy/rename the NSIS installer   -> dist/release/setup.exe
  8. Copy the MSI as a secondary      -> dist/release/OmniCovas_<ver>_x64_en-US.msi
  9. Copy LICENSE.md, NOTICE.md, THIRD_PARTY_NOTICES.md into dist/release/.

dist/release/ is gitignored and forbidden from export. Never commit generated
.exe/.msi artifacts. Distribute only via GitHub Releases (Official Distribution
Channel per LICENSE.md §2).

SmartScreen note (Decision 8 — deferred signing):
  Unsigned OmniCovas.exe and setup.exe will trigger Windows SmartScreen on
  first launch. This is a documented release gate; code-signing cert purchase
  is deferred to a future Commander-authorized slice.
#>

[CmdletBinding()]
param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [switch]$DryRun,
    [switch]$SkipSidecar,
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Get-RepoRoot {
    $root = (& git rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($root)) {
        throw "No Git root found. Run from inside the OmniCOVAS repository."
    }
    return (Resolve-Path -LiteralPath $root).Path
}

function Invoke-Step {
    param([string]$Label, [scriptblock]$Block)
    Write-Host ""
    Write-Host "==> $Label"
    & $Block
}

function Copy-Artifact {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Dest,
        [string]$Label = ""
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Artifact not found: $Source$(if ($Label) { " ($Label)" })"
    }
    if (-not $DryRun) {
        Copy-Item -LiteralPath $Source -Destination $Dest -Force
        Write-Host "  Copied: $(Split-Path $Source -Leaf) -> $(Split-Path $Dest -Leaf)"
    } else {
        Write-Host "  [DRY-RUN] Would copy: $Source -> $Dest"
    }
}

# ── Setup ─────────────────────────────────────────────────────────────────────

$repoRoot   = Get-RepoRoot
$mode       = if ($DryRun) { "DRY-RUN" } else { "BUILD" }
$scriptDir  = Join-Path $repoRoot "scripts\package"
$distDir    = Join-Path $repoRoot "dist\release"

# Resolve product version from tauri.conf.json
$tauriConf  = Get-Content (Join-Path $repoRoot "src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json
$version    = $tauriConf.version
$productName = $tauriConf.productName  # "OmniCovas"

Write-Host "BUILD_RELEASE"
Write-Host "Repo root:    $repoRoot"
Write-Host "Product:      $productName  v$version"
Write-Host "Target:       $TargetTriple"
Write-Host "Mode:         $mode"
Write-Host "SkipSidecar:  $SkipSidecar"
Write-Host "SkipBuild:    $SkipBuild"

# ── Step 1: Sync bundled license ──────────────────────────────────────────────

Invoke-Step "Sync ui/assets/legal/LICENSE.md from root" {
    $syncScript = Join-Path $scriptDir "sync_license.ps1"
    if (-not (Test-Path -LiteralPath $syncScript)) {
        throw "sync_license.ps1 not found: $syncScript"
    }
    if ($DryRun) {
        & pwsh -NonInteractive -File $syncScript -DryRun
    } else {
        & pwsh -NonInteractive -File $syncScript
    }
    if ($LASTEXITCODE -ne 0) {
        throw "sync_license.ps1 failed (exit $LASTEXITCODE)"
    }
}

# ── Step 2: Build sidecar ─────────────────────────────────────────────────────

if (-not $SkipSidecar) {
    Invoke-Step "Build Python core sidecar" {
        $sidecarScript = Join-Path $scriptDir "build_tauri_sidecar.ps1"
        if (-not (Test-Path -LiteralPath $sidecarScript)) {
            throw "build_tauri_sidecar.ps1 not found: $sidecarScript"
        }
        if ($DryRun) {
            & pwsh -NonInteractive -File $sidecarScript -TargetTriple $TargetTriple -DryRun
        } else {
            & pwsh -NonInteractive -File $sidecarScript -TargetTriple $TargetTriple
        }
        if ($LASTEXITCODE -ne 0) {
            throw "build_tauri_sidecar.ps1 failed (exit $LASTEXITCODE)"
        }
    }
} else {
    Write-Host ""
    Write-Host "==> Sidecar build SKIPPED (-SkipSidecar)"
}

# ── Step 3: Tauri build ───────────────────────────────────────────────────────

if (-not $SkipBuild) {
    Invoke-Step "Run npm run tauri build" {
        if ($DryRun) {
            Write-Host "  [DRY-RUN] Would run: npm run tauri build"
        } else {
            Push-Location $repoRoot
            try {
                & npm.cmd run tauri build
                if ($LASTEXITCODE -ne 0) {
                    throw "npm run tauri build failed (exit $LASTEXITCODE)"
                }
            } finally {
                Pop-Location
            }
        }
    }
} else {
    Write-Host ""
    Write-Host "==> Tauri build SKIPPED (-SkipBuild)"
}

# ── Step 4: Create clean dist/release/ ───────────────────────────────────────

Invoke-Step "Create clean dist/release/" {
    if ($DryRun) {
        Write-Host "  [DRY-RUN] Would recreate clean directory: $distDir"
    } else {
        $distRoot = Join-Path $repoRoot "dist"
        $resolvedDistRoot = [System.IO.Path]::GetFullPath($distRoot)
        $resolvedDistDir = [System.IO.Path]::GetFullPath($distDir)
        $expectedPrefix = $resolvedDistRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
        if (-not $resolvedDistDir.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean unexpected release path: $resolvedDistDir"
        }

        New-Item -ItemType Directory -Force -Path $distRoot | Out-Null
        if (Test-Path -LiteralPath $distDir) {
            Remove-Item -LiteralPath $distDir -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path $distDir | Out-Null
        Write-Host "  Created clean directory: $distDir"
    }
}

# ── Locate build artifacts ────────────────────────────────────────────────────

$releaseTargetDir = Join-Path $repoRoot "src-tauri\target\release"
$bundleDir        = Join-Path $releaseTargetDir "bundle"
$nsisDir          = Join-Path $bundleDir "nsis"
$msiDir           = Join-Path $bundleDir "msi"

# Main binary: src-tauri/target/release/OmniCovas.exe
$mainBinarySrc = Join-Path $releaseTargetDir "$productName.exe"

# Sidecar companion: required beside direct launcher artifact.
$sidecarSrc = Join-Path $releaseTargetDir "omnicovas-sidecar.exe"

# NSIS: src-tauri/target/release/bundle/nsis/OmniCovas_<ver>_x64-setup.exe
$nsisSrc = Join-Path $nsisDir "${productName}_${version}_x64-setup.exe"

# MSI: src-tauri/target/release/bundle/msi/OmniCovas_<ver>_x64_en-US.msi
$msiSrc  = Join-Path $msiDir "${productName}_${version}_x64_en-US.msi"

# ── Step 5: Copy main binary ──────────────────────────────────────────────────

Invoke-Step "Copy main binary -> dist/release/OmniCovas.exe" {
    Copy-Artifact `
        -Source $mainBinarySrc `
        -Dest   (Join-Path $distDir "OmniCovas.exe") `
        -Label  "main app binary"
}

# ── Step 6: Copy sidecar companion ───────────────────────────────────────────

Invoke-Step "Copy sidecar companion -> dist/release/omnicovas-sidecar.exe" {
    Copy-Artifact `
        -Source $sidecarSrc `
        -Dest   (Join-Path $distDir "omnicovas-sidecar.exe") `
        -Label  "direct launcher sidecar"
}

# ── Step 7: Copy NSIS installer -> setup.exe ─────────────────────────────────

Invoke-Step "Copy NSIS installer -> dist/release/setup.exe" {
    Copy-Artifact `
        -Source $nsisSrc `
        -Dest   (Join-Path $distDir "setup.exe") `
        -Label  "NSIS installer"
}

# ── Step 8: Copy MSI (secondary) ─────────────────────────────────────────────

Invoke-Step "Copy MSI -> dist/release/ (secondary artifact)" {
    $msiDest = Join-Path $distDir "${productName}_${version}_x64_en-US.msi"
    Copy-Artifact -Source $msiSrc -Dest $msiDest -Label "MSI"
}

# ── Step 9: Copy legal files ──────────────────────────────────────────────────

Invoke-Step "Copy legal files into dist/release/" {
    $legalFiles = @("LICENSE.md", "NOTICE.md", "THIRD_PARTY_NOTICES.md")
    foreach ($file in $legalFiles) {
        $src = Join-Path $repoRoot $file
        $dest = Join-Path $distDir $file
        if (Test-Path -LiteralPath $src) {
            Copy-Artifact -Source $src -Dest $dest -Label $file
        } else {
            Write-Host "  WARNING: $file not found at $src — skipped"
        }
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "BUILD_RELEASE COMPLETE"

if (-not $DryRun) {
    Write-Host ""
    Write-Host "Artifacts in dist/release/:"
    Get-ChildItem -LiteralPath $distDir -File | ForEach-Object {
        $sizeKb = [math]::Round($_.Length / 1KB, 1)
        Write-Host ("  {0,-45} {1,8} KB" -f $_.Name, $sizeKb)
    }
    Write-Host ""
    Write-Host "SmartScreen notice: OmniCovas.exe and setup.exe are unsigned."
    Write-Host "Document this in release notes. Signing deferred per Decision 8."
}

Write-Host ""
Write-Host "RESULT: PASS"
exit 0
