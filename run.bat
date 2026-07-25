@echo off
REM Launch lazyTTS from the local virtual environment.
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
) else (
    python app.py
)
endlocal
