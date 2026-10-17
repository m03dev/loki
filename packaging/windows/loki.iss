; LOKI for Windows - Inno Setup 6 script (https://jrsoftware.org/isinfo.php).
;
;   python tools\make_release.py --feed <feed url>          -> dist\release\seed\
;   iscc /DLokiVersion=0.16.500 packaging\windows\loki.iss   -> dist\Loki-Setup-0.16.500.exe
;
; A per-user install (no admin rights): the files go to %LOCALAPPDATA%\Programs\Loki, LOKI's data
; (chats, settings, keys, its Python and models) to %LOCALAPPDATA%\Loki, which uninstalling keeps.
; At the end of the install, bootstrap.ps1 -Setup downloads LOKI's own Python (uv + Python 3.12,
; one time) and its packages; the shortcuts run bootstrap.ps1, which opens LOKI through
; loki_launch.py. Updates then come as release zips (engine/release_update.py), checked before use.
; Signing: see docs/INSTALL.md ("Signing").

#ifndef LokiVersion
  #define LokiVersion "0.0.0"
#endif
#define SeedDir "..\..\dist\release\seed"

[Setup]
AppId={{5B0C6E7A-2D3F-4E47-9C1B-6A8E3F1D0A0C}
AppName=LOKI
AppVersion={#LokiVersion}
AppPublisher=LOKI
DefaultDirName={localappdata}\Programs\Loki
DefaultGroupName=LOKI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Loki-Setup-{#LokiVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible arm64
ArchitecturesInstallIn64BitMode=x64compatible arm64
UninstallDisplayName=LOKI
LicenseFile=..\..\LICENSE
SetupLogging=yes

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

[Icons]
Name: "{group}\LOKI"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\bootstrap.ps1"""; \
  WorkingDir: "{app}"; Comment: "Open LOKI"
Name: "{autodesktop}\LOKI"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\bootstrap.ps1"""; \
  WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Uninstall LOKI"; Filename: "{uninstallexe}"

[Run]
; one time: LOKI's own Python and packages (a few minutes, needs the internet)
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\bootstrap.ps1"" -Setup"; \
  StatusMsg: "Downloading LOKI's Python and packages (one time, a few minutes)..."; Flags: runhidden waituntilterminated
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\bootstrap.ps1"""; \
  Description: "Open LOKI now"; Flags: postinstall nowait skipifsilent runhidden

[UninstallDelete]
; the program files only; %LOCALAPPDATA%\Loki (your chats, settings, keys) is kept - delete it by hand to remove everything
Type: filesandordirs; Name: "{app}\seed"
