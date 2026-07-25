@echo off
REM ============================================================================
REM  Build the lazyTTS Windows installers with Inno Setup (iscc.exe).
REM    * lazyTTS-Setup.exe      - self-contained (wraps dist\lazyTTS; run build.bat first)
REM    * lazyTTS-Net-Setup.exe  - lightweight net-installer (downloads everything)
REM  Output goes to .\installer_out\
REM
REM  Requires Inno Setup 6.1+  ->  winget install JRSoftware.InnoSetup
REM ============================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM --- locate iscc.exe (auto-install if missing) ---
call :find_iscc

REM 1) try winget
if not defined ISCC (
    where winget >nul 2>nul
    if !errorlevel!==0 (
        echo Inno Setup not found - installing via winget ...
        winget install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements
        call :find_iscc
    )
)

REM 2) fall back to a direct download from jrsoftware.org
if not defined ISCC (
    echo Downloading the Inno Setup installer from jrsoftware.org ...
    powershell -NoProfile -Command "try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://jrsoftware.org/download.php/is.exe' -OutFile '%TEMP%\innosetup-latest.exe' -UseBasicParsing; exit 0 } catch { exit 1 }"
    if exist "%TEMP%\innosetup-latest.exe" (
        echo Installing Inno Setup silently ...
        "%TEMP%\innosetup-latest.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
        call :find_iscc
    ) else (
        echo [WARN] Could not download the Inno Setup installer ^(no internet?^).
    )
)

if not defined ISCC (
    echo(
    echo [ERROR] Inno Setup ^(iscc.exe^) still not found.
    echo         Install it manually from https://jrsoftware.org/isdl.php
    echo         then re-run this script.
    pause
    exit /b 1
)
echo Using Inno Setup: !ISCC!
echo(
goto :after_iscc

:find_iscc
set "ISCC="
for %%P in (iscc.exe) do if exist "%%~$PATH:P" set "ISCC=%%~$PATH:P"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
exit /b 0

:after_iscc

REM --- self-contained (needs the PyInstaller build) ---
if exist "dist\lazyTTS\lazyTTS.exe" (
    echo Building self-contained installer ^(lazyTTS-Setup.exe^) ...
    "!ISCC!" "installer\lazytts.iss"
) else (
    echo [skip] dist\lazyTTS\lazyTTS.exe not found - run build.bat first to build the
    echo        self-contained installer. Building the net-installer only.
)
echo(

REM --- net-installer (source only) ---
echo Building net-installer ^(lazyTTS-Net-Setup.exe^) ...
"!ISCC!" "installer\lazytts-net.iss"

echo(
echo Done. See .\installer_out\
pause
