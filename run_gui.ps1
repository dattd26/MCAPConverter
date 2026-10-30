# PowerShell launcher for MCAP Studio
$Host.UI.RawUI.WindowTitle = "MCAP Studio - Giao Diện Xử Lý Video"
$PSScriptRoot = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
Set-Location -Path $PSScriptRoot

$pythonPath = ".\.venv\Scripts\python.exe"

if (Test-Path $pythonPath) {
    & $pythonPath gui_app.py
} else {
    Write-Host "[LỖI] Không tìm thấy môi trường Python tại $pythonPath" -ForegroundColor Red
    pause
}
