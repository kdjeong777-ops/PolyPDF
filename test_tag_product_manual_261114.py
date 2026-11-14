# -*- coding: utf-8 -*-
"""'설명서' → '제품설명서'(기술 설명서는 빼기) · '#' 메뉴 형식·속성은 옵션 단추 하나만 (태그 SOT §5.3·§5.8, 검색 SOT §5.1, 261114-14).

사용자 지시: "해시태그에서 형식과 속성은 옵션단추로 변경하여 각각 1개만 선택되도록 변경 · 설명서 -> 제품설명서 로 바꾸고, 기술 설명서는 제외".
사용자 결정: '#' 메뉴 거르기에서 · 속성은 거르기에서만 1개(파일에는 여러 속성) · 기술 낱말이면 빼기(이름 단서가 manual·guide·매뉴얼뿐이고
제품 단서가 없어도 빼기), 이미 붙은 자동 '설명서' 는 새 판정, 직접 붙인 '설명서' 는 이름만 '제품설명서' 로.
실제 auto_tag·TagStore·tag_rules·BookmarkTree 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 판정 — 이름 '사용설명서'·본문 제품 낱말·2단 접지·'설명서' 폴더 → 제품설명서, 이름·폴더에 기술 낱말(기술·technical·설계·시공·지침·편람)
   이거나 이름 단서가 약한 낱말(manual·guide·매뉴얼)뿐이면 아니다, 종류 이름에 '설명서' 는 없다
B. 옮기기 — 규칙 판(PDF_AUTO_V)이 낮으면 PDF 의 자동·직접·거절 '설명서' → '제품설명서', 끈 '설명서' → 끈 '제품설명서', 사진은 그대로
C. '#' 메뉴 — 형식·속성 묶음은 옵션 단추: 하나를 고르면 같은 묶음의 다른 것은 풀리고 검색 칸에 하나만, 다시 누르면 풀림, 주제는 체크 상자 그대로
"""
import os, sys, tempfile, shutil, time, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QCheckBox, QRadioButton, QWidgetAction
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_product_manual_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "제품설명서", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def pump(cond, timeout=10.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_prodman_"))


def mk(rel):
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    d = fitz.open(); d.new_page(); d.save(str(p)); d.close()
    return str(p)


try:
    from viewer import auto_tag as AT
    MAN = "제품설명서"

    def fmt(rel, body="", twocol=None):
        g = AT.Features(path=str(tmp / rel), stem=Path(rel).stem, page_count=4, struct_text=body, aspect=0.71, text_per_page=900)
        g.twocol = twocol
        return AT.classify_format(g, {})

    # A
    chk(MAN in AT.FORMAT_VOCAB and "설명서" not in AT.FORMAT_VOCAB, "A 종류 이름은 '제품설명서'('설명서' 없음)", str(AT.FORMAT_VOCAB))
    chk(fmt("x/LG 오븐 사용설명서.pdf") == MAN, "A 이름 '사용설명서' → 제품설명서", str(fmt("x/LG 오븐 사용설명서.pdf")))
    chk(fmt("x/a.pdf", "이 사용설명서를 잘 읽고") == MAN, "A 본문 제품 낱말 → 제품설명서")
    chk(fmt("11.1 설명서.회사/a.pdf") == MAN, "A 폴더 '설명서' → 제품설명서")
    chk(fmt("x/포장 기술 설명서.pdf") != MAN, "A 이름에 '기술' → 제품설명서 아님", str(fmt("x/포장 기술 설명서.pdf")))
    chk(fmt("x/Technical Manual.pdf") != MAN, "A 'Technical Manual' → 아님")
    chk(fmt("x/교량 설계 매뉴얼.pdf") != MAN, "A '설계 매뉴얼' → 아님")
    chk(fmt("x/CR1000 메뉴얼.pdf") != MAN, "A 이름 단서가 약한 낱말('메뉴얼')뿐이고 제품 단서 없음 → 아님", str(fmt("x/CR1000 메뉴얼.pdf")))
    chk(fmt("x/ROMDAS guide.pdf") != MAN, "A 'guide' 뿐 → 아님")
    chk(fmt("x/CR1000 메뉴얼.pdf", "user manual · 제품 사양") == MAN, "A 약한 이름 + 본문 제품 낱말 → 제품설명서")
    chk(fmt("시공 기술 설명서/a 설명서.pdf") != MAN, "A 상위 폴더에 기술 낱말 → 아님")
    chk(fmt("시공 기술 설명서/a.pdf", "취급설명서 품질보증") == MAN, "A 기술 폴더라도 본문 제품 낱말이 있으면 제품설명서")

    # B 옮기기
    from viewer import tag_rules as TR
    from viewer.tag_store import TagStore
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True; mw.show(); pump(lambda: False, 0.3)
    st = mw.bookmark_tree._tags
    pa, pb, pc, ph = mk("m/a.pdf"), mk("m/b.pdf"), mk("m/c.pdf"), str(tmp / "m" / "IMG_1.jpg")
    st.set_auto(pa, ["2020-01-01", "설명서"])
    st.set(pb, ["설명서", "가족"])
    st.set_auto(pc, ["보고서"]); st.reject(pc, ["설명서"])
    st.set(ph, ["설명서"])
    rp = TR.rules_path()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"pdf_auto_v": 2, "format_off": ["설명서", "논문"]}, ensure_ascii=False), encoding="utf-8")
    mw._start_autotag_scan = lambda *a, **k: None             # 옮기기만 본다(다시 판정은 따로)
    job = TR.migrate_if_needed(mw)
    chk(job is not None, "B 규칙 판이 낮으면 한 번 옮긴다")
    pump(lambda: "설명서" not in st.get_auto(pa) and "설명서" not in st.get_manual(pb), 10)
    pump(lambda: not job._workers, 10)
    chk(st.get_auto(pa) == ["2020-01-01"], "B 자동 '설명서' → '제품설명서' 로 옮기고, 끈 항목이라 빠진다", str(st.get(pa)))
    chk(st.get_manual(pb) == [MAN, "가족"], "B 직접 붙인 '설명서' → '제품설명서'", str(st.record(pb)))
    chk(MAN in st.get_rejected(pc) and "설명서" not in st.get_rejected(pc), "B 거절한 '설명서' → '제품설명서'", str(st.record(pc)))
    chk(st.get_manual(ph) == ["설명서"], "B 사진의 '설명서' 는 그대로(사진 종류는 사진 설정 몫)", str(st.get(ph)))
    r = json.loads(rp.read_text(encoding="utf-8"))
    chk(r.get("format_off") == [MAN, "논문"] and r.get("pdf_auto_v") == TR.PDF_AUTO_V, "B 끈 '설명서' → 끈 '제품설명서'·규칙 판 올림", str(r))
    mw.close()

    # C '#' 메뉴
    from viewer.widgets.bookmark_tree import BookmarkTree
    here = tmp / "docs"
    for n in ("a.pdf", "b.pdf", "c.pdf"):
        mk("docs/" + n)
    ts = TagStore(str(tmp / "tags.json"))
    ts.set(str(here / "a.pdf"), ["보고서", "한글", "아스팔트"])
    ts.set(str(here / "b.pdf"), ["발표자료", "영어", "포장"])
    ts.set(str(here / "c.pdf"), [MAN, "한글", "스캔문서"])
    bt = BookmarkTree(); bt.resize(320, 600); bt.show(); app.processEvents()
    bt._tags = ts
    bt.set_tree_view(False)
    bt.load_folder(str(here)); pump(lambda: len(list(bt._iter_file_nodes())) == 3, 5)

    def buttons():
        bt._rebuild_tag_menu()
        out = {}
        for act in bt._tag_menu.actions():
            if isinstance(act, QWidgetAction) and act.defaultWidget() is not None:
                for c in act.defaultWidget().findChildren((QCheckBox, QRadioButton)):
                    out[c.text().split()[0].lstrip("#")] = c
        return out
    b = buttons()
    chk(all(isinstance(b.get(t), QRadioButton) for t in ("보고서", "발표자료", MAN, "한글", "영어", "스캔문서")),
        "C 형식·속성은 옵션 단추", str({k: type(v).__name__ for k, v in b.items()}))
    chk(isinstance(b.get("아스팔트"), QCheckBox), "C 주제는 체크 상자 그대로")
    b["보고서"].click(); app.processEvents()
    b["발표자료"].click(); app.processEvents()
    toks = bt.search_edit.text().split()
    chk(toks == ["#발표자료"] and not b["보고서"].isChecked() and b["발표자료"].isChecked(), "C 형식 둘째를 고르면 첫째는 풀리고 하나만", str(toks))
    b["한글"].click(); app.processEvents()
    b["영어"].click(); app.processEvents()
    toks = bt.search_edit.text().split()
    chk(sorted(toks) == ["#발표자료", "#영어"], "C 속성도 하나만(형식은 그대로)", str(toks))
    b["아스팔트"].click(); app.processEvents(); b["포장"].click(); app.processEvents()
    chk({"#아스팔트", "#포장"} <= set(bt.search_edit.text().split()), "C 주제는 여럿", bt.search_edit.text())
    b["영어"].click(); app.processEvents()
    chk("#영어" not in bt.search_edit.text().split() and not b["영어"].isChecked(), "C 다시 누르면 풀린다", bt.search_edit.text())
    b2 = buttons()
    chk(b2["발표자료"].isChecked() and not b2["보고서"].isChecked(), "C 다시 열면 검색 칸대로 표시")
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
