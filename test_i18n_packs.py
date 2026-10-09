# -*- coding: utf-8 -*-
"""다국어(언어팩) SOT Phase 0b — 언어팩 도구(scripts/i18n.py)와 내장 팩 규칙 (261008).

A. extract — tr·trp·trn·tr_noop 키·문맥·복수·나온 자리, 리터럴이 아니면 경고, 같은 원문은 한 키
B. update — 새 키는 빈칸, 원문이 조금 바뀌면 fuzzy 로 번역을 살리고, 사라진 키는 obsolete
C. init — 언어별 복수형(CLDR)·pack.json(자기 이름·fallback en)
D. report·compile — 완성도·자리표시 불일치, fuzzy 는 .mo 에서 빠져 대체 사슬로
E. pseudo — 표시·늘림·자리표시 보존, POLYPDF_LANG=qps_ploc 로 실제 번역됨, 목록에는 없음
F. 내장 팩 — pack.json 형식·코드=폴더·Plural-Forms·자리표시·대체 사슬·.pot 의 모든 키·complete 면 100%·en 존재
G. .pot 가 코드와 같다(감싼 뒤 extract 를 잊지 않게) · 추출 경고 0
H. 메인 창(Phase 2 완료 조건) — 가짜 언어로 띄운 실제 MainWindow 의 메뉴(하위까지)·단추·글자표·콤보·입력 안내·
   도움말 풍선에 표시 없는 한국어가 없다. 예외: 단어학습 패널(한국 전용 — Phase 4)·글꼴 이름(고유명사)
I. 쓰기는 내용이 바뀔 때만(생성 시각만 다르면 그대로)
J. 작업 세션 자동 번역(261009-10) — todo(빈칸·fuzzy·이전 원문)·fill(한글·자리표시·& 검사)·고쳤다 되돌리면 확정 그대로·
   '# | msgid' 주석이 쌓이지 않음·Stop 훅(막기·통과·한 번만)
"""
import os, sys, re, json, tempfile, shutil, importlib.util
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("POLYPDF_LANG", None)
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("i18n_tool", HERE / "scripts" / "i18n.py")
T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)
root = Path(tempfile.mkdtemp(prefix="polypdf_i18n_tool_"))

try:
    from babel.messages.pofile import read_po, write_po

    def po(path):
        with open(path, "rb") as f:
            return read_po(f)

    # ── A ──
    src = root / "src"; (src / "viewer").mkdir(parents=True)
    (src / "main.py").write_text("from viewer.i18n import tr\nx = tr('시작')\n", encoding="utf-8")
    (src / "viewer" / "a.py").write_text(
        "from viewer import i18n\n"
        "a = i18n.tr('저장')\n"
        "b = i18n.trp('메뉴', '열기')\n"
        "c = i18n.trn('파일 {n}개', 3).format(n=3)\n"
        "d = i18n.tr_noop('사각형')\n"
        "e = i18n.tr('저장')\n"
        "name = '파일'\n"
        "f = i18n.tr(f'{name} 열기')\n", encoding="utf-8")
    loc = src / "resources" / "locale"
    cat, warns = T.extract(base=src)
    keys = {(m.id if isinstance(m.id, str) else tuple(m.id), m.context) for m in cat if m.id}
    chk(("저장", None) in keys and ("열기", "메뉴") in keys and (("파일 {n}개", "파일 {n}개"), None) in keys
        and ("사각형", None) in keys and ("시작", None) in keys, "A 네 함수의 키·문맥·복수를 뽑는다", str(keys))
    m = cat.get("저장")
    chk(len(m.locations) == 2 and m.locations[0][0] == "viewer/a.py", "A 같은 원문은 한 키, 나온 자리 둘", str(m.locations))
    chk(len(warns) == 1 and "f-string" in warns[0], "A 리터럴이 아닌 원문은 경고", str(warns))
    chk((loc / "polypdf.pot").is_file(), "A .pot 를 쓴다")

    # ── C ──
    T.init("en", locale_dir=loc); T.init("ja", locale_dir=loc)
    ja = po(loc / "ja" / "LC_MESSAGES" / "polypdf.po")
    chk(ja.num_plurals == 1 and po(loc / "en" / "LC_MESSAGES" / "polypdf.po").num_plurals == 2,
        "C 복수형 규칙을 언어별로(ja 1형·en 2형)")
    meta = json.loads((loc / "ja" / "pack.json").read_text(encoding="utf-8"))
    chk(meta["name"] == "日本語" and meta["fallback"] == ["en"] and meta["code"] == "ja"
        and json.loads((loc / "en" / "pack.json").read_text(encoding="utf-8"))["fallback"] == [],
        "C pack.json — 자기 이름, 한국어가 아닌 언어는 en 을 거친다", str(meta))
    try:
        T.init("ja", locale_dir=loc); chk(False, "C 이미 있는 팩은 덮지 않는다")
    except FileExistsError:
        chk(True, "C 이미 있는 팩은 덮지 않는다")

    # 번역을 채운다
    en_path = loc / "en" / "LC_MESSAGES" / "polypdf.po"
    en = po(en_path)
    en.get("저장").string = "Save"
    en.get("열기", context="메뉴").string = "Open"
    en.get(("파일 {n}개", "파일 {n}개")).string = ("{n} file", "{n} files")
    en.get("사각형").string = "Rectangle {x}"            # 자리표시 불일치(일부러)
    with open(en_path, "wb") as f:
        write_po(f, en)

    # ── B ──
    (src / "viewer" / "a.py").write_text(
        "from viewer import i18n\n"
        "a = i18n.tr('저장하기')\n"          # 원문이 조금 바뀜
        "b = i18n.trp('메뉴', '열기')\n"
        "c = i18n.trn('파일 {n}개', 3)\n"
        "g = i18n.tr('새 문구')\n", encoding="utf-8")
    T.extract(base=src)
    chk(T.update(locale_dir=loc) == ["en", "ja"], "B 모든 팩을 맞춘다")
    en = po(en_path)
    m = en.get("저장하기")
    chk(m is not None and m.fuzzy and m.string == "Save", "B 바뀐 원문은 비슷한 번역을 fuzzy 로 살린다", str(m and (m.string, m.fuzzy)))
    chk(en.get("새 문구") is not None and en.get("새 문구").string == "", "B 새 키는 빈칸")
    chk("사각형" in en.obsolete, "B 사라진 키는 obsolete(#~)", str(list(en.obsolete)))

    # ── D ──
    en = po(en_path)
    en.get(("파일 {n}개", "파일 {n}개")).string = ("{n} file", "{n} files {x}")
    with open(en_path, "wb") as f:
        write_po(f, en)
    r = T.report(locale_dir=loc)["en"]
    chk(r["total"] == 5 and r["fuzzy"] == 1 and r["translated"] == 2 and r["empty"] == 2,
        "D 완성도·fuzzy·빈칸 집계", str(r))
    chk(r["placeholder_mismatch"] == ["파일 {n}개"], "D 자리표시 불일치를 잡는다", str(r["placeholder_mismatch"]))
    T.compile_all(locale_dir=loc, quiet=True)
    from viewer import i18n
    i18n.pack_dir = lambda: loc
    i18n.install(None, "en")
    chk(i18n.tr("저장하기") == "저장하기", "D fuzzy 번역은 .mo 에서 빠져 원문(대체 사슬)으로")
    chk(i18n.trp("메뉴", "열기") == "Open", "D 번역된 문구는 그대로")

    # ── E ──
    pt = T.pseudo_text("'{name}' 파일(&F) 저장")
    chk(pt.startswith("[!! ") and pt.endswith(" !!]") and "{name}" in pt and "&F" in pt and len(pt) > len("'{name}' 파일(&F) 저장"),
        "E 가짜 번역 — 표시·늘림, 자리표시·단축키 보존", pt)
    chk(T.pseudo_text("Save").startswith("[!! Šàṽé"), "E 라틴 글자는 바꾼다", T.pseudo_text("Save"))
    T.pseudo(locale_dir=loc)
    os.environ["POLYPDF_LANG"] = "qps_ploc"
    i18n.install(None, "ko")
    chk(i18n.language() == "qps_ploc" and i18n.tr("새 문구").startswith("[!! "), "E POLYPDF_LANG=qps_ploc 로 가짜 번역이 보인다")
    _pl = i18n.trn("파일 {n}개", 2).format(n=2)
    chk(_pl.startswith("[!! ") and "2" in _pl, "E 복수 문구도 가짜 번역(자리표시 채워짐)", _pl)
    os.environ.pop("POLYPDF_LANG")
    chk("qps_ploc" not in [c for c, _n, _s in i18n.available_languages()], "E 가짜 언어는 고르는 목록에 없다")
    T.clean_pseudo(locale_dir=loc)
    chk(not (loc / "qps_ploc").exists(), "E clean-pseudo 가 지운다")

    # ── I ──
    before = (loc / "polypdf.pot").read_bytes()
    T.extract(base=src)
    chk((loc / "polypdf.pot").read_bytes() == before, "I 내용이 같으면 다시 쓰지 않는다(생성 시각만 다른 diff 없음)")

    # ── J — 작업 세션 자동 번역: todo·fill·되돌림·Stop 훅 (SOT §12.3, 261009-10) ──
    items = T.todo(locale_dir=loc, langs=["en"])
    ids = {i["id"] for i in items}
    chk({"저장하기", "새 문구"} <= ids, "J todo — 빈칸·fuzzy 를 모은다", str(ids))
    fz = [i for i in items if i["id"] == "저장하기"]
    chk(fz and fz[0].get("suggest") == "Save" and fz[0].get("previous") == "저장",
        "J todo — fuzzy 는 지금 번역·이전 원문을 함께(Babel 이 #| 를 주석으로 읽는 것을 바로잡음)", str(fz))
    done, errs = T.fill([{"lang": "en", "ctx": None, "id": "저장하기", "str": "Save it"},
                         {"lang": "en", "ctx": None, "id": "새 문구", "str": "새 phrase {x}"},
                         {"lang": "en", "ctx": "메뉴", "id": "열기", "str": "&Open"}], locale_dir=loc)
    chk(done == 1 and len(errs) == 2, "J fill — 검사를 통과한 것만 넣는다", str((done, errs)))
    why = " ".join(e[2] for e in errs)
    chk("한글" in why and "자리표시" in why and "단축키" in why, "J fill — 한글 남음·자리표시·& 수를 거부", why)
    chk(T._accels("파일(&F)") == 1 and T._accels("Spacing & Crop") == 0 and T._accels("a &amp; b") == 0
        and T._accels("R&&D") == 0, "J 단축키 & — 글자 앞 & 만 센다('A & B'·&amp;·&& 는 아님)")
    m = T._read_po(en_path, locale="en").get("저장하기")
    chk(m.string == "Save it" and not m.fuzzy, "J fill 뒤 fuzzy 해제", str((m.string, m.fuzzy)))
    chk("# | msg" not in en_path.read_text(encoding="utf-8"), "J 이전 원문(#|)이 일반 주석 '# | msgid' 로 쌓이지 않는다")
    a_src = (src / "viewer" / "a.py").read_text(encoding="utf-8")
    (src / "viewer" / "a.py").write_text(a_src.replace("'저장하기'", "'저장하기 시험'"), encoding="utf-8")
    T.extract(base=src); T.update(locale_dir=loc)
    (src / "viewer" / "a.py").write_text(a_src, encoding="utf-8")
    T.extract(base=src); T.update(locale_dir=loc)
    m = T._read_po(en_path, locale="en").get("저장하기")
    chk(m.string == "Save it" and not m.fuzzy, "J 원문을 고쳤다 되돌리면 확정 번역 그대로(fuzzy 아님)", str((m.string, m.fuzzy)))
    _sync = T.sync
    try:
        T.sync = lambda base=None: ([], [])
        chk(T.hook_stop('{"stop_hook_active": false}') == "", "J hook-stop — 할 일이 없으면 통과")
        T.sync = lambda base=None: ([], [{"lang": "en", "ctx": None, "id": "새 문구", "files": []}])
        out = json.loads(T.hook_stop('{"stop_hook_active": false}') or "{}")
        chk(out.get("decision") == "block" and "fill" in out.get("reason", ""), "J hook-stop — 빈칸이 있으면 막고 할 일을 알린다", str(out))
        chk(T.hook_stop('{"stop_hook_active": true}') == "", "J hook-stop — 한 번 막힌 뒤에는 다시 막지 않는다(무한 반복 방지)")
    finally:
        T.sync = _sync

    # ── F·G — 내장 팩 ──
    real = HERE / "resources" / "locale"
    # 언어를 바꾼 직후에도 읽히게 일부러 두 언어로 쓴 원문(다국어 SOT §4 재시작 안내·설정 이름표)
    importlib.reload(i18n)
    cat_real, warns_real = T.extract_from(T.source_files(HERE), HERE)
    chk(not warns_real, "G 코드의 추출 경고 0(키는 문자열 리터럴)", str(warns_real[:5]))
    pot_keys = {(m.id if isinstance(m.id, str) else m.id[0], m.context) for m in po(real / "polypdf.pot") if m.id}
    code_keys = {(t, c) for t, c, _p, _l in cat_real}
    chk(pot_keys == code_keys, "G resources/locale/polypdf.pot 가 코드와 같다(감싼 뒤 extract)",
        "누락 %d · 남음 %d" % (len(code_keys - pot_keys), len(pot_keys - code_keys)))
    packs = T.packs(real)
    chk("en" in [p.name for p in packs], "F 내장 en 팩이 있다")
    for d in packs:
        meta = json.loads((d / "pack.json").read_text(encoding="utf-8"))
        chk(meta.get("code") == d.name and meta.get("name") and meta.get("status") in ("complete", "partial")
            and meta.get("direction", "ltr") == "ltr", "F %s pack.json 형식·코드=폴더" % d.name, str(meta))
        cat = po(d / "LC_MESSAGES" / "polypdf.po")
        chk(cat.num_plurals >= 1 and "Plural-Forms" in dict(cat.mime_headers), "F %s Plural-Forms" % d.name)
        r = T._report_cat(cat)
        chk(not r["placeholder_mismatch"], "F %s 자리표시가 원문과 같다" % d.name, str(r["placeholder_mismatch"][:5]))
        have = {(m.id if isinstance(m.id, str) else m.id[0], m.context) for m in cat if m.id}
        chk(pot_keys <= have, "F %s 에 .pot 의 키가 모두 있다(update 를 돌렸다)" % d.name, str(len(pot_keys - have)))
        if meta.get("status") == "complete":
            chk(r["translated"] == r["total"] and r["fuzzy"] == 0, "F %s complete 면 100%%·fuzzy 0" % d.name)
        chain = i18n._chain(d.name)
        chk(chain and chain[0] == d.name and len(chain) == len(set(chain)), "F %s 대체 사슬에 고리·중복 없음" % d.name, str(chain))
        # 261009(영어번역 재검토 F2): 번역문에 한글이 남으면 안 된다 — 허용은 셋뿐.
        #   ① 언어를 바꾼 직후 읽히도록 일부러 두 언어로 쓴 안내(원문에 영어가 함께 있다)
        #   ② 원문에 든 정규식 예시 '제1장' ③ 실제 파일 이름 접미 `_번역`(한국 전용 번역 기능의 산출물)
        leak = []
        for m in cat:
            if not m.id:
                continue
            mid = m.id if isinstance(m.id, str) else m.id[0]
            s = " / ".join(m.string) if isinstance(m.string, (list, tuple)) else (m.string or "")
            if T.hangul_leak(mid, s):                            # 규칙은 scripts/i18n.py 한 곳(fill 도 같은 것)
                leak.append(mid[:30])
        chk(not leak, "F %s 번역문에 한글이 남지 않았다(허용: 두 언어 안내·'제1장'·_번역)" % d.name, str(leak[:5]))
    chk(not (real / "qps_ploc").exists(), "F 가짜 언어 폴더가 저장소·빌드에 남아 있지 않다")

    # ── H — 메인 창 감싸기(Phase 2) ──
    T.pseudo(locale_dir=real)
    os.environ["POLYPDF_LANG"] = "qps_ploc"
    i18n.install(None, "ko")
    # 새 사용자처럼 — 다른 검사가 남긴 설정(한국어로 저장된 사용자 이름 등)을 읽지 않게 빈 설정 폴더로
    from PyQt6.QtCore import QCoreApplication
    _old_app = QCoreApplication.applicationName()
    QCoreApplication.setApplicationName("polypdf_i18n_h_%d" % os.getpid())
    from viewer import settings_store as _ss
    _h_dir = _ss.settings_dir()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    from PyQt6.QtWidgets import (QWidget, QAbstractButton, QLabel, QComboBox,
                                 QLineEdit, QTabWidget)
    from viewer.widgets.study_panel import StudyPanel
    _FONTS = {"맑은 고딕", "굴림", "바탕", "돋움", "궁서"}
    bare = []

    def _see(t, where):
        if ":\\" in t or ":/" in t:                    # 최근 파일·폴더 경로 = 사용자 데이터
            return
        if t and t not in _FONTS and "[!!" not in t and any("가" <= ch <= "힣" for ch in t):
            bare.append((where, t))

    def _menu(m, path):
        for a in m.actions():
            _see(a.text(), path)
            if a.menu():
                _menu(a.menu(), path + ">" + a.text())
    titles = [a.text() for a in mw.menuBar().actions()]
    for a in mw.menuBar().actions():
        _see(a.text(), "menubar")
        if a.menu():
            _menu(a.menu(), a.text())
    studies = mw.findChildren(StudyPanel)
    for w in mw.findChildren(QWidget):
        if any(sp is w or sp.isAncestorOf(w) for sp in studies):
            continue                                   # 한국 전용(§7) — Phase 4
        nm = type(w).__name__
        _see(w.toolTip(), nm + ".tip")
        if isinstance(w, (QAbstractButton, QLabel)):
            _see(w.text(), nm)
            _m = getattr(w, "menu", None)
            if callable(_m) and _m() is not None:           # 단추에 달린 메뉴(읽기 속도 등)
                _menu(_m(), nm + ".menu")
        elif isinstance(w, QComboBox):
            for i in range(w.count()):
                _see(w.itemText(i), nm)
        elif isinstance(w, QLineEdit):
            _see(w.placeholderText(), nm)
        elif isinstance(w, QTabWidget):
            for i in range(w.count()):
                _see(w.tabText(i), nm)
    chk(titles and all("[!!" in t for t in titles if t),
        "H 메뉴 막대가 모두 번역 표시(감쌈)", str(titles))
    chk(not bare, "H 메인 창에 표시 없는 한국어가 없다(단어학습 패널·글꼴 이름 제외)", str(bare[:10]))
    os.environ.pop("POLYPDF_LANG")
    QCoreApplication.setApplicationName(_old_app)
    shutil.rmtree(str(_h_dir), ignore_errors=True)
    T.clean_pseudo(locale_dir=real)
    i18n.install(None, "ko")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    os.environ.pop("POLYPDF_LANG", None)
    try:
        T.clean_pseudo(locale_dir=HERE / "resources" / "locale")
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
