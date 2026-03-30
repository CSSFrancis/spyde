#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Build SpyDE.exe with PyCrucible and inject the Windows icon.

.DESCRIPTION
    1. Runs `pycrucible --embed . --output dist/SpyDE.exe`
    2. Injects spyde/Spyde.ico into the resulting exe via tools/inject_icon.py
       (which uses tools/rcedit.exe internally).

.PARAMETER SkipIcon
    Skip the icon-injection step (useful for quick test builds).

.EXAMPLE
    .\build.ps1
    .\build.ps1 -SkipIcon
#>

param(
    [switch]$SkipIcon
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# ── helpers ──────────────────────────────────────────────────────────────────
function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    $msg"   -ForegroundColor Green }
function Fail($msg) { Write-Host "    ERROR: $msg" -ForegroundColor Red; exit 1 }

# ── pre-flight checks ────────────────────────────────────────────────────────
Step "Pre-flight checks"

if (-not (Get-Command pycrucible -ErrorAction SilentlyContinue)) {
    Fail "pycrucible not found. Install it with: pip install pycrucible"
}
Ok "pycrucible found: $(Get-Command pycrucible | Select-Object -ExpandProperty Source)"

if (-not $SkipIcon) {
    if (-not (Test-Path "tools\rcedit.exe")) {
        Fail "tools\rcedit.exe not found. Download from https://github.com/electron/rcedit/releases"
    }
    if (-not (Test-Path "spyde\Spyde.ico")) {
        Fail "spyde\Spyde.ico not found."
    }
    Ok "rcedit and icon found."
}

# ── create output directory ───────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path dist | Out-Null

# ── step 1: build with PyCrucible ─────────────────────────────────────────────
Step "Building with PyCrucible  →  dist\SpyDE.exe"
pycrucible --embed . --output dist/SpyDE.exe
if ($LASTEXITCODE -ne 0) { Fail "PyCrucible exited with code $LASTEXITCODE" }
Ok "PyCrucible build succeeded."

# ── step 2: inject Windows icon ───────────────────────────────────────────────
if (-not $SkipIcon) {
    Step "Injecting Windows icon  (spyde\Spyde.ico  →  dist\SpyDE.exe)"
    python tools/inject_icon.py dist/SpyDE.exe spyde/Spyde.ico
    if ($LASTEXITCODE -ne 0) { Fail "Icon injection exited with code $LASTEXITCODE" }
    Ok "Icon injected successfully."
} else {
    Write-Host "`n    (Icon injection skipped)" -ForegroundColor Yellow
}

# ── done ─────────────────────────────────────────────────────────────────────
Step "Done"
$size = (Get-Item dist\SpyDE.exe).Length / 1MB
Ok ("dist\SpyDE.exe is ready  ({0:F1} MB)" -f $size)

