; ============================================================
;  Marvin - installer (Inno Setup 6)
;  Build:  installer\build_installer.bat  →  dist\Marvin-Setup-<verze>.exe
;
;  Language: the wizard offers English (default) and Czech; the
;  selected language is written to {app}\runtime\ui-language.txt
;  and the app starts in it (English when nothing is selected).
; ============================================================

; Verzi lze předefinovat z příkazové řádky: ISCC /DMyAppVersion=x.y.z
; (používá installer\release.bat s verzí z installer\version.txt)
#ifndef MyAppVersion
#define MyAppVersion "1.8.1"
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
; bez admin prav - instalace do uzivatelskeho profilu
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
; vzdy zobraz vyber jazyka (anglictina je prvni = vychozi)
ShowLanguageDialog=yes

; po prejmenovani produktu odstranit stare exe z predchozi instalace
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
en.SetupEnvMenu=Set up environment and models
cze.SetupEnvMenu=Instalace prostředí a modelů
en.BackupSetupMenu=Set up from offline backup
cze.BackupSetupMenu=Instalace z offline zálohy
#ifdef FullBuild
en.RunSetupDesc=Download selected models (Python, packages and llama.cpp are included)
cze.RunSetupDesc=Stahnout vybrane modely (Python, balicky a llama.cpp jsou pribalene)
#else
en.RunSetupDesc=Set up the environment and download models (requires separately installed 64-bit Python 3.12)
cze.RunSetupDesc=Nainstalovat prostředí a modely (vyžaduje samostatně nainstalovaný 64bitový Python 3.12)
#endif

[Messages]
#ifdef FullBuild
en.WelcomeLabel2=Marvin Full includes a private Python 3.12 runtime, Python packages and llama.cpp/CUDA libraries.%n%nNo system Python or PATH changes are required. NVIDIA drivers remain your responsibility. Models are downloaded separately.%n%nContinue?
cze.WelcomeLabel2=Marvin Full obsahuje vlastni Python 3.12, Python balicky a llama.cpp/CUDA knihovny.%n%nNepotrebuje systemovy Python a nemeni PATH. Ovladac NVIDIA instaluje uzivatel. Modely se stahuji samostatne.%n%nPokracovat?
#else
en.WelcomeLabel2=This wizard will install [name/ver], a local AI application.%n%nREQUIRED: Install 64-bit Python 3.12 separately and enable "Add Python to PATH" before continuing. Python is not bundled.%n%nAfter installation, the environment and selected models will be prepared from an offline backup or downloaded. Download size depends on your model selection.%n%nContinue?
cze.WelcomeLabel2=Tento pruvodce nainstaluje [name/ver] - lokalni AI aplikaci.%n%nVYZADOVANO: Pred pokracovanim samostatne nainstalujte 64bitovy Python 3.12 a zapnete "Add Python to PATH". Python neni soucasti instalatoru.%n%nPo instalaci se prostredi a vybrane modely pripravi z offline zalohy nebo stahnou. Objem zavisi na vyberu modelu.%n%nPOKRACOVAT?
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
#ifdef FullBuild
Source: "..\build\full-payload-{#MyAppVersion}\python\*"; DestDir: "{app}\runtime\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\full-payload-{#MyAppVersion}\packages\*"; DestDir: "{app}\runtime\python-packages"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\full-payload-{#MyAppVersion}\llama\*"; DestDir: "{app}\runtime\llama"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\full-payload-{#MyAppVersion}\manifest.json"; DestDir: "{app}\runtime"; DestName: "full-manifest.json"; Flags: ignoreversion
#endif
; hlavní aplikace (PyInstaller: exe + _internal)
Source: "..\dist\Marvin\Marvin.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\Marvin\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef FullBuild
Source: "..\build\full-payload-{#MyAppVersion}\crt\*.dll"; DestDir: "{app}\_internal"; Flags: ignoreversion
#endif
; podpůrné zdroje (harness jádro, skripty, config)
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
Source: "..\harness\tools\*.py"; DestDir: "{app}\harness\tools"; Flags: ignoreversion
Source: "..\launcher\*.py"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "..\scripts\*.py"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\tests\*.py"; DestDir: "{app}\tests"; Flags: ignoreversion
Source: "..\memory\*.md"; DestDir: "{app}\memory"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs
Source: "..\skills\*.md"; DestDir: "{app}\skills"; Flags: ignoreversion recursesubdirs createallsubdirs
; setup skript (venv + modely) - spouští se po instalaci
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
; HLAVNI KROK: vytvori venv, stahne zavislosti, llama.cpp i modely (~59 GiB)
; s prubehem v konzoli - hned po dokonceni instalatoru (default zaskrtnuto)
Filename: "{app}\run_setup.bat"; Description: "{cm:RunSetupDesc}"; Flags: postinstall skipifsilent shellexec runasoriginaluser; WorkingDir: "{app}"

[Code]
var
  ModelPage: TWizardPage;
  ModelList: TNewCheckListBox;
  // naplni se v FillModelTable (Pascal Script neumi typovane konstanty);
  // zrcadli config.yaml (min_vram_gb = nejnizsi profil modelu)
  ModelKeys: array[0..6] of String;
  ModelNames: array[0..6] of String;
  ModelMinVram: array[0..6] of Double;
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
  ModelNames[0] := 'Qwen3.8-27B IQ3_S  (12.0 GB download)  -  16 GB GPUs (borderline)';
  ModelNames[1] := 'Qwen3.8-27B Q4_K_M  (16.5 GB download)  -  24 GB+ GPUs';
  ModelNames[2] := 'Qwen3.8-27B Q5_K_M  (19.8 GB download)  -  24 GB+ GPUs';
  ModelNames[3] := 'Ornith 1.5 35B-A3B Q5 Abliterated  (23.0 GB download)  -  32 GB GPUs';
  ModelNames[4] := 'Nemotron 3.5 Lightning 30B-A3B Q4_K_XL  (25.5 GB download)  -  24 GB+ GPUs';
  ModelNames[5] := 'Nemotron 3.5 Lightning 30B-A3B Q5_K_XL  (30.4 GB download)  -  26 GB+ GPUs';
  ModelNames[6] := 'Qwen3.8-Flash-Next Q3  (90.9 GB download)  -  GPU + system RAM, automatic configuration';
  ModelMinVram[0] := 15.0;
  ModelMinVram[1] := 23.0;
  ModelMinVram[2] := 24.0;
  ModelMinVram[3] := 30.0;
  ModelMinVram[4] := 24.0;
  ModelMinVram[5] := 26.0;
  ModelMinVram[6] := 12.0;
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
  // TNewCheckListBox neumi mazat polozky - pri refreshi ho vytvorime znovu
  if ModelList <> nil then
    ModelList.Free;
  ModelList := TNewCheckListBox.Create(ModelPage.Surface);
  ModelList.SetBounds(ScaleX(0), ScaleY(0), ModelPage.SurfaceWidth, ScaleY(150));
  ModelList.Parent := ModelPage.Surface;
  ModelList.ShowLines := False;
  for I := 0 to 6 do
  begin
    Fits := (Vram <= 0) or (ModelMinVram[I] <= Vram);
    // cista instalace: zaskrtni vse, co se vejde; upgrade: zaskrtni jen jiz
    // stazene - nove modely se automaticky nestahuji, uzivatel je docita sam
    if HasAnyModel then
      Checked := Fits and FileExists(ModelsDir + '\' + ModelFiles[I])
    else
      Checked := Fits and (I <> 6);
    ModelList.AddCheckBox(ModelNames[I], '', 0, Checked, Fits, False, False, TObject(I));
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
  // {app} jeste neni inicializovane (ExpandConstant by hodil internal error)
  // - prvotni stav = chovani ciste instalace; skutecnou detekci existujicich
  // modelu provede NextButtonClick(wpSelectDir) s finalni cestou
  RefreshModelChecks('');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  I: Integer;
  AnyChecked: Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
    RefreshModelChecks(WizardDirValue);  // instalacni adresar je finalni az tady
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
  Selection: String;
  OldGroup: String;
  BackupDir: String;
begin
  if CurStep = ssInstall then
  begin
    // rebrand: odstranit zastupce ze stareho nazvu produktu
    OldGroup := ExpandConstant('{autoprograms}') + '\Qwen3.8-27B Harness';
    if DirExists(OldGroup) then
      DelTree(OldGroup, True, True, True);
    DeleteFile(ExpandConstant('{autodesktop}') + '\Qwen3.8-27B Harness.lnk');
  end;
  if CurStep = ssPostInstall then
  begin
    CreateDir(ExpandConstant('{app}\runtime'));
    // uloz vybrany jazyk instalatoru -> aplikace se podle nej nastavi
    SaveStringToFile(ExpandConstant('{app}\runtime\ui-language.txt'), ActiveLanguage, False);
    BackupDir := FindOfflineBackup;
    if BackupDir <> '' then
    begin
      SaveStringToFile(ExpandConstant('{app}\runtime\offline-backup-path.txt'), BackupDir, False);
      SaveStringToFile(ExpandConstant('{app}\runtime\offline-setup-once.txt'), '1', False);
    end;
    // uloz vyber modelu z wizardu (comma list; run_setup.bat ho preda downloadu)
    Selection := '';
    if Assigned(ModelList) then
      for I := 0 to ModelList.Items.Count - 1 do
        if ModelList.Checked[I] and ModelList.ItemEnabled[I] then
        begin
          if Selection <> '' then Selection := Selection + ',';
          Selection := Selection + ModelKeys[I];
        end;
    if Selection <> '' then
      SaveStringToFile(ExpandConstant('{app}\runtime\model-selection.txt'), Selection, False);
  end;
end;
