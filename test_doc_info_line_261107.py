# -*- coding: utf-8 -*-
"""정보 한 줄은 본문 창 왼쪽 끝에서 — PDF·사진 같은 자리, 누르면 문서 정보 창 (261107-3, 마스터 §4.12 · 디자인 SOT §2.8.6.1).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
U. 용지 이름(`doc_info.paper_name`) — A4 세로·가로, Letter, 표준이 아니면 mm
A. PDF 1단: 정보 한 줄 x = 본문 창 왼쪽 끝(±1), 쪽 이동 왼쪽 끝 − INFO_GAP 앞에서 끝, 글 = 이름 · N쪽 · A4 세로 → 배경 끝나면 파일 크기
B. 짧은 임시 메시지는 그대로 보이고, 정보 줄 자리까지 닿는 긴 메시지가 떠 있는 동안만 숨김, 지우면 다시
C. 2단: 창마다 한 줄 — 각 창 왼쪽 끝, 각자 문서 이름
D. 좁으면 뒤에서 줄임('…' 없이) — 그려지는 글은 전체 글의 앞부분, 글(text)·툴팁은 전체
E. 사진 모드: 사진 정보 줄도 본문 창 왼쪽 끝(종전: 쪽 이동 오른쪽) · 사진 정보가 오기 전 PDF 줄이 남지 않는다 · PDF 모드로 오면 PDF 줄
F. 문서 정보 창(`show_doc_info`) — 모달 아님, 쪽 수·PDF 판·책갈피 수, 배경 끝나면 '읽는 중…' 이 없다 · 줄을 눌러도 같은 창
G. 메인 스레드에서 doc_info 가 파일을 열지 않는다(fitz.open)
"""
import os, sys, tempfile, threading, time, traceback
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_doc_info_line_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "정보 한 줄", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=10.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


def gx(w, mw):
    return w.mapTo(mw, QPoint(0, 0)).x()


import fitz
_main_opens = []
_orig_open = fitz.open


def _spy_open(*a, **k):
    if threading.current_thread() is threading.main_thread():
        st = traceback.extract_stack()
        if any(Path(f.filename).name in ("doc_info.py", "doc_info_controller.py") for f in st):
            _main_opens.append(str(a[:1]))
    return _orig_open(*a, **k)


fitz.open = _spy_open

tmp = Path(tempfile.mkdtemp(prefix="polypdf_doc_info_"))
try:
    def make_pdf(name, n, toc=False):
        p = tmp / name
        d = _orig_open()
        for i in range(n):
            pg = d.new_page()                             # 기본 = A4 세로
            pg.insert_text((72, 100), "Page %d text layer for info line test" % (i + 1))
        if toc:
            d.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 2]])
        d.set_metadata({"title": "Test Title", "author": "Tester"})
        d.save(str(p)); d.close()
        return str(p)

    pdf_a = make_pdf("가 문서.pdf", 3, toc=True)
    pdf_b = make_pdf("나 아주 긴 이름의 두 번째 문서 파일 이름입니다 정말로 길어요.pdf", 5)

    # U
    from viewer import doc_info
    chk(doc_info.paper_name(595.28, 841.89).startswith("A4") and doc_info.paper_name(595.28, 841.89).endswith("세로"),
        "U A4 세로", doc_info.paper_name(595.28, 841.89))
    chk(doc_info.paper_name(841.89, 595.28).endswith("가로"), "U A4 가로", doc_info.paper_name(841.89, 595.28))
    chk(doc_info.paper_name(612, 792).startswith("Letter"), "U Letter", doc_info.paper_name(612, 792))
    chk(doc_info.paper_name(300, 300) == "106 × 106 mm", "U 표준이 아니면 mm", doc_info.paper_name(300, 300))

    from viewer.app import MainWindow
    from viewer.widgets import page_nav_bar as pnb
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1600, 900); mw.show(); pump()
    mv0, mv1 = mw._mv
    host = mw.page_nav_host
    get_line = getattr(host, "info_line", None)
    chk(get_line is not None, "A 쪽 이동 칸에 창마다 정보 한 줄(info_line)")
    mw.open_pdf(Path(pdf_a)); pump()
    mv0.load_document(pdf_a); pump()
    b0 = get_line(0) if get_line else None

    # A
    if b0 is not None:
        chk(pump(lambda: b0.isVisible() and "KB" in b0.text()), "A PDF 정보 줄이 보이고 배경이 끝나면 파일 크기", repr(b0.text()))
        t = b0.text()
        chk(t.startswith("가 문서.pdf") and "3쪽" in t and "A4 세로" in t, "A 글 = 이름 · N쪽 · 지금 쪽 용지", repr(t))
        chk(abs(gx(b0, mw) - gx(mv0, mw)) <= 1, "A x = 본문 창 왼쪽 끝", "%d vs %d" % (gx(b0, mw), gx(mv0, mw)))
        chk(gx(b0, mw) + b0.width() <= gx(mv0.page_nav, mw) - pnb.INFO_GAP + 1, "A 쪽 이동 앞에서 끝난다",
            "%d %d" % (gx(b0, mw) + b0.width(), gx(mv0.page_nav, mw)))
        chk(t in b0.toolTip(), "A 툴팁에 전체 글")

        # B
        st = mw.status
        st.showMessage("짧음", 5000); pump()
        chk(b0.isVisible(), "B 짧은 메시지는 정보 줄과 함께 보인다")
        st.showMessage("아주 긴 진행 메시지 " * 30, 5000); pump()
        chk(not b0.isVisible(), "B 정보 줄 자리까지 닿는 메시지가 떠 있는 동안 숨김")
        st.clearMessage(); pump()
        chk(b0.isVisible() and abs(gx(b0, mw) - gx(mv0, mw)) <= 1, "B 메시지를 지우면 다시 그 자리")

        # F
        mw.show_doc_info()
        dlg = getattr(mw, "_doc_info_dlg", None)
        chk(dlg is not None and dlg.isVisible() and not dlg.isModal(), "F 문서 정보 창(모달 아님)")
        if dlg is not None:
            rows = {dlg._table.item(r, 0).text(): dlg._table.item(r, 1).text() for r in range(dlg._table.rowCount())}
            chk(rows.get("쪽 수") == "3" and rows.get("PDF 판", "").startswith("PDF") and rows.get("책갈피 수") == "2"
                and rows.get("제목") == "Test Title" and rows.get("작성자") == "Tester",
                "F 행 — 쪽 수·PDF 판·책갈피 수·제목·작성자", str(rows))
            chk("읽는 중…" not in rows.values() and rows.get("글자층", "").startswith("있는 쪽 3"),
                "F 배경이 끝나 '읽는 중…' 이 없고 글자층 쪽 수", str(rows))
            dlg.close(); pump()
            b0.click(); pump()
            chk(dlg.isVisible(), "F 정보 줄을 누르면 같은 창")
            dlg.close()

        # C
        mw.act_split.setChecked(True); pump()
        mv1.load_document(pdf_b); pump()
        b1 = get_line(1)
        chk(pump(lambda: b1.isVisible() and b1.text().startswith("나 ")), "C 2단 오른쪽 창 정보 줄", repr(b1.text()))
        chk(abs(gx(b1, mw) - gx(mv1, mw)) <= 1 and abs(gx(b0, mw) - gx(mv0, mw)) <= 1,
            "C 2단 창마다 그 창 왼쪽 끝", "%d/%d %d/%d" % (gx(b0, mw), gx(mv0, mw), gx(b1, mw), gx(mv1, mw)))
        chk(b0.text().startswith("가 ") and b1.text().startswith("나 "), "C 창마다 자기 문서")

        # D
        mw.resize(1100, 900); pump()
        sh = b1.shown_text()
        chk(b1.isVisible() and b1.width() < b1.sizeHint().width() and b1.text().startswith(sh) and len(sh) < len(b1.text())
            and "…" not in sh, "D 좁으면 뒤에서 줄임('…' 없이), 글은 전체", "%r / %r" % (sh, b1.text()))
        chk(b1.text() in b1.toolTip(), "D 툴팁에 전체 글")
        chk(gx(b1, mw) + b1.width() <= gx(mv1.page_nav, mw) - pnb.INFO_GAP + 1, "D 쪽 이동이 먼저")
        mw.act_split.setChecked(False); pump()
        chk(not b1.isVisible(), "D 2단을 끄면 오른쪽 창 줄도 숨는다")
        mw.resize(1600, 900); pump()

    # E — 사진 모드
    from PIL import Image
    pdir = tmp / "photos"; pdir.mkdir()
    Image.new("RGB", (800, 600), (200, 60, 60)).save(pdir / "사진 하나.jpg", "JPEG")
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump()
    if b0 is not None:
        chk(not (b0.isVisible() and b0.text().startswith("가 ")), "E 사진 모드로 오면 PDF 정보 줄이 남지 않는다", repr(b0.text()))
    mw.open_folder(pdir)
    bt = mw.bookmark_tree
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 1)
    lst = mw._photo_tree_list()
    mw._on_bookmark_activated(lst[0], 0); pump()
    pb = getattr(mw, "_photo_info_btn", None)
    chk(pump(lambda: pb is not None and pb.isVisible() and "800 × 600" in pb.text()), "E 사진 정보 줄", repr(pb.text() if pb else None))
    if pb is not None:
        chk(abs(gx(pb, mw) - gx(mw.main_view, mw)) <= 1, "E 사진 정보 줄 x = 본문 창 왼쪽 끝(종전 쪽 이동 오른쪽)",
            "%d vs %d" % (gx(pb, mw), gx(mw.main_view, mw)))
    mw._set_photo_mode(False); pump()
    mw.open_pdf(Path(pdf_a)); pump()
    mv0.load_document(pdf_a); pump()
    if b0 is not None:
        chk(pump(lambda: b0.isVisible() and b0.text().startswith("가 ")), "E PDF 모드로 오면 PDF 정보 줄", repr(b0.text()))

    # G
    chk(not _main_opens, "G 메인 스레드에서 doc_info 가 파일을 열지 않는다", str(_main_opens))
    mw.close()
except Exception:
    traceback.print_exc()
    fails.append("예외")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
