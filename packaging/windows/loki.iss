; LOKI for Windows - Inno Setup 6 script (https://jrsoftware.org/isinfo.php).
;
;   python tools\make_release.py                                   -> dist\release\seed\
;   python tools\bundle_runtime.py                                 -> dist\runtime\  (Python + packages)
;   cargo build --release --manifest-path packaging\launcher\Cargo.toml   -> Loki.exe
;   iscc /DLokiVersion=0.17.0 packaging\windows\loki.iss            -> dist\Loki-Setup-0.17.0.exe
; (.github/workflows/installers.yml does all four on a v* tag.)
;
; Zero dependencies (session 30): the installer CARRIES LOKI's own Python (python-build-standalone,
; with every package already installed), so the first start downloads nothing and works offline.
; A per-user install (no admin rights): the files go to %LOCALAPPDATA%\Programs\Loki, LOKI's data
; (chats, settings, keys, models) to %LOCALAPPDATA%\Loki, which uninstalling keeps. The shortcuts
; run Loki.exe (packaging/launcher, a tiny native launcher: no console window, ever), which starts
; runtime\python\pythonw.exe loki_launch.py. Updates come as signed release zips
; (engine/release_update.py), downloaded and checked in the background.
; Without dist\runtime (a slim build) the old way still works: bootstrap.ps1 downloads Python once.
; Signing: see docs/INSTALL.md ("Signing").

#ifndef LokiVersion
  #define LokiVersion "0.0.0"
#endif
#define SeedDir "..\..\dist\release\seed"
#define RuntimeDir "..\..\dist\runtime"
#ifndef LauncherExe
  #define LauncherExe "..\launcher\target\release\Loki.exe"
#endif
#if FileExists(AddBackslash(SourcePath) + RuntimeDir + "\python\pythonw.exe")
  #define Bundled
#endif
#if FileExists(AddBackslash(SourcePath) + LauncherExe) || FileExists(LauncherExe)
  #define HaveLauncher
#endif

[Setup]
AppId={{5B0C6E7A-2D3F-4E47-9C1B-6A8E3F1D0A0C}
AppName=LOKI
AppVersion={#LokiVersion}
AppPublisher=LOKI (m03dev)
AppPublisherURL=https://github.com/m03dev/loki
AppSupportURL=https://github.com/m03dev/loki/issues
DefaultDirName={localappdata}\Programs\Loki
DefaultGroupName=LOKI
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Loki-Setup-{#LokiVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=LOKI
#ifdef HaveLauncher
UninstallDisplayIcon={app}\Loki.exe
#endif
LicenseFile=..\..\LICENSE
SetupLogging=yes
CloseApplications=yes

[Languages]
; official Inno Setup translations only (Arabic and Hindi are unofficial ones: add them from jrsoftware.org/files/istrans if wanted)
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SeedDir}\*"; DestDir: "{app}\seed"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\installer\loki_launch.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\installer\bootstrap.ps1"; DestDir: "{app}"; Flags: ignoreversion
#ifdef Bundled
Source: "{#RuntimeDir}\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs createallsubdirs ignoreversion
#endif
#ifdef HaveLauncher
Source: "{#LauncherExe}"; DestDir: "{app}"; DestName: "Loki.exe"; Flags: ignoreversion
#endif

[Icons]
#ifdef HaveLauncher
Name: "{group}\LOKI"; Filename: "{app}\Loki.exe"; WorkingDir: "{app}"; Comment: "Open LOKI"
Name: "{autodesktop}\LOKI"; Filename: "{app}\Loki.exe"; WorkingDir: "{app}"; Tasks: desktopicon
#else
  #ifdef Bundled
Name: "{group}\LOKI"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: """{app}\loki_launch.py"" --seed ""{app}\seed"""; \
  WorkingDir: "{app}"; Comment: "Open LOKI"
Name: "{autodesktop}\LOKI"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: """{app}\loki_launch.py"" --seed ""{app}\seed"""; \
  WorkingDir: "{app}"; Tasks: desktopicon
  #else
Name: "{group}\LOKI"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\bootstrap.ps1"""; \
  WorkingDir: "{app}"; Comment: "Open LOKI"
Name: "{autodesktop}\LOKI"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\bootstrap.ps1"""; \
  WorkingDir: "{app}"; Tasks: desktopicon
  #endif
#endif
Name: "{group}\Uninstall LOKI"; Filename: "{uninstallexe}"

[Run]
#ifndef Bundled
; a slim build: LOKI's own Python and packages are downloaded once (a few minutes, needs the internet)
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\bootstrap.ps1"" -Setup"; \
  StatusMsg: "Downloading LOKI's Python and packages (one time, a few minutes)..."; Flags: runhidden waituntilterminated
#endif
#ifdef HaveLauncher
Filename: "{app}\Loki.exe"; Description: "Open LOKI now"; Flags: postinstall nowait skipifsilent
#else
  #ifdef Bundled
Filename: "{app}\runtime\python\pythonw.exe"; Parameters: """{app}\loki_launch.py"" --seed ""{app}\seed"""; \
  Description: "Open LOKI now"; Flags: postinstall nowait skipifsilent
  #else
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\bootstrap.ps1"""; \
  Description: "Open LOKI now"; Flags: postinstall nowait skipifsilent runhidden
  #endif
#endif

[UninstallDelete]
; the program files only; %LOCALAPPDATA%\Loki (your chats, settings, keys) is kept - delete it by hand to remove everything
Type: filesandordirs; Name: "{app}\seed"
Type: filesandordirs; Name: "{app}\runtime"
