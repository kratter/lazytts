@echo off
REM ============================================================================
REM  lazyTTS one-shot setup: creates a venv and installs everything required.
REM  Detects your NVIDIA GPU and installs the matching PyTorch build
REM  (cu128 for RTX 50-series / Blackwell), then all app dependencies.
REM  Also checks for ffmpeg and offers to install it via winget.
REM ============================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo(
echo ==========================================================
echo   lazyTTS - eBook to Audiobook  :  environment setup
echo ==========================================================
echo(

REM --- 1. Locate a compatible Python (Kokoro needs 3.10 - 3.12) --------------
set "PY="
REM Prefer an explicit supported version via the py launcher, newest first.
for %%V in (3.12 3.11 3.10) do (
    if not defined PY (
        py -%%V --version >nul 2>nul && set "PY=py -%%V"
    )
)
REM Fall back to whatever python is on PATH, then validate its version below.
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo [ERROR] Python was not found on PATH.
    echo         Install Python 3.12 from https://www.python.org/downloads/
    echo         and tick "Add python.exe to PATH" during install.
    goto :fail
)
echo [1/6] Using Python: %PY%
%PY% --version
%PY% -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,12) else 1)"
if errorlevel 1 (
    echo(
    echo [ERROR] Kokoro requires Python 3.10-3.12, but the selected Python is not.
    %PY% --version
    echo         Install Python 3.12 from https://www.python.org/downloads/,
    echo         then re-run setup.bat ^(it will rebuild the .venv^).
    goto :fail
)

REM --- 2. Create the virtual environment -------------------------------------
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,12) else 1)"
    if errorlevel 1 (
        echo [2/6] Existing .venv uses an unsupported Python - rebuilding ...
        rmdir /s /q .venv
        %PY% -m venv .venv
        if errorlevel 1 goto :fail
    ) else (
        echo [2/6] Reusing existing virtual environment .venv
    )
) else (
    echo [2/6] Creating virtual environment .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)
set "VENV_PY=.venv\Scripts\python.exe"

echo [3/6] Upgrading pip / setuptools / wheel ...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :fail

REM --- 3. Install PyTorch matching the GPU -----------------------------------
where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
    echo [4/6] NVIDIA GPU detected - installing CUDA 12.8 PyTorch build ...
    nvidia-smi --query-gpu=name --format=csv,noheader 2>nul
    "%VENV_PY%" -m pip install torch --index-url https://download.pytorch.org/whl/cu128
    if errorlevel 1 (
        echo [WARN] cu128 install failed. Falling back to CPU PyTorch build ...
        "%VENV_PY%" -m pip install torch
        if errorlevel 1 goto :fail
    )
) else (
    echo [4/6] No NVIDIA GPU detected - installing CPU PyTorch build ...
    "%VENV_PY%" -m pip install torch
    if errorlevel 1 goto :fail
)

REM --- 4. Install app deps in STAGES -----------------------------------------
REM Installing everything at once makes pip's resolver explode
REM ("resolution-too-deep"). Staged installs each resolve a small graph.
echo [5/6] Installing application dependencies (staged) ...

echo    - core: UI, document parsers, audio ...
"%VENV_PY%" -m pip install "gradio>=4.44" "PyMuPDF>=1.24" "ebooklib>=0.18" "beautifulsoup4>=4.12" "lxml>=5.0" "python-docx>=1.1" "soundfile>=0.12" "numpy>=1.26" "num2words>=0.5.10" "pyttsx3>=2.90" "pyinstaller>=6.10"
if errorlevel 1 goto :fail

echo    - Kokoro neural TTS (English) ...
"%VENV_PY%" -m pip install "kokoro>=0.9.4" || echo    [WARN] Kokoro failed to install - the app will still run on other engines.

echo    - Piper neural TTS (German ^& more) ...
"%VENV_PY%" -m pip install piper-tts || echo    [WARN] Piper failed to install - German voices unavailable (Kokoro/SAPI still work).

echo    - Translation tokenizer (sentencepiece, for NLLB-200) ...
"%VENV_PY%" -m pip install "sentencepiece>=0.2.0" || echo    [WARN] sentencepiece failed to install - offline translation unavailable.

echo    - Coqui XTTS-v2 (multilingual, high quality; optional/heavy) ...
"%VENV_PY%" -m pip install "coqui-tts>=0.27.0" || echo    [WARN] coqui-tts failed to install - XTTS engine unavailable (Kokoro/Piper/MMS still work).
REM torchcodec: audio I/O backend coqui-tts needs on PyTorch >=2.9 (uses ffmpeg libs).
"%VENV_PY%" -m pip install torchcodec || echo    [WARN] torchcodec failed - XTTS may not import (Kokoro/Piper/MMS still work).

echo    - Native desktop window (pywebview) ...
"%VENV_PY%" -m pip install "pywebview>=5.0" || echo    [WARN] pywebview failed - the app will open in your browser instead.

REM --- 4b. Guard: another package may have pulled a CPU torch, clobbering the
REM cu128 GPU build. If so (and a GPU exists), reinstall the cu128 build.
where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
    "%VENV_PY%" -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"
    if errorlevel 1 (
        echo(
        echo    [FIX] GPU PyTorch was replaced by a CPU build during dependency
        echo          installs. Reinstalling the cu128 GPU build ...
        "%VENV_PY%" -m pip install --force-reinstall --no-deps torch --index-url https://download.pytorch.org/whl/cu128
    ) else (
        echo    GPU PyTorch OK.
    )
)

REM --- 5. ffmpeg (needed for MP3/M4B + loudness normalization) ---------------
echo [6/6] Ensuring ffmpeg is installed ...
where ffmpeg >nul 2>nul
if %errorlevel%==0 (
    echo       ffmpeg already installed.
) else (
    where winget >nul 2>nul
    if !errorlevel!==0 (
        echo       Installing ffmpeg via winget ^(Gyan.FFmpeg^) ...
        winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
        REM winget updates PATH for NEW shells; make ffmpeg usable in THIS run too.
        for /f "delims=" %%P in ('where /r "%LOCALAPPDATA%\Microsoft\WinGet\Packages" ffmpeg.exe 2^>nul') do set "PATH=%%~dpP;!PATH!"
        where ffmpeg >nul 2>nul && echo       ffmpeg installed. || echo       ffmpeg installed - open a NEW terminal so it is on PATH.
    ) else (
        echo       [WARN] winget not available. Install ffmpeg manually:
        echo              https://www.gyan.dev/ffmpeg/builds/  ^(or: winget install Gyan.FFmpeg^)
        echo              Without ffmpeg only WAV output works ^(no MP3/M4B^).
    )
)

REM --- 6. Verify the install --------------------------------------------------
echo(
echo Verifying environment ...
"%VENV_PY%" -c "import gradio, soundfile, numpy, fitz, ebooklib, docx; print('  core deps OK, gradio', gradio.__version__)"
"%VENV_PY%" -c "import torch; print('  torch', torch.__version__, '| CUDA available:', torch.cuda.is_available()); [print('   -', torch.cuda.get_device_name(i)) for i in range(torch.cuda.device_count())]"
"%VENV_PY%" -c "import kokoro; print('  kokoro import OK')" 2>nul || echo   [WARN] kokoro not importable - Kokoro engine unavailable.
"%VENV_PY%" -c "import piper; print('  piper import OK')" 2>nul || echo   [WARN] piper not importable - German (Piper) voices unavailable.
"%VENV_PY%" -c "import sentencepiece, transformers; print('  translation deps OK (NLLB-200 via transformers)')" 2>nul || echo   [WARN] sentencepiece/transformers missing - offline translation unavailable.
"%VENV_PY%" -c "from transformers import VitsModel; print('  MMS-TTS OK (EN/DE/HU via transformers)')" 2>nul || echo   [WARN] VitsModel missing - MMS engine unavailable.
"%VENV_PY%" -c "import TTS; print('  Coqui XTTS-v2 import OK')" 2>nul || echo   [WARN] coqui-tts not importable - XTTS engine unavailable.
"%VENV_PY%" -c "import webview; print('  pywebview OK (native desktop window)')" 2>nul || echo   [note] pywebview not importable - app opens in the browser.
"%VENV_PY%" -c "import gradio, soundfile, numpy, fitz, ebooklib, docx" 2>nul && echo   (at minimum the SAPI engine is ready) || echo   [WARN] core deps missing - see errors above.
where ffmpeg >nul 2>nul && echo   ffmpeg OK ^(MP3/M4B + loudness enabled^) || echo   [note] ffmpeg not on PATH yet - reopen terminal, or WAV-only for now.

echo(
echo ==========================================================
echo   Setup complete.
echo   Start the app with:   run.bat
echo   (First Kokoro run downloads the model from Hugging Face.)
echo ==========================================================
echo(
if /i not "%~1"=="nopause" pause
goto :eof

:fail
echo(
echo [FAILED] Setup did not complete. Scroll up for the first error above.
echo(
if /i not "%~1"=="nopause" pause
exit /b 1
