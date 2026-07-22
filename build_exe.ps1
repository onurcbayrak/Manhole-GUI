param(
    [string]$VenvPath = ".venv"
)

if (-not (Test-Path $VenvPath)) {
    python -m venv $VenvPath
}

& "$VenvPath\Scripts\pip.exe" install -e .
& "$VenvPath\Scripts\pip.exe" install pyinstaller
& "$VenvPath\Scripts\pyinstaller.exe" build_exe.spec --noconfirm

Write-Host "Bitti: dist\manhole-gui\manhole-gui.exe"
