#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName "ACE60 Gamepad"
#define AppPublisher "Vwexp-ytb"
#define AppExeCli "ACE60-Gamepad-CLI.exe"
#define AppExeGui "ACE60-Gamepad-GUI.exe"

[Setup]
AppId={{7E7C0B64-5A8A-47B4-AB6A-2A4A50B2E113}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\ACE60Gamepad
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\dist\installers
OutputBaseFilename=ACE60-Gamepad-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le bureau"; GroupDescription: "Raccourcis supplémentaires :"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExeCli}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#AppExeGui}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ACE60 Gamepad (interface graphique)"; Filename: "{app}\{#AppExeGui}"
Name: "{group}\ACE60 Gamepad (terminal)"; Filename: "{app}\{#AppExeCli}"
Name: "{autodesktop}\ACE60 Gamepad"; Filename: "{app}\{#AppExeGui}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeGui}"; Description: "Lancer ACE60 Gamepad"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\*.exe"
