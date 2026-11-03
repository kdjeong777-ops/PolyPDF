# -*- coding: utf-8 -*-
"""사진 모드 선행 보호 (사진 보기 SOT 4.14 G1·G2·G5, 261103-19·-20).

지금은 책갈피창에 PDF 만 보여 드러나지 않지만, 사진 경로가 앱 안을 돌면 원본 사진을 잃는 빈틈 —
실제 함수를 불러 본다(마스터 §14.7.2 — 헬퍼가 아니라 실제 길).

G1. 원본 저장 한 길 `_finalize_save_place`: 원본이 JPG 면 덮어쓰지 않고 새 이름(.pdf)으로 — JPG 바이트 그대로
    · 어떤 길로든 PDF 아닌 파일을 덮어쓰게 되면 SaveCancelled(산출물 지움)
    · `_page_edits_dirty`: 사진의 크롭 대기값을 'PDF 쪽 편집 저장' 으로 넘기지 않는다
G2. 색인은 PDF 만: `PdfIndex.index_file(jpg)` 는 행을 만들지 않는다(종전엔 fitz 가 JPG 를 1쪽 문서로 열어 색인),
    `IndexWorker(files=[jpg])` 는 할 일이 없다(빈 목록이 폴더 전체 색인으로 번지지 않게), `_index_files([jpg])` 는 작업을 띄우지 않는다
G5. 책갈피창 목록 조사 `_probe_pdf(jpg)` 는 파일을 열지 않고 넷 값을 돌려준다
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QColor
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_guard_"))
try:
    jpg = tmp / "현장 사진.jpg"
    im = QImage(320, 200, QImage.Format.Format_RGB32)
    im.fill(QColor("#3070c0"))
    assert im.save(str(jpg), "JPG")
    jpg_bytes = jpg.read_bytes()
    import fitz
    pdf = tmp / "문서.pdf"
    d = fitz.open(); d.new_page().insert_text((72, 72), "hello"); d.save(str(pdf)); d.close()

    from viewer.app import MainWindow
    from viewer.file_overwrite import SaveCancelled

    # ── G1 ────────────────────────────────────────────────────────────
    class Stub:
        _force_save_as = False

        def __init__(self):
            self.closed = 0

        def _file_op_bg(self, fn, label=""):
            try:
                fn()
            except Exception as e:
                return e
            return None

        def _close_main_view_doc(self):
            self.closed += 1

        def _sign_guard(self, dst):
            return "ok"

    s = Stub()
    s._edit_save_dst = lambda src, sh, ask=True: MainWindow._edit_save_dst(s, src, sh, ask=False)
    produced = tmp / "out.tmp.pdf"
    shutil.copy(pdf, produced)
    try:
        final = MainWindow._finalize_save_place(s, str(jpg), str(produced), shift=False)
    except Exception as e:
        final = "ERR %r" % e
    chk(jpg.read_bytes() == jpg_bytes, "G1 원본 JPG 바이트 그대로(덮어쓰지 않음)")
    chk(str(final).lower().endswith(".pdf") and Path(final).exists() and Path(final) != jpg,
        "G1 새 이름 PDF 로 저장", str(final))

    s2 = Stub()
    s2._edit_save_dst = lambda src, sh, ask=True: (Path(jpg), True)     # 어떤 길로 원본 자리가 골라져도
    produced2 = tmp / "out2.tmp.pdf"
    shutil.copy(pdf, produced2)
    raised = False
    try:
        MainWindow._finalize_save_place(s2, str(jpg), str(produced2), shift=True)
    except SaveCancelled:
        raised = True
    except Exception:
        pass
    chk(raised and jpg.read_bytes() == jpg_bytes and not produced2.exists(),
        "G1 PDF 아닌 파일 덮어쓰기는 SaveCancelled — 산출물 지우고 원본 그대로")

    from viewer import page_crop
    page_crop.set_pending(str(jpg), {0: [5, 5, 5, 5]})

    class MV:
        def current_file(self):
            return str(jpg)

    class PT:
        _doc = None

        def is_page_dirty(self):
            return False

    s3 = Stub(); s3.main_view = MV(); s3.page_thumbs = PT()
    chk(MainWindow._page_edits_dirty(s3) is False, "G1 사진의 크롭 대기값은 PDF 쪽 편집 저장으로 넘기지 않는다")
    page_crop.clear_pending(str(jpg)) if hasattr(page_crop, "clear_pending") else None

    # ── G2 ────────────────────────────────────────────────────────────
    from viewer.indexer import PdfIndex
    db = tmp / "index.db"
    idx = PdfIndex(db)
    try:
        idx.index_file(jpg)
        idx.index_file(pdf)
        rows = {Path(r[0]).name for r in idx.conn.execute("SELECT path FROM files")}
    finally:
        idx.close()
    chk(jpg.name not in rows, "G2 index_file(jpg) 는 색인 행을 만들지 않는다", str(rows))
    chk(pdf.name in rows, "G2 PDF 는 그대로 색인")

    from viewer.workers import IndexWorker
    w = IndexWorker(db, tmp, files=[jpg])
    chk(w._cancel and w.files == [], "G2 IndexWorker(files=[jpg]) — 할 일 없음(폴더 전체로 번지지 않음)")
    w2 = IndexWorker(db, tmp, files=[jpg, pdf])
    chk(w2.files == [pdf] and not w2._cancel, "G2 IndexWorker 는 PDF 만 남긴다")

    class Prog:
        def setVisible(self, v): pass
        def setRange(self, a, b): pass

    started = []
    s4 = Stub(); s4.progress = Prog(); s4._start_index_worker = lambda wk: started.append(wk)
    s4._db_path = db
    s4._on_index_progress = lambda *a: None
    s4._on_index_finished = lambda *a: None
    s4.status = type("St", (), {"showMessage": lambda self, *a: None})()
    MainWindow._index_files(s4, [str(jpg)])
    chk(not started, "G2 _index_files([jpg]) 는 색인 작업을 띄우지 않는다")
    MainWindow._index_files(s4, [str(jpg), str(pdf)])
    chk(len(started) == 1 and [p.name for p in started[0].files] == [pdf.name], "G2 _index_files 는 PDF 만 넘긴다")

    # ── G5 ────────────────────────────────────────────────────────────
    from viewer.widgets import bookmark_tree as bt
    opened = []
    real_open = bt.fitz.open

    def spy(*a, **k):
        opened.append(a[0] if a else None)
        return real_open(*a, **k)

    bt.fitz.open = spy
    try:
        class TS:
            pass
        r = bt.BookmarkTree._probe_pdf(TS(), jpg)
    finally:
        bt.fitz.open = real_open
    chk(not opened, "G5 _probe_pdf(jpg) 는 파일을 열지 않는다")
    chk(isinstance(r, tuple) and len(r) == 4, "G5 돌려주는 값은 넷(부르는 쪽이 넷으로 푼다)", str(r))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
