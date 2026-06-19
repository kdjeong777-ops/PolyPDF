# -*- coding: utf-8 -*-
"""260606-11: 창별 읽기/mp3 버튼, OCR 제안, 단어장·책갈피 동시 생성(OCR재사용)."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow()

# 메뉴명 단축
check("2분할 메뉴명 '🗗 2분할 보기'", mw.act_split.text() == "🗗 2분할 보기")

# 창별 읽기 컨트롤: 두 창 모두 읽기 버튼+메뉴 존재, 각 창 툴바에 들어감
check("두 창 읽기 버튼 구성", len(mw._read_btns) == 2)
for i in range(2):
    tb = mw._mv[i]._toolbar
    grp = mw._read_btns[i][0].parent()   # ▶ 버튼은 그룹 위젯 안
    check(f"창{i} 읽기 그룹 툴바 포함", tb.indexOf(grp) >= 0)

# ReadAloud 타깃 전환
mw.act_split.setChecked(True)
mw.read_aloud.set_target(mw._mv[1], 1)
check("read_aloud 타깃=오른쪽창", mw.read_aloud._v is mw._mv[1])
mw.read_aloud.set_target(mw._mv[0], 0)
check("read_aloud 타깃=왼쪽창", mw.read_aloud._v is mw._mv[0])
mw.act_split.setChecked(False)

# 결합 빌드/제안 메서드 존재
for name in ("_action_build_study_and_bookmarks", "_maybe_offer_ocr",
             "_build_bookmarks_from_study", "_pane_read_toggle"):
    check(f"{name} 존재", callable(getattr(mw, name, None)))

# 동시 생성 시그널/메뉴
check("createStudyBookmarksRequested 시그널", hasattr(mw.bookmark_tree, "createStudyBookmarksRequested"))

# extract_headings_from_store: 디지털 PDF로 study build → store 재사용 헤딩 추출
from viewer.study.ocr_headings import extract_headings_from_store
from viewer.study.study_store import StudyStore, file_key_for
from viewer.study import vocab as study_vocab
import fitz
PDF = r"C:/Claude/MPDF/24 아스팔트콘크리트포장시콘크리트포장시공지침.pdf"
PDF = r"C:/Claude/MPDF/24 아스팔트콘크리트포장시공지침.pdf"
if os.path.exists(PDF):
    import tempfile
    db = os.path.join(tempfile.mkdtemp(), "s.db")
    store = StudyStore(db)
    fk = file_key_for(PDF)
    doc = fitz.open(PDF)
    from viewer.study import ocr as O
    # 앞 30p만 레이어/ocr 저장(빠르게)
    store.set_meta(fk, PDF, doc.page_count, "kor")
    for p in range(30):
        res = O.build_page(doc, p, lang="kor")
        store.save_page(fk, p, res["text"], dpi=res["dpi"], engine=res["engine"],
                        source=res["source"], conf=res["conf"], words=res["words"], lang="kor")
    doc.close()
    bms = extract_headings_from_store(store, fk, 30, use_font_auto=False)
    store.close()
    print("  store 헤딩:", [(b.page, b.title) for b in bms[:8]])
    check("store 재사용 헤딩 추출 동작(예외없음)", isinstance(bms, list))
else:
    print("  SKIP store 헤딩(PDF 없음)")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
