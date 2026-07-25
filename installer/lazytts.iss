; ── lazyTTS self-contained installer ─────────────────────────────────
; Wraps the PyInstaller build (dist\lazyTTS) into lazyTTS-Setup.exe.
; Installs to C:\lazyTTS, adds shortcuts, and (optionally) downloads the
; voice models + installs ffmpeg during setup.
;
; Build:  iscc installer\lazytts.iss      (needs Inno Setup 6.1+; run build.bat first)
; Requires dist\lazyTTS\lazyTTS.exe to exist.

#define AppName "lazyTTS"
#define AppVersion "0.1.0"
#define AppExe "lazyTTS.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=lazyTTS
DefaultDirName=C:\lazyTTS
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\installer_out
OutputBaseFilename=lazyTTS-Setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
; The bundled app is several GB.
DiskSpanning=no

[Files]
Source: "..\dist\lazyTTS\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a &desktop shortcut"
Name: dlmodels; Description: "Download voice models now (needs internet, ~1 GB) into {app}\hf_cache"; GroupDescription: "During install:"
Name: dltranslate; Description: "Also download the offline translation model (NLLB-200, ~2.4 GB) — only needed to translate books"; GroupDescription: "During install:"; Flags: unchecked
Name: dlxtts; Description: "Also download the Coqui XTTS-v2 voices (~1.8 GB) — highest quality but slow, non-commercial"; GroupDescription: "During install:"; Flags: unchecked
Name: ffmpeg; Description: "Install ffmpeg via winget (for MP3/M4B + loudness)"; GroupDescription: "During install:"

[Run]
; Download Kokoro + Piper + MMS voices into {app}\hf_cache (lazyTTS.exe --prefetch).
Filename: "{app}\{#AppExe}"; Parameters: "--prefetch --skip-translation --skip-xtts"; StatusMsg: "Downloading voice models (this can take several minutes)…"; Flags: runhidden waituntilterminated; Tasks: dlmodels
; Optionally download the translation model.
Filename: "{app}\{#AppExe}"; Parameters: "--prefetch --only-translation"; StatusMsg: "Downloading translation model (NLLB-200, ~2.4 GB)…"; Flags: runhidden waituntilterminated; Tasks: dltranslate
; Optionally download the XTTS-v2 voices.
Filename: "{app}\{#AppExe}"; Parameters: "--prefetch --only-xtts"; StatusMsg: "Downloading XTTS-v2 voices (~1.8 GB)…"; Flags: runhidden waituntilterminated; Tasks: dlxtts
; ffmpeg via winget (installs system-wide; the app also finds a local ffmpeg.exe).
Filename: "powershell.exe"; Parameters: "-NoProfile -Command ""winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements"""; StatusMsg: "Installing ffmpeg…"; Flags: runhidden waituntilterminated; Tasks: ffmpeg
; Offer to launch at the end.
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\hf_cache"
Type: filesandordirs; Name: "{app}\audiobooks"
Type: files; Name: "{app}\settings.json"
