@echo off
TITLE BlueX Quantitative Control Terminal & Execution Gateway
COLOR 0B
echo ==============================================================================
echo  BLUEX QUANTITATIVE EXECUTION COCKPIT & BRIDGE (XAU/USD)
echo  LS Trading Academy - Institutional Market Control System
echo ==============================================================================
echo.

cd /d "%~dp0"

set "PY=C:\Users\Asus ROG\AppData\Local\Programs\Python311\python.exe"
if not exist "%PY%" (
    set "PY=python"
)

echo [*] Launching BlueX Interactive Web Cockpit at http://127.0.0.1:8000/terminal ...
start "" "http://127.0.0.1:8000/terminal"

echo [*] Starting FastAPI Microsecond Execution Server on port 8000...
echo.
"%PY%" server.py

pause
