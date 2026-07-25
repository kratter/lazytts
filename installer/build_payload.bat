@echo off
REM ============================================================================
REM  Build the payload zip for the SLIM installer.
REM  The slim installer ships only lazyTTS.exe (~88 MB) and downloads this zip
REM  (the ~4.9 GB _internal folder, compressed to ~2 GB) at install time.
REM
REM  1) run build.bat first (produces dist\lazyTTS)
REM  2) run this  -> installer_out\lazyTTS-payload.zip
REM  3) UPLOAD that zip to your host (GitHub Release, web server, etc.)
REM  4) put its URL in installer\lazytts-slim.iss  (#define PayloadURL ...)
REM  5) build the slim installer (build_installer.bat)
REM ============================================================================
setlocal
cd /d "%~dp0\.."

if not exist "dist\lazyTTS\_internal" (
    echo [ERROR] dist\lazyTTS\_internal not found. Run build.bat first.
    pause
    exit /b 1
)
if not exist "installer_out" mkdir "installer_out"

echo Packing dist\lazyTTS\_internal into installer_out\lazyTTS-payload.zip ...
echo (Large - this takes a few minutes.)
REM tar.exe (bsdtar) ships with Windows 10+ and handles huge file sets + .zip.
tar.exe -a -c -f "installer_out\lazyTTS-payload.zip" -C "dist\lazyTTS" _internal
if errorlevel 1 (
    echo [FAILED] Could not create the payload zip.
    pause
    exit /b 1
)

echo(
for %%F in ("installer_out\lazyTTS-payload.zip") do echo Created %%~fF  (%%~zF bytes)
echo(
echo Next: upload lazyTTS-payload.zip to your host and set its URL in
echo       installer\lazytts-slim.iss  (#define PayloadURL).
echo NOTE: GitHub Release assets cap at 2 GB each - if the zip exceeds that,
echo       host it elsewhere or split it.
pause
