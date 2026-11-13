# -*- coding: utf-8 -*-
"""261114-6(마스터 §1.1, 사용자 결정 'A안: 보이는 이름만'): 보이는 이름은 PolyPinax, 내부 ID 는 'PolyPDF' 그대로.

내부 ID 를 바꾸면 사용자 자료·설정을 잃는다(설정 폴더·서명 비밀번호·기본 앱·작업 표시줄 고정·업데이트 사슬·PDF 표식).
이 검사는 그 값이 그대로인지(F), 보이는 이름이 새 이름인지(V) 본다 — 이름 표의 주인은 마스터 §1.1.

V1 `viewer/branding.py` — APP_NAME = PolyPinax(보이는 이름), APP_ID = PolyPDF(내부 ID)
V2 화면 문구(`polypdf.pot` 의 msgid)에 보이는 이름으로 'PolyPDF' 가 없다 — 실행 파일·설치 파일 이름·폴더 이름은 내부 ID 라 둔다
V3 설치 프로그램 — 보이는 이름(MyAppName)은 PolyPinax, 레지스트리·설치 폴더는 내부 ID(MyAppId), 시작 메뉴 폴더는 새 이름(UsePreviousGroup=no)
V4 가상 프린터 — 이름 PolyPinax, 옛 'PolyPDF' 프린터는 설치 때 새 이름으로 바꾼다(`printer_plan`), 상태·인쇄 해상도는 옛 이름도 안다
V5 창 제목·정보 창·시작 그림은 branding.APP_NAME 을 쓴다
V6 도움말(help_*.html)에 보이는 이름으로 'PolyPDF' 가 없다(레이어 이름 'PolyPDF'·폴더·실행 파일 이름은 둔다)
V7 업데이트 도우미가 설치 정보 이름을 옛 이름·새 이름 모두 알아보고 새 이름으로 쓴다
F  내부 ID 표 — 하나라도 바뀌면 실패
"""
import os, re, sys, importlib
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def read(rel):
    with open(os.path.join(HERE, rel), encoding="utf-8-sig") as f:
        return f.read()


# 내부 ID 로 남기는 'PolyPDF' 꼴 — 실행 파일·설치 파일·휴대용 표식·특허 기본 폴더·설정 폴더·레이어 이름
KEEP = re.compile(r"PolyPDF(?=\.exe|-Setup|\.portable|_특허|\.pdf\b|\.photo\b)|LocalTools\\+PolyPDF|'PolyPDF' (?:레이어|layer)")


def visible_left(text):
    return [m.start() for m in re.finditer(r"PolyPDF", KEEP.sub("", text))]


try:
    # ── V1 ──
    try:
        branding = importlib.import_module("viewer.branding")
    except Exception as ex:
        branding = None
        chk(False, "V1 viewer/branding.py 가 있다", repr(ex))
    if branding:
        chk(getattr(branding, "APP_NAME", None) == "PolyPinax", "V1 보이는 이름 APP_NAME = PolyPinax", str(getattr(branding, "APP_NAME", None)))
        chk(getattr(branding, "APP_ID", None) == "PolyPDF", "V1 내부 ID APP_ID = PolyPDF", str(getattr(branding, "APP_ID", None)))

    # ── V2 ── 화면 문구
    pot = read("resources/locale/polypdf.pot")
    ids = re.findall(r'^msgid "(.*)"$', pot, re.M)
    left = [s for s in ids if visible_left(s)]
    chk(not left, "V2 화면 문구에 보이는 이름 'PolyPDF' 가 없다(%d개)" % len(left), str(left[:5]))

    # ── V3 ── 설치 프로그램
    iss = read("installer/PolyPDF.iss")
    chk(re.search(r'^#define MyAppName "PolyPinax"$', iss, re.M) is not None, "V3 설치 프로그램 보이는 이름 MyAppName = PolyPinax")
    chk(re.search(r'^#define MyAppId "PolyPDF"$', iss, re.M) is not None, "V3 설치 프로그램 내부 ID MyAppId = PolyPDF")
    chk(re.search(r"^DefaultDirName=\{autopf\}\\\{#MyAppId\}$", iss, re.M) is not None, "V3 설치 폴더는 내부 ID(Program Files\\PolyPDF)")
    chk(re.search(r"^UsePreviousGroup=no$", iss, re.M) is not None, "V3 시작 메뉴 폴더는 새 이름(옛 폴더 이어 쓰지 않음)")
    reg = iss[iss.index("\n[Registry]"):iss.index("\n[Run]")]
    bad = [ln for ln in reg.splitlines() if "Software\\{#MyAppName}" in ln or 'ValueName: "{#MyAppName}"' in ln]
    chk(not bad, "V3 레지스트리 키·등록 값 이름은 내부 ID(MyAppId)", str(bad[:3]))
    chk('ValueName: "ApplicationName"; ValueData: "{#MyAppName}"' in reg, "V3 기본 앱 화면에 보이는 이름은 새 이름")

    # ── V4 ── 가상 프린터
    vp = importlib.import_module("viewer.vprinter")
    chk(vp.PRINTER_NAME == "PolyPinax", "V4 가상 프린터 이름 PolyPinax", vp.PRINTER_NAME)
    chk("PolyPDF" in getattr(vp, "LEGACY_PRINTER_NAMES", ()), "V4 옛 프린터 이름 'PolyPDF' 를 안다")
    plan = getattr(vp, "printer_plan", None)
    chk(callable(plan), "V4 printer_plan 이 있다")
    if callable(plan):
        chk(plan(["Microsoft Print to PDF"]) == ("add", None), "V4 프린터 없음 → 새로 만든다", str(plan(["Microsoft Print to PDF"])))
        chk(plan(["PolyPDF", "Fax"]) == ("rename", "PolyPDF"), "V4 옛 'PolyPDF' 만 있음 → 새 이름으로 바꾼다(기본 프린터·설정 유지)", str(plan(["PolyPDF"])))
        chk(plan(["PolyPinax"]) == ("keep", None), "V4 새 이름 있음 → 그대로", str(plan(["PolyPinax"])))
        chk(plan(["PolyPinax", "PolyPDF"]) == ("keep", "PolyPDF"), "V4 둘 다 있음 → 옛 것을 지운다", str(plan(["PolyPinax", "PolyPDF"])))
    vsrc = read("viewer/vprinter.py")
    chk("for name in (PRINTER_NAME,) + LEGACY_PRINTER_NAMES" in vsrc, "V4 제거는 옛 이름 프린터도 지운다")
    pc = read("viewer/print_controller.py")
    chk("vprinter.ALL_PRINTER_NAMES" in pc, "V4 인쇄 해상도 제한은 옛 이름 프린터에도")
    vc = read("viewer/vprinter_controller.py")
    chk("ALL_PRINTER_NAMES" in vc, "V4 설치 여부 확인은 옛 이름 프린터도 본다")

    # ── V5 ── 창 제목·정보 창·시작 그림
    app = read("viewer/app.py")
    chk('f"PolyPDF  v' not in app and "APP_NAME" in app, "V5 창 제목은 APP_NAME")
    chk("<h3>PolyPDF</h3>" not in read("viewer/about.py"), "V5 정보 창 제목은 APP_NAME")
    chk('AlignCenter, "PolyPDF")' not in read("main.py"), "V5 시작 그림 글자는 APP_NAME")
    for rel in ("viewer/app.py", "viewer/widgets/thumbs_list.py"):
        chk('QMessageBox.information(self, "PolyPDF"' not in read(rel), "V5 알림 창 제목은 APP_NAME — " + rel)

    # ── V6 ── 도움말
    for rel in ("resources/help/help_ko.html", "resources/help/help_en.html"):
        n = visible_left(read(rel))
        chk(not n, "V6 도움말에 보이는 이름 'PolyPDF' 가 없다 — " + rel, "%d곳" % len(n))

    # ── V7 ── 업데이트 도우미 — 설치 정보(제거 목록) 이름
    up = importlib.import_module("viewer.updater")
    chk("-like 'PolyPinax*'" in up._PS_INSTALLER and "-like 'PolyPDF*'" in up._PS_INSTALLER,
        "V7 업데이트 도우미가 설치 정보 이름을 옛·새 이름 모두 알아본다")
    chk("('PolyPinax v' + $nv)" in up._PS_INSTALLER, "V7 업데이트 도우미가 설치 정보 이름을 새 이름으로 쓴다")

    # ── F ── 내부 ID 표(바꾸면 사용자 자료·설정을 잃는다 — 마스터 §1.1)
    main_src = read("main.py")
    chk('APP_USER_MODEL_ID = "LocalTools.PolyPDF"' in main_src, "F 작업 표시줄 앱 ID LocalTools.PolyPDF(고정·묶음)")
    chk(len(re.findall(r'setApplicationName\(APP_ID \+', main_src)) == 2 and "from viewer.branding import APP_ID" in main_src,
        "F 설정 폴더 이름(앱 이름)은 내부 ID — %APPDATA%\\LocalTools\\PolyPDF")
    chk(re.search(r"^AppId=\{\{8E7B5A30-6E2C-4E2B-9C1A-1A2B3C4D5E6F\}$", iss, re.M) is not None, "F 설치 프로그램 AppId(업그레이드 = 같은 앱)")
    chk(re.search(r'^#define MyProgId "PolyPDF.pdf"$', iss, re.M) is not None, "F ProgID PolyPDF.pdf(사용자가 고른 기본 앱)")
    chk(re.search(r'^#define MyAppExe "PolyPDF.exe"$', iss, re.M) is not None, "F 실행 파일 이름 PolyPDF.exe")
    chk(re.search(r"^OutputBaseFilename=PolyPDF-Setup-v\{#MyAppVersion\}$", iss, re.M) is not None, "F 설치 파일 이름 PolyPDF-Setup-v…(옛 판 업데이트가 찾는다)")
    chk(iss.count('AppUserModelID: "LocalTools.PolyPDF"') == 2, "F 바로가기 작업 표시줄 앱 ID")
    chk("{userappdata}\\LocalTools\\PolyPDF\\settings.json" in iss, "F 설치 프로그램이 읽는 설정 파일 자리")
    ss = importlib.import_module("viewer.settings_store")
    chk(ss.PORTABLE_MARKER == "PolyPDF.portable", "F 휴대용 표식 PolyPDF.portable")
    chk(str(ss.local_data_dir()).endswith("PolyPDF") or ss.PORTABLE, "F 도구 자료 폴더 %LOCALAPPDATA%\\PolyPDF", str(ss.local_data_dir()))
    pdfd = importlib.import_module("viewer.pdf_default")
    chk((pdfd.APP, pdfd.PROG_ID, pdfd.CAPS) == ("PolyPDF", "PolyPDF.pdf", r"Software\PolyPDF\Capabilities"), "F 기본 PDF 앱 등록 이름")
    src = read("viewer/photo_default.py")
    chk('APP = "PolyPDFPhoto"' in src and 'PROG_ID = "PolyPDF.photo"' in src and r'CAPS = r"Software\PolyPDF\PhotoCapabilities"' in src,
        "F 기본 사진 앱 등록 이름")
    sh = importlib.import_module("viewer.sign_hello")
    chk((sh.KEY_NAME, sh._INFO) == ("PolyPDF.sign", b"PolyPDF sign password v1"), "F Windows Hello 키 이름(바꾸면 서명 비밀번호를 못 연다)")
    pm = importlib.import_module("viewer.pdf_mirror")
    chk((pm.LAYER, pm.LINK_NM, pm.HASH_KEY, pm.AUTHOR_KW, pm.RESIGN_URI) ==
        ("PolyPDF", "PolyPDF:link", "PolyPDFHash", "PolyPDFAuthorKeywords", "polypdf-resign:"), "F PDF 안 표식(레이어·링크·지문·저자 키워드·재서명)")
    ta = read("viewer/text_apply.py")
    chk('TEXT_LAYER_KEY = "PolyPDFTextLayer"' in ta and 'TEXT_LAYER_CHECK_KEY = "PolyPDFTextLayerCheck"' in ta, "F PDF 글자층 기록 키")
    chk('".polypdf_file_tags.json"' in read("viewer/tag_store.py") and '".polypdf_tag_candidates.json"' in read("viewer/tag_store.py"),
        "F 폴더 옆 태그 파일 이름")
    chk('".polypdf_dict.db"' in read("viewer/study/dict_store.py") and '".polypdf_dict_images"' in read("viewer/study/image_fetch.py"),
        "F 폴더 옆 사전 파일 이름")
    sb = importlib.import_module("viewer.share_bundle")
    chk((sb.FORMAT, sb.SUFFIX, sb.MANIFEST) == ("polypdf-share", ".polypdf.zip", "polypdf_share.json"), "F 전달 묶음 형식·확장자")
    chk((up.DEFAULT_REPO, up.ASSET_NAME) == ("kdjeong777-ops/PolyPDF", "PolyPDF-windows.zip") and '"polypdf-setup-"' in read("viewer/updater.py"),
        "F 업데이트 저장소·자산 이름(옛 판이 찾는다)")
    chk(up.INNO_APP_ID == "{8E7B5A30-6E2C-4E2B-9C1A-1A2B3C4D5E6F}", "F 업데이트의 설치 프로그램 AppId")
    i18 = read("viewer/i18n.py")
    chk('DOMAIN = "polypdf"' in i18 and r'r"Software\PolyPDF"' in i18, "F 번역 도메인·설치 언어 레지스트리 키")
    chk((vp.DRIVER_NAME, vp.PORT_NAME, vp.MONITOR_NAME, vp.MONITOR_DLL, vp.TASK_PREFIX) ==
        ("PolyPDF", "PolyPDF Port", "PolyPDF Port Monitor", "polypdfmon.dll", "PolyPDF Print Receiver - "), "F 가상 프린터 드라이버·포트·모니터·예약 작업 이름")
    chk('"application/x-polypdf-pages"' in read("viewer/widgets/thumbs_list.py") and '"application/x-polypdf-deco"' in read("viewer/widgets/main_view.py"),
        "F 클립보드·끌기 형식(창끼리·판끼리 주고받는다)")
    chk('"polypdf-{_user()}-{os.getpid()}-{next(_seq)}"' in read("viewer/instance_link.py") and '"polypdf-open-{_user()}"' in read("viewer/open_gather.py"),
        "F 창 사이 연결 이름(업데이트 중 옛 창·새 창)")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
