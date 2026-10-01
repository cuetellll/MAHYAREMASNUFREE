#define MyAppName "MahyarFree"
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define MyAppPublisher "Mahyar"
#define MyAppExeName "MahyarFree.exe"

[Setup]
AppId={{B6C0C863-5DAD-4F73-9E52-33285BD0F9D4}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\MahyarFree
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\release
OutputBaseFilename=MahyarFree-Setup-x64
SetupIconFile=..\mahyarfree\ui\assets\img\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
Uninstallable=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\MahyarFree\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch MahyarFree"; Flags: postinstall nowait skipifsilent
