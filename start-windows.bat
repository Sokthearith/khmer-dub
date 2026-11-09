@echo off
REM Khmer Dub - double-click to start. First start downloads 2-4 GB (Python, AI models).
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo Installing uv (Python manager^)...
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

set EXTRA=cpu
where nvidia-smi >nul 2>nul
if not errorlevel 1 set EXTRA=gpu

echo.
echo Starting Khmer Dub (%EXTRA% mode). The app opens in your browser when ready.
echo Keep this window open while you use the app.
echo.
uv run --extra %EXTRA% khmerdub ui
pause
