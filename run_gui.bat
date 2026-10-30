@echo off
chcp 65001 >nul
title MCAP Studio - Khoi Dong Giao Dien
cd /d "%~dp0"

echo ========================================================
echo    DANG KHOI DONG MCAP STUDIO GIAO DIEN CUC BO...
echo ========================================================

if exist ".\.venv\Scripts\python.exe" (
    ".\.venv\Scripts\python.exe" gui_app.py
) else (
    echo [LOI] Khong tim thay moi truong Python tai .\.venv\Scripts\python.exe
    echo Vui long kiem tra lai thu muc cai dat.
    pause
)
