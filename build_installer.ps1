# Compila l'installer SubLab (Inno Setup).
# Uso: powershell -ExecutionPolicy Bypass -File build_installer.ps1
$ErrorActionPreference = "Stop"

$candidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    throw "ISCC.exe non trovato. Installa Inno Setup: winget install JRSoftware.InnoSetup"
}

Push-Location $PSScriptRoot
try {
    if (-not (Test-Path "assets\sublab.ico")) { python make_icon.py }
    Write-Host "Compilo con $iscc ..."
    & $iscc "installer.iss" | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "compilazione fallita (exit $LASTEXITCODE)" }
    $out = Get-ChildItem "dist\SubLabSetup*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Write-Host "`nInstaller pronto: $($out.FullName)  ($([math]::Round($out.Length/1MB,2)) MB)"
} finally {
    Pop-Location
}
