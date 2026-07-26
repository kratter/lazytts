; ── lazyTTS lightweight net-installer ────────────────────────────────
; Small setup.exe that installs the SOURCE to C:\lazyTTS, then during install
; creates the Python venv, downloads all dependencies (torch cu128, kokoro,
; piper, gradio, ffmpeg) and the voice models — everything fetched at install.
;
; Build:  iscc installer\lazytts-net.iss     (needs Inno Setup 6.1+)
; Result is a few-MB installer; the heavy downloads happen on the user's machine.
;
; NOTE: requires Python 3.10-3.12. If missing, this offers to install it via
; winget; you may then need to re-run setup (PATH refresh) — see README.

#define AppName "lazyTTS"
#define AppVersion "0.7.1"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=lazyTTS
DefaultDirName=C:\lazyTTS
DisableDirPage=no
DisableProgramGroupPage=yes
DefaultGroupName={#AppName}
OutputDir=..\installer_out
OutputBaseFilename=lazyTTS-Net-Setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern

[Files]
; Ship the source tree (NOT the built exe, venv, caches, or outputs).
Source: "..\app.py";              DestDir: "{app}"; Flags: ignoreversion
Source: "..\config.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "..\prefetch_models.py";  DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt";    DestDir: "{app}"; Flags: ignoreversion
Source: "..\readme.md";           DestDir: "{app}"; Flags: ignoreversion
Source: "..\run.bat";             DestDir: "{app}"; Flags: ignoreversion
Source: "..\run_offline.bat";     DestDir: "{app}"; Flags: ignoreversion
Source: "..\setup.bat";           DestDir: "{app}"; Flags: ignoreversion
Source: "..\make_offline.bat";    DestDir: "{app}"; Flags: ignoreversion
Source: "..\lazytts\*";              DestDir: "{app}\lazytts"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\build\lazytts.spec";     DestDir: "{app}\build"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\run.bat"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\run.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a &desktop shortcut"
Name: dltranslate; Description: "Download the offline translation model (NLLB-200, ~2.4 GB) — only needed to translate books"; GroupDescription: "During install:"; Flags: unchecked
Name: dlxtts; Description: "Download the Coqui XTTS-v2 voices (~1.8 GB) — highest quality but slow, non-commercial"; GroupDescription: "During install:"; Flags: unchecked

[Run]
; If Python is missing, install it via winget (may need a new shell afterward).
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -Command ""winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements"""; \
  StatusMsg: "Installing Python 3.12…"; Flags: waituntilterminated; Check: PythonMissing
; Create the venv + install all dependencies (+ ffmpeg) via setup.bat.
Filename: "{app}\setup.bat"; Parameters: "nopause"; WorkingDir: "{app}"; \
  StatusMsg: "Installing dependencies — the console window shows live progress (large download, please wait)…"; \
  Flags: waituntilterminated
; Download the standard TTS voices (Kokoro + Piper + small MMS) — always.
Filename: "{app}\.venv\Scripts\python.exe"; Parameters: """{app}\prefetch_models.py"" --skip-translation --skip-xtts"; WorkingDir: "{app}"; \
  StatusMsg: "Downloading voice models…"; Flags: waituntilterminated
; Download the translation model only if the user opted in (keeps install small).
Filename: "{app}\.venv\Scripts\python.exe"; Parameters: """{app}\prefetch_models.py"" --only-translation"; WorkingDir: "{app}"; \
  StatusMsg: "Downloading translation model (NLLB-200, ~2.4 GB)…"; Flags: waituntilterminated; Tasks: dltranslate
; Download the Coqui XTTS-v2 voices only if the user opted in.
Filename: "{app}\.venv\Scripts\python.exe"; Parameters: """{app}\prefetch_models.py"" --only-xtts"; WorkingDir: "{app}"; \
  StatusMsg: "Downloading XTTS-v2 voices (~1.8 GB)…"; Flags: waituntilterminated; Tasks: dlxtts
Filename: "{app}\run.bat"; Description: "Launch {#AppName}"; WorkingDir: "{app}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\hf_cache"
Type: filesandordirs; Name: "{app}\audiobooks"
Type: files; Name: "{app}\settings.json"

[Code]
function PythonMissing(): Boolean;
var rc: Integer;
begin
  Result := True;
  if Exec('cmd.exe', '/c where py >nul 2>nul', '', SW_HIDE, ewWaitUntilTerminated, rc) and (rc = 0) then
    Result := False;
  if Result and Exec('cmd.exe', '/c where python >nul 2>nul', '', SW_HIDE, ewWaitUntilTerminated, rc) and (rc = 0) then
    Result := False;
end;
