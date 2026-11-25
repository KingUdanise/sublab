; SubLab — installer Windows (Inno Setup 6)
; Compila con:  iscc installer.iss     (oppure build_installer.ps1)

#define AppName "SubLab"
#define AppVersion "0.1.0"
#define AppPublisher "SubLab"
#define AppId "{{0D6F7E52-3B2A-4C9E-9A41-5F2C1B7D8E44}"
#define PluginDir "{userappdata}\Blackmagic Design\DaVinci Resolve\Support\Workflow Integration Plugins\SubLab"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\SubLab
DefaultGroupName=SubLab
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=SubLabSetup
SetupIconFile=assets\sublab.ico
UninstallDisplayIcon={app}\assets\sublab.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableDirPage=auto
DisableWelcomePage=no
AppMutex=SubLabAppMutex

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "resolveplugin"; Description: "Installa SubLab anche nel menu Workspace di DaVinci Resolve"; GroupDescription: "Integrazione Resolve:"; Flags: checkedonce

[Files]
Source: "app.pyw";        DestDir: "{app}"; Flags: ignoreversion
Source: "server.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "bridge.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "asr.py";         DestDir: "{app}"; Flags: ignoreversion
Source: "fonts.py";       DestDir: "{app}"; Flags: ignoreversion
Source: "push.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "make_icon.py";   DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "README.md";      DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "web\*";          DestDir: "{app}\web"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\sublab.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "wip\manifest.xml"; DestDir: "{app}\wip"; Flags: ignoreversion skipifsourcedoesntexist
Source: "wip\main.js";      DestDir: "{app}\wip"; Flags: ignoreversion skipifsourcedoesntexist
; plugin per il menu Workspace (solo se l'utente lo vuole)
Source: "wip\manifest.xml"; DestDir: {#PluginDir}; Tasks: resolveplugin; Flags: ignoreversion
Source: "wip\main.js";      DestDir: {#PluginDir}; Tasks: resolveplugin; Flags: ignoreversion

[Icons]
Name: "{group}\SubLab"; Filename: "{code:GetPythonW}"; Parameters: """{app}\app.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\sublab.ico"
Name: "{group}\Disinstalla SubLab"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SubLab"; Filename: "{code:GetPythonW}"; Parameters: """{app}\app.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\sublab.ico"; Tasks: desktopicon

[Run]
Filename: "{code:GetPythonW}"; Parameters: """{app}\app.pyw"""; WorkingDir: "{app}"; Description: "Avvia SubLab"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\out"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\web\__pycache__"
Type: files; Name: {#PluginDir}\server_path.txt
Type: files; Name: {#PluginDir}\manifest.xml
Type: files; Name: {#PluginDir}\main.js

[Code]
var
  PythonW: String;
  DepsOK: Boolean;
  DepsMsg: String;

{ --- ricerca dell'interprete Python --- }

function CandidatePythonExe(Version: String; Root: Integer; Silent: Boolean): String;
var
  P: String;
begin
  Result := '';
  if RegQueryStringValue(Root, 'SOFTWARE\Python\PythonCore\' + Version + '\InstallPath',
                         'ExecutablePath', P) and FileExists(P) then
    Result := P;
end;

function TestDeps(PyExe: String): Boolean;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{cmd}'),
       '/c ""' + PyExe + '" -c "import fastapi,uvicorn,webview,faster_whisper" > nul 2>&1"',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := (Code = 0);
end;

function WindowedOf(PyExe: String): String;
begin
  Result := ExtractFilePath(PyExe) + 'pythonw.exe';
  if not FileExists(Result) then
    Result := PyExe;
end;

procedure ResolvePython();
var
  Versions: array[0..5] of String;
  Roots: array[0..1] of Integer;
  i, j, k: Integer;
  Py, FirstFound: String;
begin
  Versions[0] := '3.13'; Versions[1] := '3.12'; Versions[2] := '3.11';
  Versions[3] := '3.10'; Versions[4] := '3.9';  Versions[5] := '3.8';
  Roots[0] := HKCU; Roots[1] := HKLM;
  FirstFound := '';
  DepsOK := False;
  DepsMsg := '';

  { 1) primo interprete che ha davvero tutte le dipendenze }
  for k := 0 to 5 do
    for j := 0 to 1 do
    begin
      Py := CandidatePythonExe(Versions[k], Roots[j], False);
      if Py = '' then
        Continue;
      if FirstFound = '' then
        FirstFound := Py;
      if TestDeps(Py) then
      begin
        PythonW := WindowedOf(Py);
        DepsOK := True;
        Exit;
      end;
    end;

  { 2) nessuno ha le dipendenze: uso il primo Python trovato e lo dico all'utente }
  if FirstFound <> '' then
  begin
    PythonW := WindowedOf(FirstFound);
    DepsMsg := 'Interprete trovato: ' + FirstFound;
    Exit;
  end;

  { 3) pythonw generico dal PATH }
  PythonW := 'pythonw.exe';
  DepsMsg := 'Nessuna installazione Python trovata nel registro.';
end;

function GetPythonW(Param: String): String;
begin
  if PythonW = '' then
    ResolvePython();
  Result := PythonW;
end;

{ --- scrittura dei percorsi per il plugin di Resolve --- }

procedure WriteServerPaths();
var
  P: String;
begin
  SaveStringToFile(ExpandConstant('{app}') + '\server_path.txt',
                   ExpandConstant('{app}') + '\server.py', False);
  if WizardIsTaskSelected('resolveplugin') then
  begin
    P := ExpandConstant('{#PluginDir}') + '\server_path.txt';
    ForceDirectories(ExtractFilePath(P));
    SaveStringToFile(P, ExpandConstant('{app}') + '\server.py', False);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteServerPaths();
end;

function InitializeSetup(): Boolean;
begin
  ResolvePython();
  Result := True;
  if not DepsOK and (Pos('pythonw.exe', PythonW) = 0) then
  begin
    MsgBox('SubLab richiede Python 3.10 o superiore.' + #13#10 +
           'Installalo da https://www.python.org/downloads/ e rilancia questo installer.',
           mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if not DepsOK then
    if MsgBox('Alcune dipendenze Python non risultano installate.' + #13#10 + #13#10 +
              DepsMsg + #13#10 + #13#10 +
              'Puoi installare SubLab ugualmente e sistemarle dopo con:' + #13#10 +
              '    pip install -r requirements.txt' + #13#10 + #13#10 + 'Continuare?',
              mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if DirExists(ExpandConstant('{#PluginDir}')) then
      DelTree(ExpandConstant('{#PluginDir}'), True, True, True);
  end;
end;

