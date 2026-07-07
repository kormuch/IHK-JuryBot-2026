@echo off
cd /d "%~dp0"
title JuryBot 2026
echo JuryBot 2026 startet...
echo.
echo Beenden: Ctrl+C
echo.
start "" /b cmd /c "ping -n 4 127.0.0.1 >nul && start http://127.0.0.1:8000"
python -m backend.main
echo.
echo Server beendet. Fehler oben pruefen.
pause
