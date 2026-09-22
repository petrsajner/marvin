@echo off
rem ============================================================
rem  RELEASE: build a new Marvin version (application and installers)
rem  - run tests, rebuild the executable and compile the installers
rem    using version.txt (also displayed by the application)
rem  - output: dist\Marvin-Setup-<version>.exe
rem  An application-only reinstall retains the environment and models.
rem  Skip the environment setup step when only replacing application files.
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0.."
set "PYTHONUTF8=1"

set "VERFILE=installer\version.txt"
if not exist "%VERFILE%" ( echo 1.7.0> "%VERFILE%" )
set /p VERSION=<"%VERFILE%"
set VERSION=%VERSION: =%

echo ============================================================
echo  RELEASE %VERSION%  (tests -^> executable -^> installer)
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

echo [1/3] Tests...
".venv\Scripts\python.exe" tests\test_core.py >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Tests failed; build stopped.
    ".venv\Scripts\python.exe" tests\test_core.py
    pause & exit /b 1
)
echo        OK - all tests passed.
".venv\Scripts\python.exe" -B -m unittest discover -s tests -t . -p "test_*.py"
if errorlevel 1 ( echo [ERROR] Workspace integration tests failed. & exit /b 1 )

echo [2/3] Build Marvin.exe...
call installer\build_exe.bat
if errorlevel 1 ( echo [ERROR] Executable build failed. & pause & exit /b 1 )

echo [3/3] Compiling installer %VERSION%...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC ( echo [ERROR] ISCC not found. & pause & exit /b 1 )
"%ISCC%" "/DMyAppVersion=%VERSION%" installer\marvin.iss
if errorlevel 1 ( echo [ERROR] Installer build failed. & pause & exit /b 1 )
".venv\Scripts\python.exe" scripts\build_full_payload.py
if errorlevel 1 ( echo [ERROR] Full payload build failed. & exit /b 1 )
".venv\Scripts\python.exe" tests\check_full_runtime.py
if errorlevel 1 ( echo [ERROR] Full runtime verification failed. & exit /b 1 )
"%ISCC%" "/DMyAppVersion=%VERSION%" /DFullBuild installer\marvin.iss
if errorlevel 1 ( echo [ERROR] Full installer build failed. & exit /b 1 )

echo.
echo ============================================================
echo  RELEASE DONE: dist\Marvin-Setup-%VERSION%-Minimal.exe and -Full.exe
echo  Application and installer version: %VERSION%
echo ============================================================
endlocal
