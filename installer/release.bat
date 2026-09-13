@echo off
rem ============================================================
rem  RELEASE: build nove verze Marvin (exe + instalator)
rem  - spusti testy, prebuilduje exe, zkompiluje instalator
rem    s verzi z version.txt (stejne cislo zobrazuje aplikace)
rem  - vysledek: dist\Marvin-Setup-<verze>.exe
rem  Reinstall u zakladu: vse je rychle (venv/modely zustavaji,
rem  setup krok odskrtni - program se jen prekopiruje)
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0.."
set "PYTHONUTF8=1"

set "VERFILE=installer\version.txt"
if not exist "%VERFILE%" ( echo 1.7.0> "%VERFILE%" )
set /p VERSION=<"%VERFILE%"
set VERSION=%VERSION: =%

echo ============================================================
echo  RELEASE %VERSION%  (testy -^> exe -^> instalator)
echo ============================================================

echo [FRONTEND] Building the local workspace...
".venv\Scripts\python.exe" -B scripts\download_webview2.py
if errorlevel 1 ( echo [ERROR] WebView2 payload verification failed. & exit /b 1 )
call npm --prefix frontend ci --no-audit --no-fund
if errorlevel 1 ( echo [ERROR] Frontend dependencies failed. & exit /b 1 )
call npm --prefix frontend run build
if errorlevel 1 ( echo [ERROR] Frontend build failed. & exit /b 1 )
".venv\Scripts\python.exe" scripts\build_manuals.py
if errorlevel 1 ( echo [ERROR] Manual build failed. & exit /b 1 )

echo [1/3] Testy...
".venv\Scripts\python.exe" tests\test_core.py >nul 2>&1
if errorlevel 1 (
    echo [CHYBA] Testy neprosly - build zastaven.
    ".venv\Scripts\python.exe" tests\test_core.py
    pause & exit /b 1
)
echo        OK - vsechny testy prosly.
".venv\Scripts\python.exe" -B -m unittest tests.test_workspace tests.test_runtime_support tests.test_prompt_performance tests.test_history_recovery tests.test_webview_runtime
if errorlevel 1 ( echo [ERROR] Workspace integration tests failed. & exit /b 1 )

echo [2/3] Build Marvin.exe...
call installer\build_exe.bat
if errorlevel 1 ( echo [CHYBA] Exe build selhal. & pause & exit /b 1 )

echo [3/3] Kompilace instalatoru %VERSION%...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC ( echo [CHYBA] ISCC nenalezen. & pause & exit /b 1 )
"%ISCC%" "/DMyAppVersion=%VERSION%" installer\marvin.iss
if errorlevel 1 ( echo [CHYBA] Instalator build selhal. & pause & exit /b 1 )
".venv\Scripts\python.exe" scripts\build_full_payload.py
if errorlevel 1 ( echo [ERROR] Full payload build failed. & exit /b 1 )
".venv\Scripts\python.exe" tests\check_full_runtime.py
if errorlevel 1 ( echo [ERROR] Full runtime verification failed. & exit /b 1 )
"%ISCC%" "/DMyAppVersion=%VERSION%" /DFullBuild installer\marvin.iss
if errorlevel 1 ( echo [ERROR] Full installer build failed. & exit /b 1 )

echo.
echo ============================================================
echo  RELEASE HOTOVO: dist\Marvin-Setup-%VERSION%-Minimal.exe and -Full.exe
echo  Verze aplikace i instalatoru: %VERSION%
echo ============================================================
endlocal
