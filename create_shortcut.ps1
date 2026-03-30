 # create_shortcut.ps1
# Creates a SpyDE shortcut on the Desktop (or Start Menu) with the branded icon.
# Run this once after copying SpyDE.exe to its final location.
#
# Usage:
#   .\create_shortcut.ps1                  # uses SpyDE.exe in the same folder
#   .\create_shortcut.ps1 -Target "C:\Apps\SpyDE.exe"

param(
    [string]$Target = (Join-Path $PSScriptRoot "SpyDE.exe"),
    [string]$IconFile = (Join-Path $PSScriptRoot "Spyde.ico"),
    [switch]$StartMenu
)

$exePath  = (Resolve-Path $Target -ErrorAction Stop).Path
$iconPath = if (Test-Path $IconFile) { $IconFile } else { $exePath }

$shell = New-Object -ComObject WScript.Shell

if ($StartMenu) {
    $dir  = [System.IO.Path]::Combine($env:APPDATA, "Microsoft\Windows\Start Menu\Programs")
    $link = Join-Path $dir "SpyDE.lnk"
} else {
    $link = Join-Path ([System.Environment]::GetFolderPath("Desktop")) "SpyDE.lnk"
}

$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath       = $exePath
$shortcut.WorkingDirectory = Split-Path $exePath -Parent
$shortcut.IconLocation     = "$iconPath,0"
$shortcut.Description      = "DE Visualization Tool"
$shortcut.Save()

Write-Host "Shortcut created: $link"


