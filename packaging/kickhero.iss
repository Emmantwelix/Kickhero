; Inno Setup script for Kickhero. Built by packaging\build.py:
;   ISCC.exe /DAppVersion=0.2.0 packaging\kickhero.iss

#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif

[Setup]
AppId={{6B0E3C1A-8F7D-4C52-9A61-2E4B7D9C8A15}
AppName=Kickhero
AppVersion={#AppVersion}
AppPublisher=Kickhero contributors
DefaultDirName={autopf}\Kickhero
DefaultGroupName=Kickhero
DisableProgramGroupPage=yes
; Install for the current user by default (no admin needed); the dialog offers all users
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\installer
OutputBaseFilename=Kickhero-Setup-{#AppVersion}
SetupIconFile=..\kickhero\assets\kickhero.ico
UninstallDisplayIcon={app}\Kickhero.exe
LicenseFile=..\LICENSE
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\build\dist\Kickhero\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Kickhero"; Filename: "{app}\Kickhero.exe"
Name: "{autodesktop}\Kickhero"; Filename: "{app}\Kickhero.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Kickhero.exe"; Description: "{cm:LaunchProgram,Kickhero}"; Flags: nowait postinstall skipifsilent
