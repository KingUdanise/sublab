@echo off
REM Avvia il backend SubLab e apre la UI nel browser predefinito.
setlocal
set SUBLAB_PORT=8777
cd /d "%~dp0"
start "" /min python "%~dp0server.py"
timeout /t 3 >nul
start "" "http://127.0.0.1:8777"
endlocal
