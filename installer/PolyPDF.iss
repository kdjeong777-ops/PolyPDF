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
