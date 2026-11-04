#Requires -Version 5.1
<#
Build OmniCOVAS release artifacts and collect them into dist/release/.

Steps (in order):
  1. Sync ui/assets/legal/LICENSE.md from root LICENSE.md (drift guard).
  2. Build the Python core sidecar via build_tauri_sidecar.ps1.
  3. Generate target-aware SBOM, inventory, and third-party notices.
  4. Run `npm run tauri build` (produces OmniCovas.exe, NSIS setup, MSI).
  5. Create dist/release/.
  5. Copy/rename the main app binary  -> dist/release/OmniCovas.exe
  6. Copy the sidecar companion       -> dist/release/omnicovas-sidecar.exe
  7. Copy/rename the NSIS installer   -> dist/release/setup.exe
  8. Copy the MSI as a secondary      -> dist/release/OmniCovas_<ver>_x64_en-US.msi
  10. Copy legal files and durable machine-readable SBOM evidence.
  11. Generate SHA256SUMS.txt over every release file.

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

# PB10-R9: resolve a PowerShell host instead of assuming `pwsh` is installed.
# The script previously hardcoded `pwsh`, so on a machine with only Windows
# PowerShell 5.1 the release build failed at step 1 with CommandNotFoundException
# — the same class of global-tool assumption as the hardcoded `uv` in the native
# dev launcher. Prefer PowerShell 7 when present; otherwise use the host we are
# already running under.
function Resolve-PowerShellHost {
    $pwshCommand = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($pwshCommand) {
        return $pwshCommand.Source
    }

    $windowsPowerShell = Get-Command powershell -ErrorAction SilentlyContinue
    if ($windowsPowerShell) {
        return $windowsPowerShell.Source
    }

    throw "No PowerShell host found. Install PowerShell 7 (pwsh) or ensure powershell.exe is on PATH."
}

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

$psHost = Resolve-PowerShellHost
Write-Host "PS host:      $psHost"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

# ── Step 1: Sync bundled license ──────────────────────────────────────────────

Invoke-Step "Sync ui/assets/legal/LICENSE.md from root" {
    $syncScript = Join-Path $scriptDir "sync_license.ps1"
    if (-not (Test-Path -LiteralPath $syncScript)) {
        throw "sync_license.ps1 not found: $syncScript"
    }
    if ($DryRun) {
        & $psHost -NonInteractive -File $syncScript -DryRun
    } else {
        & $psHost -NonInteractive -File $syncScript
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
            & $psHost -NonInteractive -File $sidecarScript -TargetTriple $TargetTriple -DryRun
        } else {
            & $psHost -NonInteractive -File $sidecarScript -TargetTriple $TargetTriple
        }
        if ($LASTEXITCODE -ne 0) {
            throw "build_tauri_sidecar.ps1 failed (exit $LASTEXITCODE)"
        }
    }
} else {
    Write-Host ""
    Write-Host "==> Sidecar build SKIPPED (-SkipSidecar)"
}

# ── Step 3: Generate SBOM, inventory, and notices ─────────────────────────────

Invoke-Step "Generate target-aware SBOM and legal inventory" {
    $sbomScript = Join-Path $repoRoot "scripts\release\generate_sbom_inventory.py"
    $noticesScript = Join-Path $repoRoot "scripts\release\generate_third_party_notices.py"
    if ($DryRun) {
        Write-Host "  [DRY-RUN] Would run: $pythonExe $sbomScript"
        Write-Host "  [DRY-RUN] Would run: $pythonExe $noticesScript"
    } else {
        if (-not (Test-Path -LiteralPath $pythonExe)) {
            throw "Repository Python environment not found: $pythonExe"
        }
        & $pythonExe $sbomScript
        if ($LASTEXITCODE -ne 0) {
            throw "SBOM generation failed (exit $LASTEXITCODE)"
        }
        & $pythonExe $noticesScript
        if ($LASTEXITCODE -ne 0) {
            throw "Third-party notice generation failed (exit $LASTEXITCODE)"
        }
    }
}

# ── Step 4: Tauri build ───────────────────────────────────────────────────────

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

# ── Step 5: Create clean dist/release/ ───────────────────────────────────────

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

# ── Step 10: Copy legal files and durable SBOM evidence ───────────────────────

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

Invoke-Step "Copy durable SBOM evidence into dist/release/sbom/" {
    $sbomSource = Join-Path $repoRoot "artifacts\sbom\phase10-reconciliation"
    $sbomDest = Join-Path $distDir "sbom"
    $sbomFiles = @(
        "python-sbom-cyclonedx.json",
        "rust-sbom-cyclonedx.json",
        "npm-sbom-cyclonedx.json",
        "dependency-license-inventory.csv",
        "inventory-summary.json",
        "sbom-manifest.json"
    )
    if ($DryRun) {
        Write-Host "  [DRY-RUN] Would create: $sbomDest"
    } else {
        New-Item -ItemType Directory -Force -Path $sbomDest | Out-Null
    }
    foreach ($file in $sbomFiles) {
        Copy-Artifact `
            -Source (Join-Path $sbomSource $file) `
            -Dest (Join-Path $sbomDest $file) `
            -Label $file
    }
}

# ── Step 11: Hash the complete release envelope ───────────────────────────────

Invoke-Step "Generate SHA256SUMS.txt over the complete release envelope" {
    $hashFile = Join-Path $distDir "SHA256SUMS.txt"
    if ($DryRun) {
        Write-Host "  [DRY-RUN] Would hash all release files into: $hashFile"
    } else {
        $prefixLength = $distDir.TrimEnd("\").Length + 1
        $hashLines = Get-ChildItem -LiteralPath $distDir -File -Recurse |
            Where-Object { $_.FullName -ne $hashFile } |
            Sort-Object FullName |
            ForEach-Object {
                $relativePath = $_.FullName.Substring($prefixLength).Replace("\", "/")
                $digest = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                "$digest  $relativePath"
            }
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllLines($hashFile, [string[]]$hashLines, $utf8NoBom)
        Write-Host "  Hashed $($hashLines.Count) release files."
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "BUILD_RELEASE COMPLETE"

if (-not $DryRun) {
    Write-Host ""
    Write-Host "Artifacts in dist/release/:"
    Get-ChildItem -LiteralPath $distDir -File -Recurse | ForEach-Object {
        $sizeKb = [math]::Round($_.Length / 1KB, 1)
        $displayName = $_.FullName.Substring($distDir.Length + 1)
        Write-Host ("  {0,-55} {1,8} KB" -f $displayName, $sizeKb)
    }
    Write-Host ""
    Write-Host "SmartScreen notice: OmniCovas.exe and setup.exe are unsigned."
    Write-Host "Document this in release notes. Signing deferred per Decision 8."
}

Write-Host ""
Write-Host "RESULT: PASS"
exit 0
