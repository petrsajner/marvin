@echo off
rem ============================================================
rem  Build Marvin.exe (PyInstaller, onedir with icon)
rem  Output: dist\Marvin\Marvin.exe (+ _internal\)
rem ============================================================
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Missing .venv - run scripts\setup_env.py
    pause & exit /b 1
)

echo [BUILD] Installing PyInstaller...
".venv\Scripts\python.exe" -m pip install pyinstaller --quiet

echo [BUILD] Compiling Marvin.exe...
".venv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm --clean --onedir --noconsole ^
    --name Marvin ^
    --icon app_icon.ico ^
    --add-data "installer\version.txt;." ^
    --add-data "harness\locales;harness\locales" ^
    --collect-all webview ^
    --hidden-import clr ^
    launcher\launcher_app.py
if errorlevel 1 ( echo [ERROR] Compilation failed. & pause & exit /b 1 )

echo [BUILD] DONE: dist\Marvin\Marvin.exe
endlocal
