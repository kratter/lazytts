@echo off
REM Build the standalone lazyTTS.exe with PyInstaller (one-dir).
setlocal
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] .venv not found. Run setup.bat first.
    pause
    exit /b 1
)

echo Building lazyTTS.exe  (this is large and can take 10-40 min) ...
echo(
"%VENV_PY%" -m PyInstaller --noconfirm --clean build\lazytts.spec
set "RC=%errorlevel%"
echo(
if "%RC%"=="0" (
    echo ==========================================================
    echo   Done -> dist\lazyTTS\lazyTTS.exe
    echo   * For offline: copy the hf_cache folder into dist\lazyTTS\
    echo   * ffmpeg must be on PATH (or copy ffmpeg.exe into dist\lazyTTS\)
    echo ==========================================================
) else (
    echo [FAILED] Build failed. Scroll up for the first error.
)
pause
exit /b %RC%
