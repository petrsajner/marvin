; ============================================================
;  Marvin - installer (Inno Setup 6)
;  Build:  installer\build_installer.bat  →  dist\Marvin-Setup-<version>.exe
;
;  Language: the wizard offers English (default) and Czech; the
;  selected language is written to {app}\runtime\ui-language.txt
;  and the app starts in it (English when nothing is selected).
; ============================================================

; Override the version from the command line: ISCC /DMyAppVersion=x.y.z
; (installer\release.bat uses installer\version.txt)
#ifndef MyAppVersion
#define MyAppVersion "1.14.1"
#endif

#define MyAppName "Marvin"
#define MyAppPublisher "Petr Sajner"
#define MyAppExeName "Marvin.exe"
#define MyAppIcon "..\app_icon.ico"

[Setup]
AppId={{8F3A2C1B-6D5E-4F8A-9B7C-2E1D0A4B5C6E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright=© Petr Sajner 2026
DefaultDirName={localappdata}\QwenHarness
DefaultGroupName={#MyAppName}
; Install in the user profile without administrator privileges
PrivilegesRequired=lowest
OutputDir=..\dist
#ifdef FullBuild
OutputBaseFilename=Marvin-Setup-{#MyAppVersion}-Full
#else
OutputBaseFilename=Marvin-Setup-{#MyAppVersion}-Minimal
#endif
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\app_icon.ico
#ifdef FullBuild
Compression=lzma2/fast
#else
Compression=lzma2
#endif
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
CloseApplications=yes
; Always show language selection; English is the default first entry
ShowLanguageDialog=yes

; Remove the old executable after the product rename
[InstallDelete]
Type: files; Name: "{app}\QwenHarness.exe"
; Replace only packaged application code. User data, models and user-skills stay.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\harness"
Type: filesandordirs; Name: "{app}\launcher"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\tests"
Type: filesandordirs; Name: "{app}\skills"
Type: filesandordirs; Name: "{app}\ui_dist"

[Languages]
; First entry = default language (English base after installation).
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "cze"; MessagesFile: "compiler:Languages\Czech.isl"

[CustomMessages]
#include "locales\cs-custom.isl"
en.PrepareDesktop=Preparing desktop components...
en.DesktopSetupFailed=Desktop components could not be prepared. Connect to the internet and run Setup again, or use the Full installer for offline setup.
en.SetupEnvMenu=Set up environment and models
en.BackupSetupMenu=Set up from offline backup
#ifdef FullBuild
en.RunSetupDesc=Download selected models (Python, packages and llama.cpp are included)
#else
en.RunSetupDesc=Set up the environment and download models (requires separately installed 64-bit Python 3.12)
#endif

[Messages]
#include "locales\cs-messages.isl"
#ifdef FullBuild
en.WelcomeLabel2=Marvin Full includes a private Python 3.12 runtime, Python packages, llama.cpp/CUDA libraries and the offline WebView2 installer.%n%nWebView2 is prepared automatically. No system Python or PATH changes are required. NVIDIA drivers remain your responsibility. Models are downloaded separately.%n%nContinue?
#else
en.WelcomeLabel2=This wizard will install [name/ver], a local AI application.%n%nREQUIRED: Install 64-bit Python 3.12 separately and enable "Add Python to PATH" before continuing. Python is not bundled. WebView2 is prepared automatically; internet is required when it is missing.%n%nAfter installation, the environment and selected models will be prepared from an offline backup or downloaded. Download size depends on your model selection.%n%nContinue?
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "webview2.json"; DestDir: "{app}\runtime\webview2"; Flags: ignoreversion
Source: "..\runtime\webview2\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{app}\runtime\webview2"; Flags: ignoreversion
#ifdef FullBuild
Source: "..\runtime\webview2\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; DestDir: "{app}\runtime\webview2"; Flags: ignoreversion
#endif
#ifdef FullBuild
Source: "..\build\full-payload-{#MyAppVersion}\python\*"; DestDir: "{app}\runtime\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\full-payload-{#MyAppVersion}\packages\*"; DestDir: "{app}\runtime\python-packages"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\full-payload-{#MyAppVersion}\llama\*"; DestDir: "{app}\runtime\llama"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\full-payload-{#MyAppVersion}\manifest.json"; DestDir: "{app}\runtime"; DestName: "full-manifest.json"; Flags: ignoreversion
#endif
; Main application (PyInstaller: executable and _internal)
Source: "..\dist\Marvin\Marvin.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\Marvin\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef FullBuild
Source: "..\build\full-payload-{#MyAppVersion}\crt\*.dll"; DestDir: "{app}\_internal"; Flags: ignoreversion
#endif
; Supporting source (harness core, scripts and configuration)
Source: "..\qwen_app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\webapp.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\tui.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\run_app.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\run_cli.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements-windows-py312.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ui_dist\*"; DestDir: "{app}\ui_dist"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "version.txt"; DestDir: "{app}"; DestName: "version.txt"; Flags: ignoreversion
Source: "..\config.yaml"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\AGENTS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\output\pdf\Marvin-Manual-EN.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\output\pdf\Marvin-Manual-CS.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\harness\*.py"; DestDir: "{app}\harness"; Flags: ignoreversion recursesubdirs
Source: "..\harness\locales\*.json"; DestDir: "{app}\harness\locales"; Flags: ignoreversion
Source: "..\harness\tools\*.py"; DestDir: "{app}\harness\tools"; Flags: ignoreversion
Source: "..\launcher\*.py"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "..\scripts\*.py"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\tests\*.py"; DestDir: "{app}\tests"; Flags: ignoreversion
Source: "..\memory\*.md"; DestDir: "{app}\memory"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs
Source: "..\skills\*.md"; DestDir: "{app}\skills"; Flags: ignoreversion recursesubdirs createallsubdirs
; Setup script (environment and models), run after installation
Source: "run_setup.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "run_setup_from_backup.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{#MyAppName} (CLI)"; Filename: "{app}\run_cli.bat"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\{cm:SetupEnvMenu}"; Filename: "{app}\run_setup.bat"; WorkingDir: "{app}"
Name: "{group}\{cm:BackupSetupMenu}"; Filename: "{app}\run_setup_from_backup.bat"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
#ifdef FullBuild
Filename: "{app}\runtime\python\python.exe"; Parameters: "-I ""{app}\scripts\bootstrap_full.py"""; WorkingDir: "{app}"; StatusMsg: "Preparing private Python environment..."; Flags: runhidden waituntilterminated
#endif
; Prepare the environment, dependencies, llama.cpp and selected models
; Show console progress after installation; selected by default
Filename: "{app}\run_setup.bat"; Description: "{cm:RunSetupDesc}"; Flags: postinstall skipifsilent shellexec runasoriginaluser; WorkingDir: "{app}"

[Code]
var
  ModelPage: TWizardPage;
  ModelList: TNewCheckListBox;
  // Populated in FillModelTable because Pascal Script does not support typed constants;
  // mirrors config.yaml (min_vram_gb is the smallest model profile)
  ModelKeys: array[0..6] of String;
  ModelNames: array[0..6] of String;
  ModelMinVram: array[0..6] of Double;
  ModelRowKeys: array[0..6] of String;
  ModelFiles: array[0..6] of String;

procedure FillModelTable;
begin
  ModelKeys[0] := 'q3';
  ModelKeys[1] := 'q4';
  ModelKeys[2] := 'q5';
  ModelKeys[3] := 'ornith_q5';
  ModelKeys[4] := 'nemotron_q4';
  ModelKeys[5] := 'nemotron_q5';
  ModelKeys[6] := 'flash_next_q3';
  ModelNames[0] := 'Qwen3.8-27B IQ3_S  (12.0 GB download)  -  16/24 GB GPUs, Q8 64k/48k on 16 GB';
  ModelNames[1] := 'Qwen3.8-27B Q4_K_M  (16.5 GB download)  -  24 GB+ GPUs';
  ModelNames[2] := 'Qwen3.8-27B Q5_K_M  (19.8 GB download)  -  24 GB+ GPUs';
  ModelNames[3] := 'Ornith 1.5 35B-A3B Q5 Abliterated  (23.0 GB download)  -  32 GB GPUs';
  ModelNames[4] := 'Nemotron 3.5 Lightning 30B-A3B Q4_K_XL  (25.5 GB download)  -  24 GB+ GPUs';
  ModelNames[5] := 'Nemotron 3.5 Lightning 30B-A3B Q5_K_XL  (30.4 GB download)  -  24 GB+ GPUs, CPU experts on 24 GB';
  ModelNames[6] := 'Qwen3.8-Flash-Next Q3  (90.9 GB download)  -  GPU + system RAM, automatic configuration';
  ModelMinVram[0] := 15.0;
  ModelMinVram[1] := 23.0;
  ModelMinVram[2] := 23.0;
  ModelMinVram[3] := 31.0;
  ModelMinVram[4] := 23.0;
  ModelMinVram[5] := 23.0;
  ModelMinVram[6] := 15.0;
  ModelFiles[0] := 'Qwen3.8-27B-UD-IQ3_S.gguf';
  ModelFiles[1] := 'Qwen3.8-27B-UD-Q4_K_M.gguf';
  ModelFiles[2] := 'Qwen3.8-27B-UD-Q5_K_M.gguf';
  ModelFiles[3] := 'Ornith-1.5-35B-Abliterated-Dynamic-Q5_K_M.gguf';
  ModelFiles[4] := 'NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-Q4_K_XL.gguf';
  ModelFiles[5] := 'NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-Q5_K_XL.gguf';
  ModelFiles[6] := 'Qwen3.8-Flash-Next\.marvin-verified.json';
end;

function DetectVRAM: Double;
var
  ResultCode: Integer;
  TmpFile: String;
  Lines: TArrayOfString;
begin
  Result := 0;
  TmpFile := ExpandConstant('{tmp}\qwen-vram.txt');
  Exec(ExpandConstant('{cmd}'),
       Format('/c nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits > "%s"', [TmpFile]),
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if (ResultCode = 0) and LoadStringsFromFile(TmpFile, Lines) and (GetArrayLength(Lines) > 0) then
    Result := StrToIntDef(Trim(Lines[0]), 0) / 1024.0;
end;

procedure RefreshModelChecks(AppDir: String);
var
  I: Integer;
  Vram: Double;
  Fits, Checked, HasAnyModel: Boolean;
  ModelsDir: String;
begin
  Vram := DetectVRAM;
  ModelsDir := AppDir + '\runtime\models';
  HasAnyModel := False;
  for I := 0 to 6 do
    if FileExists(ModelsDir + '\' + ModelFiles[I]) then HasAnyModel := True;
  // Recreate TNewCheckListBox on refresh because individual items cannot be removed
  if ModelList <> nil then
    ModelList.Free;
  ModelList := TNewCheckListBox.Create(ModelPage.Surface);
  ModelList.SetBounds(ScaleX(0), ScaleY(0), ModelPage.SurfaceWidth, ScaleY(150));
  ModelList.Parent := ModelPage.Surface;
  ModelList.ShowLines := False;
  for I := 0 to 6 do
  begin
    Fits := (Vram <= 0) or (ModelMinVram[I] <= Vram);
    // Fresh installs select all compatible models; upgrades select only models
    // already downloaded. The user selects any additional models explicitly.
    if HasAnyModel then
      Checked := Fits and FileExists(ModelsDir + '\' + ModelFiles[I])
    else
      Checked := Fits and (I <> 6);
    if not ((I = 0) and (Vram >= 31.0)) then
    begin
      ModelRowKeys[ModelList.Items.Count] := ModelKeys[I];
      ModelList.AddCheckBox(ModelNames[I], '', 0, Checked, Fits, False, False, TObject(I));
    end;
  end;
end;

procedure InitializeWizard;
var
  Vram: Double;
  Subtitle: String;
begin
  FillModelTable;
  Vram := DetectVRAM;
  if Vram > 0 then
    Subtitle := Format('Detected GPU: %.1f GB VRAM. Only models that fit are selectable; uncheck what you do not want to download.', [Vram])
  else
    Subtitle := 'GPU VRAM could not be detected - all models are offered. Uncheck what you do not want to download.';
  ModelPage := CreateCustomPage(wpSelectDir, 'Models to download',
    'Choose which models to download on first launch. ' + Subtitle);
  // {app} is not initialized yet; ExpandConstant would raise an internal error
  // Use fresh-install behavior initially. NextButtonClick(wpSelectDir)
  // detects existing models using the final installation path.
  RefreshModelChecks('');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  I: Integer;
  AnyChecked: Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
    RefreshModelChecks(WizardDirValue);  // the installation directory is final at this point
  if CurPageID = ModelPage.ID then
  begin
    AnyChecked := False;
    for I := 0 to ModelList.Items.Count - 1 do
      if ModelList.Checked[I] then AnyChecked := True;
    if not AnyChecked then
    begin
      MsgBox('Keep at least one model checked - the app cannot run without any model.',
             mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function FindOfflineBackup: String;
var
  SourceDir: String;
begin
  SourceDir := ExpandConstant('{src}');
  Result := '';
  if FileExists(SourceDir + '\manifest.json') then
    Result := SourceDir
  else if FileExists(SourceDir + '\QwenHarness-Offline-Backup\manifest.json') then
    Result := SourceDir + '\QwenHarness-Offline-Backup'
  else if FileExists(SourceDir + '\Marvin-Offline-Backup\manifest.json') then
    Result := SourceDir + '\Marvin-Offline-Backup';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  I: Integer;
  DesktopResult: Integer;
  Selection: String;
  OldGroup: String;
  BackupDir: String;
begin
  if CurStep = ssInstall then
  begin
    // Remove shortcuts using the former product name
    OldGroup := ExpandConstant('{autoprograms}') + '\Qwen3.8-27B Harness';
    if DirExists(OldGroup) then
      DelTree(OldGroup, True, True, True);
    DeleteFile(ExpandConstant('{autodesktop}') + '\Qwen3.8-27B Harness.lnk');
  end;
  if CurStep = ssPostInstall then
  begin
    CreateDir(ExpandConstant('{app}\runtime'));
    // Save the installer language for the application to use
    SaveStringToFile(ExpandConstant('{app}\runtime\ui-language.txt'), ActiveLanguage, False);
    BackupDir := FindOfflineBackup;
    if BackupDir <> '' then
    begin
      SaveStringToFile(ExpandConstant('{app}\runtime\offline-backup-path.txt'), BackupDir, False);
      SaveStringToFile(ExpandConstant('{app}\runtime\offline-setup-once.txt'), '1', False);
    end;
    // The frozen launcher shares detection/repair with normal startup. It needs
    // neither system Python nor a prepared venv, and verifies the runtime itself.
    WizardForm.StatusLabel.Caption := CustomMessage('PrepareDesktop');
    if not Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--prepare-webview2',
                ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, DesktopResult) then
      RaiseException(CustomMessage('DesktopSetupFailed'));
    if DesktopResult <> 0 then
      RaiseException(CustomMessage('DesktopSetupFailed'));
    // Save the comma-separated model selection for run_setup.bat to pass to the downloader
    Selection := '';
    if Assigned(ModelList) then
      for I := 0 to ModelList.Items.Count - 1 do
        if ModelList.Checked[I] and ModelList.ItemEnabled[I] then
        begin
          if Selection <> '' then Selection := Selection + ',';
          Selection := Selection + ModelRowKeys[I];
        end;
    if Selection <> '' then
      SaveStringToFile(ExpandConstant('{app}\runtime\model-selection.txt'), Selection, False);
  end;
end;
