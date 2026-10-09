; PolyPDF Windows 설치 프로그램 (Inno Setup 6) — 260618-30
;   빌드: GitHub Actions(release.yml) 또는  installer\build_installer.ps1 (로컬, ISCC 필요)
;   버전은 ISCC /DMyAppVersion=<x.y.z> 로 주입(없으면 0.0.0).
;   261008-27(다국어 SOT §10): 언어 목록·마법사 문구·사용 안내는 `languages.iss`(자동 생성 —
;     `python scripts\i18n.py inno`, build_ci.bat 가 부른다). 이 파일에는 한국어·영어 문구를 직접 쓰지 않는다.
;   명령줄: /APPLANG=<코드>  — PolyPDF 언어 지정(첫 설치·업그레이드 모두, 언어 페이지 생략).
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
; dist 산출물 위치(.iss 기준 상대) — CI/로컬 모두 ..\dist\PolyPDF
#ifndef DistDir
  #define DistDir "..\dist\PolyPDF"
#endif
#define MyAppName "PolyPDF"
#define MyAppPublisher "kdjeong777-ops"
#define MyAppURL "https://github.com/kdjeong777-ops/PolyPDF"
#define MyAppExe "PolyPDF.exe"
#define MyProgId "PolyPDF.pdf"

[Setup]
AppId={{8E7B5A30-6E2C-4E2B-9C1A-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\
OutputBaseFilename=PolyPDF-Setup-v{#MyAppVersion}
SetupIconFile=..\resources\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
; 64비트 Windows 의 진짜 Program Files 에 설치
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Program Files 쓰기 → 관리자 권한 필요
PrivilegesRequired=admin
WizardStyle=modern
ChangesAssociations=yes
; 261008-27: Inno 표준 언어 창은 쓰지 않는다 — 마법사 언어는 Windows 화면 언어로 고르고(업그레이드는 이전 마법사 언어),
;   PolyPDF 언어는 따로 아래 [Code] 의 언어 페이지에서 고른다(다국어 SOT §10.1). 마침 화면 안내는 [Languages] 의 InfoAfterFile.
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage
UsePreviousLanguage=yes

; [Languages]·[CustomMessages]·사용 안내 [Files]/[Icons]·#define AppLang* — 자동 생성
#include "languages.iss"

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:AdditionalTasks}"
; PDF 기본 앱 — Windows 10/11 은 보안상 설치 프로그램이 강제 지정 불가.
;   체크 시: 연결 등록(아래 [Registry]) + 설치 후 'Windows 기본 앱' 설정을 열어 사용자가 확정.
Name: "pdfdefault"; Description: "{cm:PdfDefault}"; GroupDescription: "{cm:FileAssoc}"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\{cm:UninstallIcon}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; ── 261008-27: PolyPDF 언어 — 앱이 처음 켜질 때 이 값으로 초기 설정한다(다국어 SOT §4·§10.1). 제거 때 지운다 ──
Root: HKLM; Subkey: "Software\{#MyAppName}"; ValueType: string; ValueName: "InstallLanguage"; ValueData: "{code:GetAppLang}"; Flags: uninsdeletevalue
; ── ProgID 등록: '연결 프로그램'·'기본 앱' 후보로 PolyPDF 노출(기본값 강제 아님) ──
Root: HKLM; Subkey: "Software\Classes\{#MyProgId}"; ValueType: string; ValueName: ""; ValueData: "{cm:ProgIdDesc}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\{#MyProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExe},0"
Root: HKLM; Subkey: "Software\Classes\{#MyProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" ""%1"""
; .pdf 의 '연결 가능 목록'에 추가('연결 프로그램 → PolyPDF' 가능)
Root: HKLM; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#MyProgId}"; ValueData: ""; Flags: uninsdeletevalue
; ── 기본 앱(설정 → 기본 앱)에 애플리케이션 등록: Capabilities ──
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "{cm:AppDesc}"
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#MyProgId}"
Root: HKLM; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "Software\{#MyAppName}\Capabilities"; Flags: uninsdeletevalue

[Run]
; 261009-21: 아이콘 캐시 새로 고침 — 업그레이드 뒤 바로가기 아이콘이 흰색으로 남았다(사용자 보고).
;   설치한 사용자 권한으로·창 없이·기다리지 않음. 없으면(옛 Windows) 건너뜀.
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runasoriginaluser runhidden nowait skipifdoesntexist
; 설치 직후 실행(선택)
Filename: "{app}\{#MyAppExe}"; Description: "{cm:RunApp}"; Flags: nowait postinstall skipifsilent
; PDF 기본 앱 체크 시 — Windows '기본 앱' 설정 열기(사용자가 .pdf → PolyPDF 선택)
Filename: "ms-settings:defaultapps"; Description: "{cm:OpenDefaultApps}"; Flags: shellexec postinstall skipifsilent; Tasks: pdfdefault

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

; ─────────────────────────────────────────────────────────────────────────
; 260621-51: 재설치 시 기존 설치 감지 → 버전 비교 표시 → 기존 제거 → 설치.
;   (Inno 는 같은 AppId 면 덮어쓰기만 하므로, 명시적 '비교·제거 후 설치' 흐름을 추가.)
; 261008-27(다국어 SOT §10): PolyPDF 언어 — 첫 설치는 언어 페이지, 업그레이드는 기존 언어(§10.2 순서),
;   제거 프로그램이 없으면 제거 단계를 건너뛰고 옛 _internal 을 지운 뒤 덮어 설치(§10.3).
; ─────────────────────────────────────────────────────────────────────────
[Code]
const
  UNINST_SUB = '\Microsoft\Windows\CurrentVersion\Uninstall\{8E7B5A30-6E2C-4E2B-9C1A-1A2B3C4D5E6F}_is1';
  APP_LANG_CODES = '{#AppLangCodes}';
  APP_LANG_NAMES = '{#AppLangNames}';
  APP_LANG_WIZARD = '{#AppLangWizard}';

var
  gPrevVer: String;
  gPrevUninst: String;
  gAppLang: String;        { 정한 PolyPDF 언어 코드 }
  gLangFixed: Boolean;     { 업그레이드·/APPLANG — 언어 페이지를 보이지 않는다 }
  gSettingsLang: String;   { 사용자 설정 파일의 언어(있으면 — 첫 설치 페이지의 기본값으로도) }
  gLangPage: TInputOptionWizardPage;

{ ── 쉼표 목록 ── }
function ListItem(list: String; idx: Integer): String;
var
  i, p: Integer;
begin
  Result := '';
  for i := 0 to idx do
  begin
    p := Pos(',', list);
    if p > 0 then
    begin
      Result := Copy(list, 1, p - 1);
      Delete(list, 1, p);
    end
    else
    begin
      Result := list;
      list := '';
    end;
  end;
end;

function ListCount(const list: String): Integer;
var
  i: Integer;
begin
  Result := 1;
  for i := 1 to Length(list) do
    if list[i] = ',' then Result := Result + 1;
end;

function ListIndex(const list, value: String): Integer;
var
  i: Integer;
begin
  Result := -1;
  for i := 0 to ListCount(list) - 1 do
    if CompareText(ListItem(list, i), value) = 0 then
    begin
      Result := i;
      Exit;
    end;
end;

{ 언어 코드 다듬기: 'EN-us' → 'en_us' 꼴은 그대로 두고 소문자·'-'→'_' 만. }
function NormLang(s: String): String;
begin
  s := Lowercase(Trim(s));
  StringChangeEx(s, '-', '_', True);
  Result := s;
end;

{ 사용 안내·시작 메뉴는 이 함수로 고른다. 이번 설치본에 없는 언어(외부 팩)는 영어 안내. }
function IsAppLang(const code: String): Boolean;
begin
  if ListIndex(APP_LANG_CODES, gAppLang) >= 0 then
    Result := CompareText(gAppLang, code) = 0
  else
    Result := CompareText(code, 'en') = 0;
end;

function GetAppLang(Param: String): String;
begin
  Result := gAppLang;
end;

{ 이전 설치의 Uninstall 레지스트리 값(여러 뷰 시도). }
function ReadUninstVal(const ValName: String): String;
var
  v: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, 'Software' + UNINST_SUB, ValName, v) then
    Result := v
  else if RegQueryStringValue(HKLM, 'Software\WOW6432Node' + UNINST_SUB, ValName, v) then
    Result := v
  else if RegQueryStringValue(HKCU, 'Software' + UNINST_SUB, ValName, v) then
    Result := v;
end;

{ 사용자 설정 %APPDATA%\LocalTools\PolyPDF\settings.json 의 "language" 값.
  파일이 없으면 Exists=False. 있는데 값이 없으면 '' (이 기능 전의 앱 — 한국어). }
function ReadSettingsLanguage(var Exists: Boolean): String;
var
  path: String;
  raw: AnsiString;
  s: String;
  p, q: Integer;
begin
  Result := '';
  path := ExpandConstant('{userappdata}\LocalTools\PolyPDF\settings.json');
  Exists := FileExists(path);
  if not Exists then Exit;
  if not LoadStringFromFile(path, raw) then Exit;
  s := String(raw);
  p := Pos('"language"', s);
  if p = 0 then Exit;
  s := Copy(s, p + 10, 64);
  p := Pos('"', s);
  if p = 0 then Exit;
  Delete(s, 1, p);
  q := Pos('"', s);
  if q = 0 then Exit;
  Result := NormLang(Copy(s, 1, q - 1));
end;

{ 다국어 SOT §10.2 — 업그레이드 때 기존 언어(기존 제거 **전에** 읽는다). }
function UpgradeLanguage(): String;
var
  exists: Boolean;
  v: String;
  i: Integer;
begin
  Result := gSettingsLang;                                   { 1) 앱에서 바꿨을 수 있다 — 지금 쓰는 언어 }
  if Result <> '' then Exit;
  ReadSettingsLanguage(exists);
  if exists then begin Result := 'ko'; Exit; end;           { 2) 설정은 있는데 language 없음 = 이 기능 전의 앱 }
  if RegQueryStringValue(HKLM, 'Software\{#MyAppName}', 'InstallLanguage', v) and (v <> '') then
  begin
    Result := NormLang(v); Exit;                             { 3) 설치만 하고 앱을 안 켠 경우 }
  end;
  v := ReadUninstVal('Inno Setup: Language');                { 4) 옛 설치본의 마법사 언어 }
  i := ListIndex(APP_LANG_WIZARD, v);
  if i >= 0 then Result := ListItem(APP_LANG_CODES, i) else Result := 'ko';
end;

function VerBase(v: String): String;
var
  p: Integer;
begin
  if (Length(v) > 0) and ((v[1] = 'v') or (v[1] = 'V')) then Delete(v, 1, 1);
  p := Pos('-', v);
  if p > 0 then Result := Copy(v, 1, p - 1) else Result := v;
end;

function VerPreStr(const v: String): String;
var
  p: Integer;
begin
  p := Pos('-', v);
  if p > 0 then Result := Copy(v, p + 1, Length(v)) else Result := '';
end;

{ v 의 idx(0~2)번째 점-구분 숫자. }
function VerNum(v: String; idx: Integer): Integer;
var
  s, tok: String;
  i, p: Integer;
begin
  s := VerBase(v);
  tok := '';
  for i := 0 to idx do
  begin
    p := Pos('.', s);
    if p > 0 then
    begin
      tok := Copy(s, 1, p - 1);
      Delete(s, 1, p);
    end
    else
    begin
      tok := s;
      s := '';
    end;
  end;
  Result := StrToIntDef(tok, 0);
end;

{ a 와 b 비교: a>b → 1, a=b → 0, a<b → -1. 프리릴리즈(-beta 등)는 같은 X.Y.Z 정식보다 작음. }
function CompareVer(const a, b: String): Integer;
var
  i, na, nb, c: Integer;
  pa, pb: String;
begin
  Result := 0;
  for i := 0 to 2 do
  begin
    na := VerNum(a, i);
    nb := VerNum(b, i);
    if na > nb then begin Result := 1; Exit; end;
    if na < nb then begin Result := -1; Exit; end;
  end;
  pa := VerPreStr(a);
  pb := VerPreStr(b);
  if (pa = '') and (pb = '') then Exit;          { 둘 다 정식, 동일 }
  if (pa = '') and (pb <> '') then begin Result := 1; Exit; end;   { 정식 > 프리 }
  if (pa <> '') and (pb = '') then begin Result := -1; Exit; end;  { 프리 < 정식 }
  c := CompareText(pa, pb);                       { 둘 다 프리: 문자열 비교(근사) }
  if c > 0 then Result := 1 else if c < 0 then Result := -1 else Result := 0;
end;

{ 설치 시작 전: 기존 설치 감지 + 버전 비교 안내 + PolyPDF 언어 결정. }
function InitializeSetup(): Boolean;
var
  cmp: Integer;
  msg, forced: String;
  exists: Boolean;
begin
  Result := True;
  gPrevVer := ReadUninstVal('DisplayVersion');
  gPrevUninst := ReadUninstVal('QuietUninstallString');
  if gPrevUninst = '' then
    gPrevUninst := ReadUninstVal('UninstallString');

  gSettingsLang := ReadSettingsLanguage(exists);
  forced := NormLang(ExpandConstant('{param:APPLANG|}'));    { 0) 명시 지정 }
  if (forced <> '') and (ListIndex(APP_LANG_CODES, forced) >= 0) then
  begin
    gAppLang := forced;
    gLangFixed := True;
  end
  else if gPrevVer <> '' then
  begin
    gAppLang := UpgradeLanguage();                           { 업그레이드 — 페이지 없이 기존 언어 그대로 }
    gLangFixed := True;
  end
  else
  begin
    gAppLang := '';                                          { 첫 설치 — 언어 페이지에서 고른다 }
    gLangFixed := False;
  end;

  if gPrevVer <> '' then
  begin
    cmp := CompareVer('{#MyAppVersion}', gPrevVer);
    msg := CustomMessage('AlreadyInstalled') + #13#10#13#10
         + FmtMessage(CustomMessage('OldVersion'), [gPrevVer]) + #13#10
         + FmtMessage(CustomMessage('NewVersion'), ['{#MyAppVersion}']) + #13#10#13#10;
    if cmp > 0 then
      msg := msg + CustomMessage('IsUpgrade')
    else if cmp = 0 then
      msg := msg + CustomMessage('IsSame')
    else
      msg := msg + CustomMessage('IsDowngrade');
    msg := msg + #13#10#13#10 + CustomMessage('AskReplace');
    if (not WizardSilent()) and (MsgBox(msg, mbConfirmation, MB_YESNO) = IDNO) then
      Result := False;
  end;
end;

{ 첫 설치의 'PolyPDF 언어' 페이지 — 내장 팩 목록. 기본값: 설정 파일의 언어 → 마법사 언어의 팩 → en. }
procedure InitializeWizard();
var
  i, def: Integer;
begin
  gLangPage := CreateInputOptionPage(wpWelcome, CustomMessage('LangPageTitle'),
    CustomMessage('LangPageDesc'), CustomMessage('LangPageSub'), True, False);
  for i := 0 to ListCount(APP_LANG_NAMES) - 1 do
    gLangPage.Add(ListItem(APP_LANG_NAMES, i));
  def := ListIndex(APP_LANG_CODES, gSettingsLang);
  if def < 0 then def := ListIndex(APP_LANG_WIZARD, ActiveLanguage());
  if def < 0 then def := ListIndex(APP_LANG_CODES, 'en');
  if def < 0 then def := 0;
  gLangPage.SelectedValueIndex := def;
  if gAppLang = '' then
    gAppLang := ListItem(APP_LANG_CODES, def);               { 조용한 설치(/SILENT)는 페이지 없이 이 값 }
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (gLangPage <> nil) and (PageID = gLangPage.ID) and gLangFixed;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (gLangPage <> nil) and (CurPageID = gLangPage.ID) and (not gLangFixed) then
    gAppLang := ListItem(APP_LANG_CODES, gLangPage.SelectedValueIndex);
end;

{ 파일 복사 직전: 실행 중인 앱 종료 → 기존 버전 제거(대기) → 설치 진행. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  rc, i: Integer;
  uninstExe, oldDir: String;
begin
  Result := '';
  if gPrevUninst = '' then Exit;

  { 1) 실행 중인 PolyPDF 종료(파일 잠금 방지) }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM PolyPDF.exe', '',
       SW_HIDE, ewWaitUntilTerminated, rc);
  Sleep(500);

  { 2) 기존 버전 제거 — QuietUninstallString 의 exe 경로만 추출해 silent 실행 }
  uninstExe := gPrevUninst;
  if (Length(uninstExe) > 0) and (uninstExe[1] = '"') then
  begin
    Delete(uninstExe, 1, 1);
    i := Pos('"', uninstExe);
    if i > 0 then uninstExe := Copy(uninstExe, 1, i - 1);
  end;

  { 261008-27(다국어 SOT §10.3): 제거 프로그램 파일이 없으면(옛 앱 안 업데이트의 정리가 지운 경우)
    제거 단계를 건너뛰고, 옛 .pyd/.dll 이 남지 않게 기존 _internal 만 지운 뒤 덮어 설치한다. }
  if not FileExists(uninstExe) then
  begin
    oldDir := ReadUninstVal('Inno Setup: App Path');
    if oldDir = '' then oldDir := ExtractFileDir(uninstExe);
    if (oldDir <> '') and DirExists(oldDir + '\_internal') then
      DelTree(oldDir + '\_internal', True, True, True);
    Exit;
  end;

  if not Exec(uninstExe, '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES', '',
              SW_HIDE, ewWaitUntilTerminated, rc) then
  begin
    Result := CustomMessage('UninstallFailed');
    Exit;
  end;

  { 3) 제거 완료 대기 — 언인스톨러는 임시 복사본으로 동작하므로 레지스트리 키가 사라질 때까지 폴링(최대 ~30초) }
  i := 0;
  while (i < 60) and (ReadUninstVal('UninstallString') <> '') do
  begin
    Sleep(500);
    i := i + 1;
  end;
  Sleep(500);
end;
