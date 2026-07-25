@echo off
REM ============================================================================
REM  Pre-download EVERYTHING needed for fully-offline use into .\hf_cache:
REM    * Kokoro model + all voices (English)
REM    * Piper voices (German, Hungarian & more)
REM    * Meta MMS-TTS voices (English/German/Hungarian)
REM    * Coqui XTTS-v2 voices (~1.8 GB, multilingual)
REM    * NLLB-200 translation model (~2.4 GB)
REM  Run this ONCE, while online, after setup.bat.
REM ============================================================================
setlocal
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] .venv not found. Run setup.bat first.
    echo(
    pause
    exit /b 1
)

echo ==========================================================
echo   Downloading all models into .\hf_cache for offline use
echo   Kokoro (English) + Piper + MMS (EN/DE/HU) + XTTS-v2 voices
echo   + NLLB-200 translation model (~2.4 GB)
echo   Needs internet; this can take a while on the first run (several GB).
echo ==========================================================
echo(

"%VENV_PY%" prefetch_models.py
set "RC=%errorlevel%"

echo(
if "%RC%"=="0" (
    echo ==========================================================
    echo   Offline cache ready in .\hf_cache
    echo   Run the app with NO internet using:  run_offline.bat
    echo   For the .exe: ship the hf_cache folder next to lazyTTS.exe
    echo ==========================================================
) else (
    echo [FAILED] Prefetch did not complete. See errors above.
)
echo(
pause
exit /b %RC%
