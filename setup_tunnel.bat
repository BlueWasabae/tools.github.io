@echo off
TITLE BlueX Cloudflare Webhook Tunnel
COLOR 0A
echo ==============================================================================
echo  BLUEX CLOUDFLARE SECURE TUNNEL (TradingView -^> Localhost:8000)
echo ==============================================================================
echo.

where cloudflared >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [*] Downloading Cloudflare Tunnel (cloudflared.exe)...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'"
)

echo [*] Starting Cloudflare Tunnel pointing to http://127.0.0.1:8000 ...
echo [*] Copy the generated '*.trycloudflare.com' HTTPS URL and paste into TradingView Alert Webhook URL!
echo.
cloudflared.exe tunnel --url http://127.0.0.1:8000
pause
