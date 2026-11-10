@echo off
REM Khmer Dub - double-click to start. First start downloads 2-4 GB (Python, AI models)
REM and puts a "Khmer Dub" shortcut on the desktop and in the Start menu.
cd /d "%~dp0"

REM An update can't replace this file while it runs, so it leaves start-windows.bat.new: swap it in now.
if exist "%~dp0start-windows.bat.new" (
    move /y "%~dp0start-windows.bat.new" "%~dp0start-windows.bat" >nul
    "%~dp0start-windows.bat"
    exit /b
)

set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>nul
if errorlevel 1 (
    echo Installing uv (Python manager^)...
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
)

set EXTRA=cpu
where nvidia-smi >nul 2>nul
if not errorlevel 1 set EXTRA=gpu

REM install a downloaded update (if any) before the app opens
uv run --extra %EXTRA% khmerdub update --apply
if exist "%~dp0start-windows.bat.new" (
    move /y "%~dp0start-windows.bat.new" "%~dp0start-windows.bat" >nul
    "%~dp0start-windows.bat"
    exit /b
)

echo.
echo Starting Khmer Dub (%EXTRA% mode). It opens in its own window when ready.
echo Keep this black window open while you use the app.
echo.
uv run --extra %EXTRA% khmerdub app
if errorlevel 1 pause
