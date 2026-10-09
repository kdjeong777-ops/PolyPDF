# -*- coding: utf-8 -*-
"""설치 프로그램(Inno Setup) 문구 원문 — 다국어 SOT §10.4 (261008-27).

`scripts/i18n.py extract` 가 `msgctxt "installer"` 로 뽑아 언어팩 `.po` 에 넣고,
`scripts/i18n.py inno` 가 이 표와 각 팩의 번역으로 `installer/languages.iss` 를 만든다.
실행되는 코드가 아니다 — 생성기는 이 파일을 AST 로 읽는다(키 → 원문).

- MESSAGES: 설치 **마법사 언어**를 따르는 문구 → `[CustomMessages]`(`{cm:키}`·`CustomMessage('키')`).
  줄바꿈은 `\\n` 으로 쓰면 생성기가 Inno 의 `%n` 으로 바꾼다. `%1`·`%2` 는 Inno 의 자리표시다.
- APP_LANG: **PolyPDF 언어**를 따르는 것(사용 안내 파일·시작 메뉴 이름) — 언어마다 `[Files]`·`[Icons]` 항목이 따로 생긴다.
"""
from viewer.i18n import trp

MESSAGES = {
    "DesktopIcon": trp("installer", "바탕화면에 바로가기 만들기"),
    "AdditionalTasks": trp("installer", "추가 작업:"),
    "PdfDefault": trp("installer", "PolyPDF 를 PDF 기본 앱으로 설정 (설치 후 Windows 설정에서 한 번 선택 필요)"),
    "FileAssoc": trp("installer", "파일 연결:"),
    "ProgIdDesc": trp("installer", "PDF 문서 (PolyPDF)"),
    "AppDesc": trp("installer", "PDF 뷰어·편집·책갈피·검색·단어장"),
    "RunApp": trp("installer", "PolyPDF 실행"),
    "OpenDefaultApps": trp("installer", "Windows '기본 앱' 설정 열기 ( .pdf → PolyPDF 선택 )"),
    "UninstallIcon": trp("installer", "PolyPDF 제거"),
    "AlreadyInstalled": trp("installer", "이미 PolyPDF 가 설치되어 있습니다."),
    "OldVersion": trp("installer", "기존 버전: %1"),
    "NewVersion": trp("installer", "새 버전:   %1"),
    "IsUpgrade": trp("installer", "→ 업그레이드입니다."),
    "IsSame": trp("installer", "→ 동일한 버전을 다시 설치합니다."),
    "IsDowngrade": trp("installer", "→ 더 낮은 버전입니다(다운그레이드)."),
    "AskReplace": trp("installer", "기존 버전을 제거한 뒤 새로 설치합니다. 계속하시겠습니까?"),
    "UninstallFailed": trp("installer", "기존 버전 제거를 실행하지 못했습니다.\n"
                                        "제어판에서 기존 PolyPDF 를 수동 제거한 뒤 다시 설치해 주세요."),
    "LangPageTitle": trp("installer", "PolyPDF 언어 / Language"),   # 한국어 마법사에서도 영어 사용자가 알아보게
    "LangPageDesc": trp("installer", "PolyPDF 화면에 쓸 언어를 고르세요."),
    "LangPageSub": trp("installer", "설치 마법사의 언어와 따로 고를 수 있습니다. 나중에 도구 → 환경설정 맨 위 '언어 / Language' 에서 바꿀 수 있습니다(다시 시작)."),
}

# WIZARD: Inno 표준 마법사 메시지(`Korean.isl`·`Default.isl`)를 덮어쓰는 것 → `[Messages]`(마법사 언어별).
#   키는 Inno 메시지 이름 그대로. 261009-12(사용자 지시): 설치 진행 중 '파일 추출 중...' 은 설치하는 단계인데
#   추출만 하는 것처럼 읽혔다.
WIZARD = {
    "StatusExtractFiles": trp("installer", "파일을 추출하여 설치하는 중..."),
}

APP_LANG = {
    "GuideFile": trp("installer", "사용안내(API키).txt"),
    "GuideIcon": trp("installer", "사용 안내 (API 키)"),
}
