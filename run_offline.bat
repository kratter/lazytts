@echo off
REM Launch lazyTTS in fully-offline mode (no Hugging Face network access).
REM Requires make_offline.bat to have populated .\hf_cache first.
setlocal
cd /d "%~dp0"
set "LAZYTTS_OFFLINE=1"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
) else (
    python app.py
)
endlocal
