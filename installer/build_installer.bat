@echo off
rem ============================================================
rem  Build the Marvin installer (Inno Setup 6)
rem  - locate ISCC or install Inno Setup through winget
rem  - read the version from installer\version.txt
rem ============================================================
setlocal
cd /d "%~dp0"

set "VERFILE=version.txt"
if not exist "%VERFILE%" ( echo [ERROR] Missing %VERFILE%. & pause & exit /b 1 )
set /p VERSION=<"%VERFILE%"
set VERSION=%VERSION: =%

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo [BUILD] Inno Setup 6 not found; installing through winget...
    winget install JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements --silent
    if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
    if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)

if not defined ISCC (
    echo [ERROR] Could not install Inno Setup. Install it manually: https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

echo [BUILD] Compiling installer (%ISCC%)...
"..\.venv\Scripts\python.exe" -B "..\scripts\download_webview2.py"
if errorlevel 1 ( echo [ERROR] WebView2 payload verification failed. & exit /b 1 )
"%ISCC%" "/DMyAppVersion=%VERSION%" "marvin.iss"
if errorlevel 1 ( echo [ERROR] Compilation failed. & pause & exit /b 1 )

echo.
echo [BUILD] DONE: dist\Marvin-Setup-%VERSION%-Minimal.exe
echo [BUILD] For both Minimal and Full, use installer\release.bat.
pause
