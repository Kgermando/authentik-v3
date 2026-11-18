; Installateur Inno Setup 6 de Authentik. Compile par build_windows.ps1 (ISCC.exe).
; Editeur : Ministere de la Formation Professionnelle (MFP). Voir AGENTS.md 5 bis.
#define AppVersion GetEnv("AUTHENTIK_VERSION")
#if AppVersion == ""
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{25648931-310E-4A4A-B8C5-5348B2A38FE9}
AppName=Authentik
AppVersion={#AppVersion}
AppPublisher=Ministère de la Formation Professionnelle (MFP)
AppCopyright=© Ministère de la Formation Professionnelle (MFP), RDC
DefaultDirName={autopf}\Authentik
DefaultGroupName=Authentik
UninstallDisplayIcon={app}\Authentik.exe
OutputDir=..\dist
OutputBaseFilename=Authentik-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
; Base SQLite et documents partages par les utilisateurs du poste.
; La desinstallation NE supprime PAS ce dossier (donnees et documents conserves).
Name: "{commonappdata}\Authentik"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{commonappdata}\Authentik\documents"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "..\dist\Authentik\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Authentik"; Filename: "{app}\Authentik.exe"
Name: "{group}\Guide d'utilisation"; Filename: "{app}\GUIDE.md"
Name: "{group}\Désinstaller Authentik"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Authentik"; Filename: "{app}\Authentik.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Authentik.exe"; Description: "{cm:LaunchProgram,Authentik}"; Flags: nowait postinstall skipifsilent
