# -*- coding: utf-8 -*-
"""환경설정 해시태그 '형식 낱말' — 체크 상자 + 이름 글 상자 하나, 새 분류 더하기 (태그 SOT §5.3·§5.8, 디자인 SOT §2.14, 261112-11).

사용자 지시(2026-11-12): 체크 상자 오른쪽의 고칠 수 없는 이름 글을 빼고 글 상자에서 이름을 고친다, 새 분류도 더한다.
사용자 결정: 새 분류는 '이름에 낱말'(파일 이름·PDF 제목), 이름을 바꾸면 이미 붙은 자동 태그도 새 이름으로.
실제 MainWindow·SettingsDialog 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 형식 줄에 고칠 수 없는 이름 글이 없다 — 체크 상자에 글이 없고, 글 상자에 지금 붙는 이름이 들어 있다
B. [분류 더하기] 를 눌러 이름·찾을 낱말을 넣으면 규칙에 `format_custom`, 이름 빈 새 줄은 버린다, [빼기] 로 줄이 빠진다
C. 판정 — 파일 이름·제목에 분류 이름이나 찾을 낱말이 있으면 그 형식(내장 ① 보다 먼저), 끄기·이름 바꾸기, 축은 '형식'
D. 규칙 정리·옮기기 — 같은 이름은 합치고, 더한 분류는 다시 판정 대상, 뺀 분류의 자동 태그는 빠지고, 내장 이름의 분류를 빼도 내장 태그는 남는다
E. [적용] 하면 tag_rules.json 에 들어가고 이미 붙은 자동 태그가 새 이름으로 바뀐다
"""
import os, sys, tempfile, shutil, time, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_rules_custom_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "형식 낱말 새 분류", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond, timeout=20.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tagcustom_"))
try:
    from viewer import auto_tag, tag_rules as TR
    from viewer.auto_tag import FORMAT_VOCAB
    from viewer.settings_store import settings_dir
    rp = Path(settings_dir()) / "tag_rules.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"alias": {"공문": "공문서"}, "format_custom": [{"name": "견적서", "words": ["견적"]}]},
                             ensure_ascii=False), encoding="utf-8")
    from viewer.app import MainWindow
    from viewer.widgets.settings_dialog import SettingsDialog
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.show(); pump(lambda: False, 0.3)
    store = mw.bookmark_tree._tags
    A, B = str(tmp / "a.pdf"), str(tmp / "b.pdf")
    store.set_auto(A, ["견적서", "아스팔트"]); store.set_auto(B, ["공문서"])
    dlg = SettingsDialog(mw._prefs, mw, host=mw, page="tags")
    dlg.show(); pump(lambda: False, 0.2)
    pn = dlg.tag_rules_panel

    # A
    texts = {w.text() for w in pn.findChildren(QCheckBox)} | {w.text() for w in pn.findChildren(QLabel)}
    chk(not set(FORMAT_VOCAB) & texts, "A 형식 줄에 고칠 수 없는 이름 글이 없다", str(set(FORMAT_VOCAB) & texts))
    chk(pn.fmt_name["공문"].text() == "공문서" and pn.fmt_name["기사"].text() == "기사",
        "A 글 상자에 지금 붙는 이름이 들어 있다", f"{pn.fmt_name['공문'].text()!r} {pn.fmt_name['기사'].text()!r}")
    chk(len(pn.cust_rows) == 1 and pn.cust_rows[0]["name"].text() == "견적서" and pn.cust_rows[0]["words"].text() == "견적",
        "A 더한 분류 줄 — 이름·찾을 낱말", str([(r['name'].text(), r['words'].text()) for r in pn.cust_rows]))

    # B
    chk(not dlg.btn_apply.isEnabled(), "B 준비 — 바꾸기 전 [적용] 꺼짐")
    QTest.mouseClick(pn.btn_fmt_add, Qt.MouseButton.LeftButton); app.processEvents()
    chk(len(pn.cust_rows) == 2 and not dlg.btn_apply.isEnabled(), "B [분류 더하기] — 새 줄(이름 넣기 전에는 바뀐 것 없음)",
        f"{len(pn.cust_rows)} {dlg.btn_apply.isEnabled()}")
    new = pn.cust_rows[-1]                     # 한글은 QTest.keyClicks 로 넣지 않는다(오프스크린에서 프로세스가 죽는다) — 코드는 textChanged 를 듣는다
    new["name"].setText("계약서")
    new["words"].setText("계약, contract")
    chk(dlg.btn_apply.isEnabled(), "B 이름을 넣으면 [적용] 켜짐")
    QTest.mouseClick(pn.btn_fmt_add, Qt.MouseButton.LeftButton); app.processEvents()      # 이름 없이 남긴 줄
    r = pn.rules()
    chk(r.get("format_custom") == [{"name": "견적서", "words": ["견적"]}, {"name": "계약서", "words": ["계약", "contract"]}],
        "B 규칙에 더한 분류 — 이름 빈 새 줄은 버린다", str(r.get("format_custom")))
    from PyQt6.QtWidgets import QPushButton
    gone = pn.cust_rows[-1]
    bx = [b for b in gone["w"].findChildren(QPushButton) if b.text() == "빼기"]
    if bx:
        QTest.mouseClick(bx[0], Qt.MouseButton.LeftButton); app.processEvents()
    chk(len(pn.cust_rows) == 2, "B [빼기] 로 줄이 빠진다")
    pn.cust_rows[0]["name"].setText("견적")                              # 더한 분류 이름 고치기
    pn.fmt_name["기사"].setText("신문기사")
    r = pn.rules()
    chk(r.get("alias", {}).get("견적서") == "견적" and r["alias"].get("기사") == "신문기사"
        and r["format_custom"][0]["name"] == "견적서", "B 이름 고치기는 표준 이름 → 붙일 이름(alias)", str(r))

    # C
    f = lambda stem, title="": auto_tag.Features(stem=stem, meta={"title": title}, page_count=1, aspect=0.7)
    rules = {"format_custom": [{"name": "견적서", "words": ["quotation", "견적"]}]}
    chk(auto_tag.classify_format(f("2026 견적_A사"), rules) == "견적서", "C 파일 이름의 찾을 낱말")
    chk(auto_tag.classify_format(f("doc1", "Quotation for pavement"), rules) == "견적서", "C PDF 제목의 낱말(대소문자 무시)")
    chk(auto_tag.classify_format(f("견적서 영수증"), rules) == "견적서", "C 내장 ① 명시어보다 먼저")
    chk(auto_tag.classify_format(f("doc1"), rules) is None, "C 낱말이 없으면 붙이지 않는다(본문은 안 본다)")
    chk(auto_tag.classify_format(f("견적서"), {**rules, "format_off": ["견적서"]}) is None, "C 끈 분류는 형식 없음")
    chk(auto_tag.classify_format(f("견적서"), {**rules, "alias": {"견적서": "견적"}}) == "견적", "C 이름 바꾸기")
    chk(auto_tag.axis_of("견적서", rules) == "형식" and auto_tag.axis_of("견적서", {}) == "주제", "C 축은 '형식'")

    # D
    n = TR.normalize({"format_custom": [{"name": "견적서", "words": ["견적", "x"]}, {"name": "견적서", "words": ["quote"]},
                                        {"name": " ", "words": ["a"]}, "bad"], "format_off": ["견적서", "없는분류"]})
    chk(n.get("format_custom") == [{"name": "견적서", "words": ["견적", "quote"]}] and n.get("format_off") == ["견적서"],
        "D 같은 이름은 합치고, 빈 이름·1글자 낱말·알 수 없는 끄기는 버린다", str(n))
    old = {"format_custom": [{"name": "견적서", "words": ["견적"]}, {"name": "보고서", "words": ["report"]}]}
    chk(TR.diff(old, {**old, "format_custom": old["format_custom"] + [{"name": "계약서", "words": []}]})["formats_on"] == ["계약서"],
        "D 더한 분류는 다시 판정 대상")
    chk(TR.diff(old, {"format_custom": [{"name": "견적서", "words": ["견적", "quote"]}, old["format_custom"][1]]})["formats_on"] == ["견적서"],
        "D 낱말을 바꾼 분류도 다시 판정")
    fn = TR.remapper(old, {"format_custom": [{"name": "견적서", "words": ["견적"]}], "alias": {"견적서": "견적"}})
    chk(fn("견적서") == "견적" and fn("보고서") == "보고서" and fn("영수증") == "영수증",
        "D 이름 바꾸기는 옮기고, 내장 이름의 분류를 빼도 내장 태그는 남는다", f"{fn('견적서')} {fn('보고서')}")
    fn2 = TR.remapper({**old, "alias": {"견적서": "견적"}}, {})
    chk(fn2("견적") is None and fn2("아스팔트") == "아스팔트", "D 뺀 분류의 자동 태그(바꾼 이름이어도)는 빠진다")

    # E — 실제 [적용]
    dlg.apply()
    job = mw.__dict__.get("_tag_rules_job")
    ends = []
    if job is not None:
        job.ended.connect(lambda k: ends.append(k))
        pump(lambda: bool(ends) or not job._workers, 20)
        pump(lambda: False, 0.3)
    saved = json.loads(rp.read_text(encoding="utf-8"))
    chk(saved.get("format_custom") == [{"name": "견적서", "words": ["견적"]}, {"name": "계약서", "words": ["계약", "contract"]}]
        and saved.get("alias") == {"공문": "공문서", "견적서": "견적", "기사": "신문기사"}, "E tag_rules.json 에 새 분류·이름", str(saved))
    chk(store.get_auto(A) == ["견적", "아스팔트"] and store.get_auto(B) == ["공문서"],
        "E 이미 붙은 자동 태그가 새 이름으로(사용자 결정 '새 이름으로 바꿈')", f"{store.get_auto(A)} {store.get_auto(B)}")
    dlg.reject()
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
