# -*- coding: utf-8 -*-
"""261008-1: 스크린샷 창 — '클립보드로 복사' 이름 · '클립보드 가져오기' · PDF 저장 뒤 불러오기 (스크린샷 SOT §7·§8·§9).

사용자 요청:
  - 'PDF저장' 버튼 실행 시 저장 후 해당 창 불러들일지 여부 확인 창 띄움
  - '클립보드 저장' 버튼 → '클립보드로 복사'
  - '클립보드 가져오기' 버튼 추가 (사용자 결정: 그림 + 그림 파일)

A. 단추 이름·순서, 단축키 목록 이름
B. 클립보드 가져오기 — 그림 데이터 1장 / 탐색기 그림 파일 여러 개(파일이 우선) / 없으면 알림
C. PDF 저장 → '이 창에 불러올까요?' 예 → 책갈피창 목록에 들어가고 본문에 열린다 · 아니오 → 그대로
D. 종료할 때의 저장(§9)은 묻지 않는다
"""
import os, sys, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, QMimeData, QUrl
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=10, ms=20):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


root = Path(tempfile.mkdtemp(prefix="polypdf_shotclip_"))
try:
    infos = []
    QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else ""))
    QMessageBox.warning = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else ""))
    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    strip = mw.shot_strip

    # ── A ────────────────────────────────────────────────────────────
    chk("클립보드로 복사" in mw.btn_clip.text(), "A '클립보드 저장' → '클립보드로 복사'", mw.btn_clip.text())
    chk(hasattr(mw, "btn_clip_in") and "클립보드 가져오기" in mw.btn_clip_in.text(),
        "A '클립보드 가져오기' 단추가 있다")
    order = [w for w in strip._extra_widgets]
    chk(order == [mw.btn_clip_in, mw.btn_clip, mw.btn_save_pdf], "A 순서: 가져오기 · 복사 · PDF 저장")
    from viewer import app as appmod
    import inspect
    chk('("clipboard_save", (tr("클립보드로 복사")' in inspect.getsource(appmod), "A 단축키 목록 이름도 같다")

    # ── B. 클립보드 가져오기 ──────────────────────────────────────────
    cb = QApplication.clipboard()
    n0 = strip.list.count()
    img = QImage(120, 80, QImage.Format.Format_RGB32); img.fill(QColor(200, 30, 30))
    cb.setImage(img); spin(2)
    mw.btn_clip_in.click(); spin(3)
    chk(strip.list.count() == n0 + 1, "B 그림 데이터 1장 → 카드 1장", str(strip.list.count()))
    p_last = strip.all_paths()[-1]
    chk(Path(p_last).exists() and QImage(p_last).width() == 120, "B 카드는 임시 폴더 PNG(같은 크기)", p_last)

    files = []
    for i, c in enumerate((QColor(0, 120, 0), QColor(0, 0, 160))):
        f = root / f"그림{i}.png"
        im = QImage(64 + i, 40, QImage.Format.Format_RGB32); im.fill(c); im.save(str(f)); files.append(f)
    (root / "메모.txt").write_text("x", encoding="utf-8")
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(f)) for f in files] + [QUrl.fromLocalFile(str(root / "메모.txt"))])
    md.setImageData(img)                       # 탐색기처럼 그림 데이터(아이콘)가 함께 실려도
    cb.setMimeData(md); spin(2)
    n1 = strip.list.count()
    mw._on_clipboard_import(); spin(3)
    ws = [QImage(p).width() for p in strip.all_paths()[n1:]]
    chk(strip.list.count() == n1 + 2 and ws == [64, 65],
        "B 탐색기 그림 파일 여러 개 → 파일마다 카드(그림 데이터·그림 아닌 파일은 빼고)", str(ws))
    chk(all(Path(p).parent != root for p in strip.all_paths()[n1:]),
        "B 원본 파일을 가리키지 않고 복사본을 쓴다(원본을 옮겨도 카드가 깨지지 않게)")
    cb.clear(); spin(2)
    infos.clear()
    n2 = strip.list.count()
    mw._on_clipboard_import(); spin(2)
    chk(strip.list.count() == n2 and infos and "가져올 그림이 없습니다" in infos[-1],
        "B 클립보드가 비면 알리고 아무것도 넣지 않는다", str(infos[-1:]))

    # ── C. PDF 저장 → 불러오기 ───────────────────────────────────────
    from viewer.widgets import screenshot_pdf_dialog as spd
    spd.ScreenshotPdfDialog.exec = lambda self: QDialog.DialogCode.Accepted
    out = root / "모음.pdf"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out), "PDF (*.pdf)"))
    asked = []
    ans = {"v": QMessageBox.StandardButton.No}
    QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), ans["v"])[1])
    before = mw.main_view.current_file()
    ok = mw.action_save_screenshot_pdf(); spin(5)
    chk(ok and out.exists(), "C 저장된다")
    chk(len(asked) == 1 and "이 창에 불러올까요" in asked[0], "C 저장 뒤 '이 창에 불러올까요?' 를 묻는다", str(asked))
    chk(mw.main_view.current_file() == before, "C 아니오 → 아무것도 열지 않는다")
    out.unlink()
    asked.clear(); ans["v"] = QMessageBox.StandardButton.Yes
    mw.btn_save_pdf.click(); spin(15)                 # 실제 단추(clicked(bool) 이 인자를 넣는 길)
    chk(len(asked) == 1, "C 단추로 저장해도 묻는다", str(asked))
    cur = mw.main_view.current_file()
    chk(cur and Path(cur) == out, "C 예 → 저장한 PDF 가 본문에 열린다", str(cur))
    bt = mw.bookmark_tree
    chk(any(Path(p) == out for p in bt.all_file_paths()), "C 책갈피창 목록에도 들어간다", str(bt.all_file_paths()))
    with fitz.open(str(out)) as d:
        chk(d.page_count == strip.list.count(), "C 쪽 수 = 카드 수", f"{d.page_count} vs {strip.list.count()}")

    # ── D. 종료할 때의 저장은 묻지 않는다 ──────────────────────────────
    out.unlink() if out.exists() and mw.main_view.current_file() != str(out) else None
    out2 = root / "종료.pdf"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out2), "PDF (*.pdf)"))
    asked.clear()
    ok2 = mw.action_save_screenshot_pdf(ask_open=False); spin(3)
    chk(ok2 and out2.exists() and not asked, "D 종료 때 저장(ask_open=False)은 불러올지 묻지 않는다", str(asked))
    src = inspect.getsource(appmod.MainWindow)
    chk("self.action_save_screenshot_pdf(ask_open=False)" in src, "D 종료 확인이 ask_open=False 로 부른다")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
