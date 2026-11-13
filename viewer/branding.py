# -*- coding: utf-8 -*-
"""프로그램 이름 — 제품·모드 이름과 내부 ID 를 한 곳에 (261114-6·261114-8, 마스터 §1.1).

이름 체계(사용자 결정 261114-8): 제품 = PolyPinax · PDF 모드 = PolyPDF · 사진 모드 = PolyPix — 새 모드는 `MODES` 한 줄.
- `APP_NAME`(= `PRODUCT`): 사용자에게 보이는 제품 이름(창 제목·정보 창·알림 창 제목·시작 그림·설치 프로그램·가상 프린터).
  번역 문구(`tr()`) 안의 이름은 원문 글자로 쓴다 — 바꿀 때는 이 값과 함께 문구·번역·도움말을 한 번에(작업 절차 SOT §4.1 의 1).
- **이사 스위치 `MOVED`**(261114-8, 사용자 결정 B안 '밖에 보이는 것만 이사'·'다음 판에 한 번에'): 켜면 밖에 보이는 제품 단위
  내부 ID(설정 폴더·실행 파일·설치 폴더·작업 표시줄 앱 ID·설치·업데이트 자산 이름·업데이트 저장소·사진 ProgID)가 PolyPinax/PolyPix 로 간다.
  **beta.13 다음 판(이사 판)에서 True 로 바꾼다** — 그 전에는 꺼 두어 지금 판과 똑같이 동작한다(지휘 세션이 아무 커밋에서나 태그를 찍을 수 있게).
  켜졌을 때 옛 이름을 읽는 길(설정 폴더 이사·옛 HKCU 등록 고치기·옛 프로세스 이름)은 `OLD_*` 를 본다.
- `LEGACY`: 바꾸지 않는 옛 이름 — 화면에 안 보이고 바꾸면 위험하다(`test_branding_ids_261114.py` F 가 지킨다).
- PDF 모드 단위(ProgID `PolyPDF.pdf`·PDF 안 표식·'PolyPDF' 레이어)는 모드 이름 그대로가 맞는 이름이라 바꾸지 않는다.
"""

MOVED = False                                  # ★ 이사 스위치 — 이사 판(beta.13 다음 판)에서 True

PRODUCT = "PolyPinax"
MODES = {"pdf": "PolyPDF", "photo": "PolyPix"}     # 모드 이름 — 새 모드(예: 영상)는 한 줄
APP_NAME = PRODUCT

OLD_ID = "PolyPDF"                             # 이사 전 제품 단위 내부 ID
NEW_ID = "PolyPinax"
OLD_REPO = "kdjeong777-ops/PolyPDF"
NEW_REPO = "kdjeong777-ops/PolyPinax"
# 구성요소(ffmpeg·Tesseract — `components` 릴리스)·자연 음성 모델(`neural_tts.COMPONENTS_BASE`)은 옛 저장소에 그대로 둔다 —
#   이사 판 뒤 옛 저장소는 지우지 않고 보관(archive)만 해 계속 받을 수 있다. 새 저장소로 옮기면 이 줄과 neural_tts 주소를 함께.
COMPONENTS_REPO = OLD_REPO


def ids(moved: bool) -> dict:
    """제품 단위 내부 ID — `moved` 상태로. 모듈 값은 `ids(MOVED)`. 검사는 `ids(True)` 로 이사 판 값을 본다."""
    app_id = NEW_ID if moved else OLD_ID
    return {
        "APP_ID": app_id,                                     # 앱 이름 = 설정 폴더(%APPDATA%\LocalTools\<>)·QSettings·HKLM\Software\<>
        "EXE_STEM": app_id,                                   # 실행 파일 <>.exe · dist\<> · 설치 폴더 Program Files\<>
        "AUMID": "LocalTools." + app_id,                      # 작업 표시줄 앱 ID(설치본 바로가기와 같게)
        "SETUP_PREFIX": app_id + "-Setup-v",                  # 설치 파일 <>-Setup-v<판>.exe
        "ASSET_PREFIX": app_id,                               # 릴리스 zip <>-<태그>-win64…zip
        "UPDATE_REPO": NEW_REPO if moved else OLD_REPO,       # 앱 안 업데이트가 보는 저장소
        "PORTABLE_MARKER": app_id + ".portable",              # 휴대용 표식
        "PHOTO_PROG_ID": ("PolyPix" if moved else "PolyPDF") + ".photo",   # 사진 모드 ProgID(모드 이름)
        "PHOTO_APP": ("PolyPix" if moved else "PolyPDF") + "Photo",        # RegisteredApplications 값 이름
    }


_I = ids(MOVED)
APP_ID = _I["APP_ID"]
EXE_STEM = _I["EXE_STEM"]
EXE_NAME = EXE_STEM + ".exe"
AUMID = _I["AUMID"]
SETUP_PREFIX = _I["SETUP_PREFIX"]
ASSET_PREFIX = _I["ASSET_PREFIX"]
UPDATE_REPO = _I["UPDATE_REPO"]
PORTABLE_MARKER = _I["PORTABLE_MARKER"]
PHOTO_PROG_ID = _I["PHOTO_PROG_ID"]
PHOTO_APP = _I["PHOTO_APP"]

# 두 이름 모두 알아보는 것 — 스위치와 상관없이(이사 판 전후의 판이 섞여 있어도: 다른 창 찾기·설치 파일·휴대용 표식·ProgID 고치기)
ALL_EXE_NAMES = (NEW_ID + ".exe", OLD_ID + ".exe")
ALL_SETUP_PREFIXES = (NEW_ID + "-Setup-v", OLD_ID + "-Setup-v")
OLD_PORTABLE_MARKERS = tuple(dict.fromkeys((PORTABLE_MARKER, NEW_ID + ".portable", OLD_ID + ".portable")))
ALL_PHOTO_PROG_IDS = ("PolyPix.photo", "PolyPDF.photo")

# 바꾸지 않는 옛 이름(LEGACY) — 까닭: 화면에 안 보이고, 바꾸면 사용자 자료를 잃거나 PC 전체에 영향(마스터 §1.1 표)
LEGACY = {
    "hello_key": "PolyPDF.sign",               # 저장한 서명 비밀번호(Windows Hello) — 바꾸면 못 연다
    "printer_driver": "PolyPDF",               # 가상 프린터 드라이버·포트·모니터 — 바꾸면 드라이버 재설치·스풀러 재시작
    "program_data": "PolyPDF",                 # %ProgramData%\PolyPDF(스풀·기록) — 포트 설정·ACL 이 가리킨다
    "pdf_prog_id": "PolyPDF.pdf",              # PDF 모드 이름 — 고른 기본 PDF 앱
    "pdf_marks": "PolyPDF",                    # PDF 안 표식(/PolyPDFHash·PolyPDF:link·레이어) — PDF 모드 이름
    "sidecars": ".polypdf_",                   # 폴더 옆 태그·사전 파일 — 사용자 폴더마다 흩어져 있다
    "bundle": ".polypdf.zip",                  # 전달 묶음 — 이미 주고받은 묶음
    "env": "POLYPDF_",                         # 환경 변수 — 검사·도구
    "i18n_domain": "polypdf",                  # 번역 파일 이름
    "ipc": "polypdf-",                         # 창 사이 연결·클립보드 형식 — 업데이트 중 옛 창·새 창
}
