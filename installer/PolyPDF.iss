; PolyPDF Windows 설치 프로그램 (Inno Setup 6) — 260618-30
;   빌드: GitHub Actions(release.yml) 또는  installer\build_installer.ps1 (로컬, ISCC 필요)
;   버전은 ISCC /DMyAppVersion=<x.y.z> 로 주입(없으면 0.0.0).
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
; 설치 마침 화면 직전에 사용 안내(API 키 등) 표시
InfoAfterFile=guide_ko.txt

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"
; PDF 기본 앱 — Windows 10/11 은 보안상 설치 프로그램이 강제 지정 불가.
;   체크 시: 연결 등록(아래 [Registry]) + 설치 후 'Windows 기본 앱' 설정을 열어 사용자가 확정.
Name: "pdfdefault"; Description: "PolyPDF 를 PDF 기본 앱으로 설정 (설치 후 Windows 설정에서 한 번 선택 필요)"; GroupDescription: "파일 연결:"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "guide_ko.txt"; DestDir: "{app}"; DestName: "사용안내(API키).txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\사용 안내 (API 키)"; Filename: "{app}\사용안내(API키).txt"
Name: "{group}\{#MyAppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; ── ProgID 등록: '연결 프로그램'·'기본 앱' 후보로 PolyPDF 노출(기본값 강제 아님) ──
Root: HKLM; Subkey: "Software\Classes\{#MyProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF 문서 (PolyPDF)"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\{#MyProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExe},0"
Root: HKLM; Subkey: "Software\Classes\{#MyProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" ""%1"""
; .pdf 의 '연결 가능 목록'에 추가('연결 프로그램 → PolyPDF' 가능)
Root: HKLM; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#MyProgId}"; ValueData: ""; Flags: uninsdeletevalue
; ── 기본 앱(설정 → 기본 앱)에 애플리케이션 등록: Capabilities ──
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "PDF 뷰어·편집·책갈피·검색·단어장"
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#MyProgId}"
Root: HKLM; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "Software\{#MyAppName}\Capabilities"; Flags: uninsdeletevalue

[Run]
; 설치 직후 실행(선택)
Filename: "{app}\{#MyAppExe}"; Description: "PolyPDF 실행"; Flags: nowait postinstall skipifsilent
; PDF 기본 앱 체크 시 — Windows '기본 앱' 설정 열기(사용자가 .pdf → PolyPDF 선택)
Filename: "ms-settings:defaultapps"; Description: "Windows '기본 앱' 설정 열기 ( .pdf → PolyPDF 선택 )"; Flags: shellexec postinstall skipifsilent; Tasks: pdfdefault

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

; ─────────────────────────────────────────────────────────────────────────
; 260621-51: 재설치 시 기존 설치 감지 → 버전 비교 표시 → 기존 제거 → 설치.
;   (Inno 는 같은 AppId 면 덮어쓰기만 하므로, 명시적 '비교·제거 후 설치' 흐름을 추가.)
; ─────────────────────────────────────────────────────────────────────────
[Code]
const
  UNINST_SUB = '\Microsoft\Windows\CurrentVersion\Uninstall\{8E7B5A30-6E2C-4E2B-9C1A-1A2B3C4D5E6F}_is1';

var
  gPrevVer: String;
  gPrevUninst: String;

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

function VerBase(v: String): String;
var
  p: Integer;
begin
  if (Length(v) > 0) and ((v[1] = 'v') or (v[1] = 'V')) then Delete(v, 1, 1);
  p := Pos('-', v);
  if p > 0 then Result := Copy(v, 1, p - 1) else Result := v;
end;

function VerHasPre(const v: String): Boolean;
begin
  Result := Pos('-', v) > 0;
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

{ 설치 시작 전: 기존 설치 감지 + 버전 비교 안내. }
function InitializeSetup(): Boolean;
var
  cmp: Integer;
  msg: String;
begin
  Result := True;
  gPrevVer := ReadUninstVal('DisplayVersion');
  gPrevUninst := ReadUninstVal('QuietUninstallString');
  if gPrevUninst = '' then
    gPrevUninst := ReadUninstVal('UninstallString');

  if gPrevVer <> '' then
  begin
    cmp := CompareVer('{#MyAppVersion}', gPrevVer);
    msg := '이미 PolyPDF 가 설치되어 있습니다.' + #13#10#13#10
         + '기존 버전: ' + gPrevVer + #13#10
         + '새 버전:   ' + '{#MyAppVersion}' + #13#10#13#10;
    if cmp > 0 then
      msg := msg + '→ 업그레이드입니다.'
    else if cmp = 0 then
      msg := msg + '→ 동일한 버전을 다시 설치합니다.'
    else
      msg := msg + '→ 더 낮은 버전입니다(다운그레이드).';
    msg := msg + #13#10#13#10
         + '기존 버전을 제거한 뒤 새로 설치합니다. 계속하시겠습니까?';
    if MsgBox(msg, mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;

{ 파일 복사 직전: 실행 중인 앱 종료 → 기존 버전 제거(대기) → 설치 진행. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  rc, i: Integer;
  uninstExe: String;
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

  if not Exec(uninstExe, '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES', '',
              SW_HIDE, ewWaitUntilTerminated, rc) then
  begin
    Result := '기존 버전 제거를 실행하지 못했습니다.' + #13#10
            + '제어판에서 기존 PolyPDF 를 수동 제거한 뒤 다시 설치해 주세요.';
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
