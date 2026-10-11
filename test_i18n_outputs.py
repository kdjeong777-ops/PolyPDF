"""다국어 SOT §8 — 생성 결과물·도움말 (Phase 5, 261008-26)

A. 도움말은 `resources/help/help_<코드>.html` — 언어마다 대체 사슬(`resource_chain`) 차례로 찾는다
   (ko → ko, en → en, 도움말이 없는 언어 → 그 언어의 fallback → 한국어 원문)
B. 영어 도움말에는 한글이 없고 숨긴 한국 전용 기능(§7: 단어장·법령·KCSC·KIPO·번역)을 말하지 않는다 ·
   도움말이 가리키는 메뉴 이름이 실제 영어 메뉴와 같다
C. 다단의 기본 목차 쪽 제목은 만드는 때의 화면 언어(ko '목차', en 'Contents')
D. 저장 창에 제안하는 기본 파일 이름은 화면 언어를 따르고, 번역된 이름에 Windows 가 막는 글자가 없다
E. 실제 사용법 창이 그 언어의 도움말을 보여 준다
F. 도움말이 실제 기능과 같다(261009-11) — app.py 기본 단축키가 두 도움말 표에 모두 · 낡은 경로·없어진 설정 없음 ·
   영어 도움말의 메뉴·옵션 이름이 실제 영어 화면과 같음 · 한국어 도움말이 새 기능 절을 갖춤
"""
import os, sys, re, json, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("POLYPDF_LANG", None)
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []
H = re.compile(r"[가-힣]")


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_i18n_out_"))
try:
    from viewer import i18n
    from viewer.widgets.help_dialog import usage_html, HelpDialog

    # ── A ──
    i18n.install(None, "ko")
    chk(i18n.resource_chain() == ["ko"], "A ko 사슬", str(i18n.resource_chain()))
    ko_html = usage_html()
    chk("PolyPDF 사용법" in ko_html and "단어장" in ko_html, "A ko 는 한국어 도움말(종전 내용)")
    i18n.install(None, "en")
    chk(i18n.resource_chain() == ["en", "ko"], "A en 사슬", str(i18n.resource_chain()))
    en_html = usage_html()
    chk("Using PolyPDF" in en_html, "A en 은 영어 도움말")

    # 도움말이 없는 언어 → fallback(en) → ko. 임시 언어팩 'ja'(fallback en) 를 만들어 본다
    from babel.messages.catalog import Catalog
    from babel.messages.mofile import write_mo
    real_dir = i18n.pack_dir
    loc = tmp / "locale"
    for code, fb in (("en", []), ("ja", ["en"])):
        d = loc / code / "LC_MESSAGES"; d.mkdir(parents=True)
        with open(d / "polypdf.mo", "wb") as f:
            write_mo(f, Catalog(locale=code))
        (loc / code / "pack.json").write_text(json.dumps(
            {"code": code, "name": code, "english_name": code, "status": "partial",
             "fallback": fb, "rtl": False, "qt": "", "inno": ""}), encoding="utf-8")
    i18n.pack_dir = lambda: loc
    try:
        i18n.install(None, "ja")
        chk(i18n.resource_chain() == ["ja", "en", "ko"], "A 도움말 없는 언어(ja→en)의 사슬", str(i18n.resource_chain()))
        chk("Using PolyPDF" in usage_html(), "A ja 는 영어 도움말로 물러난다")
    finally:
        i18n.pack_dir = real_dir

    # ── B ──
    i18n.install(None, "en")
    text = re.sub(r"<!--.*?-->", "", en_html, flags=re.S)
    chk(not H.search(text), "B 영어 도움말에 한글이 없다", str(H.findall(text)[:5]))
    hidden = [w for w in ("Vocabulary", "vocabulary", "KCSC", "KIPO", "Laws", "patent", "Translate", "translation")
              if w in text]
    chk(not hidden, "B 영어 도움말이 숨긴 한국 전용 기능을 말하지 않는다", str(hidden))
    for ko_name in ("사용법", "정보", "단축키 설정...", "책갈피 자동 생성...", "책갈피 생성",
                    "책갈피 모두 펼치기", "책갈피 모두 접기", "클립보드로 복사", "클립보드 가져오기",
                    "사용자 크기 설정", "책갈피 추가"):
        en_name = i18n.tr(ko_name).replace("...", "")
        chk(en_name in text, "B 도움말의 메뉴 이름이 실제 영어 메뉴와 같다: %s" % en_name)
    ko_sec = len(re.findall(r"<h3>", ko_html)); en_sec = len(re.findall(r"<h3>", en_html))
    chk(en_sec == ko_sec - 1, "B 영어 도움말은 한국어 절에서 단어장 절 하나만 뺐다", "%d vs %d" % (en_sec, ko_sec))

    # ── C ──
    from viewer import twoup
    for code, want in (("ko", "목차"), ("en", "Contents")):
        i18n.install(None, code)
        d = twoup._fitz_toc_doc([("a.pdf", 3)], 595, 842)
        t = d[0].get_text()
        d.close()
        chk(want in t, "C %s 다단 기본 목차 제목 '%s'" % (code, want), t[:40])

    # ── D ──
    i18n.install(None, "en")
    chk(i18n.tr("{stem}_다단.pdf").format(stem="a") == "a_nup.pdf"
        and i18n.tr("스크린샷.pdf") == "Screenshots.pdf", "D en 기본 파일 이름")
    i18n.install(None, "ko")
    chk(i18n.tr("{stem}_다단.pdf").format(stem="a") == "a_다단.pdf", "D ko 기본 파일 이름은 종전과 같다")
    from babel.messages.pofile import read_po
    cat = read_po(open(Path(HERE) / "resources/locale/en/LC_MESSAGES/polypdf.po", "rb"), locale="en")
    bad = []
    for m in cat:
        if isinstance(m.id, str) and re.search(r"\.(pdf|docx|png)$", m.id) and not m.id.startswith(("<", "PDF")):
            name = re.sub(r"\{[^}]*\}", "x", m.string or "")
            if not name or re.search(r'[\\/:*?"<>|]', name):
                bad.append((m.id, m.string))
    chk(not bad, "D 번역된 파일 이름에 Windows 가 막는 글자가 없다", str(bad))

    # ── E ──
    i18n.install(None, "en")
    dlg = HelpDialog(); dlg.show(); app.processEvents()
    from PyQt6.QtWidgets import QTextBrowser
    b = dlg.findChild(QTextBrowser)
    chk(b is not None and "Using PolyPDF" in b.toPlainText(), "E 영어 사용법 창이 영어 도움말을 보여 준다")
    chk(dlg.windowTitle() == i18n.tr("PolyPDF — 사용법") and not H.search(dlg.windowTitle()), "E 창 제목도 영어")
    dlg.close()

    # ── F — 도움말이 실제 기능과 어긋나지 않게 (261009-11) ──
    # 종전 도움말은 '2분할 보기 Ctrl+2'(실제 2단 보기는 Ctrl+Shift+2, Ctrl+2 는 선 2)·'메뉴 → 설정 → 환경설정'(실제 도구 메뉴)처럼
    # 코드가 바뀐 뒤 낡아 있었다. 단축키 표의 기본 키는 app.py `_sc_defs` 에서 읽어 두 도움말에 모두 있는지 본다.
    src = (Path(HERE) / "viewer" / "app.py").read_text(encoding="utf-8")
    defs = re.findall(r'\("(\w+)",\s*\(tr\("[^"]+"\), "([^"]+)"', src)
    chk(len(defs) >= 15, "F app.py 에서 기본 단축키 표를 읽었다", str(len(defs)))
    for code, html in (("ko", ko_html), ("en", en_html)):
        miss = [k for sid, k in defs
                if k not in html and not (sid.startswith("draw_pen_") and "Ctrl+1" in html and "Ctrl+5" in html)]
        chk(not miss, "F [%s] 도움말 단축키 표에 기본 단축키가 모두 있다" % code, str(miss))
    chk("Ctrl+2</td>" not in ko_html and "Ctrl+2</td>" not in en_html, "F 2단 보기를 Ctrl+2 로 적지 않는다(Ctrl+2 는 선 2)")
    for stale in ("메뉴 → 설정 → 환경설정", "설정 → 단축키 설정", "파일 → 책갈피 자동 생성", "스크린샷 리스트 시작 시 복원"):
        chk(stale not in ko_html, "F ko 도움말에 낡은 경로·없어진 설정이 없다: %s" % stale)
    chk("Restore the screenshot list on startup" not in en_html, "F en 도움말에 없어진 설정이 없다")
    i18n.install(None, "en")
    for ko_name in ("도구", "환경설정...", "인덱스 재구축", "구성요소 설치(녹화·OCR)…", "Windows 기본 PDF 앱으로 등록…",
                    "현재 검색어를 즐겨찾기에 추가...", "즐겨찾기 관리...", "선과 텍스트 입력 설정…", "2단 보기",
                    "평탄화해서 내보내기...", "PDF로 인쇄", "다단 인쇄", "OCR 로 읽기", "해시태그 편집...", "녹화 테스트 (3초)",
                    "업데이트 자동 다운로드", "베타(테스트) 버전도 받기", "계속 편집"):
        en_name = i18n.tr(ko_name).replace("...", "").replace("…", "")
        chk(en_name in en_html, "F en 도움말의 이름이 실제 영어 화면과 같다: %s" % en_name)
    ko_sec = len(re.findall(r"<h3>", ko_html))
    chk(ko_sec >= 17, "F ko 도움말이 편집·쪽 편집·인쇄·텍스트 창·발표·태그 절을 갖는다", str(ko_sec))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    from viewer import i18n as _i
    _i.install(None, "ko")
    shutil.rmtree(str(tmp), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
