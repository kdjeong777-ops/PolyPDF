# -*- coding: utf-8 -*-
"""책갈피창 [저장] 은 xref 가 상한 PDF 에도 책갈피를 쓴다 — 마스터 §4.7.13.

사용자 보고(1.1.0-beta.2): 일괄 OCR 뒤 [저장] 이 'Could not read Boolean object' 로 실패(24 아스팔트 시공지침 598쪽).
그 파일 끝의 증분 갱신은 xref 구역이 비어 있다(`xref\\r\\ntrailer`) — PyMuPDF 는 열지만 pypdf 는 'trailer' 를
불(Boolean) 값으로 읽다 실패했다. 책갈피 쓰기만 아직 pypdf(`pdf_bookmarker.apply_bookmarks_to_pdf`)였다.
실제 처리기(`BookmarkTree._op_save`, 앱의 `_finalize_save`·`_file_op_bg` 연결 그대로)로:
  A  그런 PDF 에서 [저장] 이 '저장 실패' 창 없이 끝나고 책갈피가 PDF 에 써진다(수정 전 코드는 실패 창)
  B  (재발 방지) 뷰어 코드는 pypdf 로 PDF 를 열지 않는다 — 벤더 사본의 옛 쓰개 `pdf_writer.py` 밖에서 `pypdf` import 가 없다
"""
import os, re, sys, shutil, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_bm_xref_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


import fitz
from test_fixtures import text_pdf
from viewer.app import MainWindow
from viewer.history import HistoryItem

root = Path(tempfile.mkdtemp(prefix="polypdf_bmxref_"))
pdf = root / "doc.pdf"
# 고전 xref 표로 다시 쓴 뒤 빈 xref 구역의 증분 갱신을 붙인다(그 파일의 끝과 같은 꼴)
d = fitz.open(text_pdf()); d.save(str(pdf), garbage=1); d.close()
b = pdf.read_bytes()
prev = int(re.findall(rb"startxref\s+(\d+)", b)[-1])
trailer = re.findall(rb"trailer\s*(<<.*?>>)\s*startxref", b, re.S)[-1]
root_ref = re.search(rb"/Root\s+(\d+ \d+ R)", trailer).group(1)
size = re.search(rb"/Size\s+(\d+)", trailer).group(1)
off = len(b)
b += (b"xref\r\ntrailer\r\n<</Root " + root_ref + b" /Size " + size + b" /Prev %d>>\r\nstartxref\r\n%d\r\n%%%%EOF\r\n"
      % (prev, off))
pdf.write_bytes(b)
d = fitz.open(str(pdf)); n_pages = d.page_count; d.close()
chk(n_pages > 4, "준비: PyMuPDF 는 그 PDF 를 연다", n_pages)
try:
    from pypdf import PdfReader
    PdfReader(str(pdf)); pypdf_fails = False
except Exception as e:
    pypdf_fails = "Boolean" in str(e)
chk(pypdf_fails, "준비: pypdf 는 그 PDF 를 'Could not read Boolean object' 로 못 읽는다(사용자 파일과 같은 꼴)")

warned = []
_real_warn = QMessageBox.warning
QMessageBox.warning = staticmethod(lambda *a, **k: (warned.append(a[1:3]), QMessageBox.StandardButton.Ok)[1])
mw = MainWindow(); mw.show(); app.processEvents()
try:
    mw.bookmark_tree.load_pdf_files([str(pdf)]); app.processEvents()
    mw._load_main(HistoryItem(str(pdf), 0, "", "bookmark")); app.processEvents(); QTest.qWait(200)
    bt = mw.bookmark_tree
    bt.btn_edit.setChecked(True); app.processEvents()
    bms = [("목차", 2, 0), ("가 장", 3, 0), ("나 절", 4, 1)]
    chk(bt.replace_file_bookmarks(str(pdf), bms), "준비: 책갈피창에 '저장 안 됨' 으로 넣었다")
    bt._op_save(str(pdf))
    for _ in range(40):
        app.processEvents(); QTest.qWait(50)
    chk(not warned, "A 저장 실패 창이 뜨지 않는다", warned)
    d = fitz.open(str(pdf)); toc = d.get_toc(); d.close()
    chk([t[1] for t in toc] == ["목차", "가 장", "나 절"] and [t[0] for t in toc] == [1, 1, 2],
        "A 책갈피가 PDF 에 써졌다(레벨까지)", toc)
finally:
    QMessageBox.warning = _real_warn
    mw._skip_save_on_close = True
    mw.close()
    shutil.rmtree(root, ignore_errors=True)

# B — pypdf 는 xref 가 상한 PDF 를 못 읽는다. 뷰어 코드에서 PDF 를 여는 일은 PyMuPDF 로만
bad = []
vdir = Path(HERE) / "viewer"
for p in vdir.rglob("*.py"):
    rel = p.relative_to(vdir).as_posix()
    if rel == "_vendor/pdf_bookmarker/pdf_writer.py":      # 옛 쓰개 — 앱은 부르지 않는다(bookmarker_bridge.apply_to_pdf)
        continue
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if re.match(r"\s*(from\s+pypdf\b|import\s+pypdf\b)", line):
            bad.append("%s:%d" % (rel, i))
chk(not bad, "B 뷰어 코드에 pypdf import 가 없다(PDF 는 PyMuPDF 로)", bad)
import inspect
from viewer import bookmarker_bridge
chk("apply_bookmarks_to_pdf(" not in inspect.getsource(bookmarker_bridge.apply_to_pdf),
    "B 책갈피 쓰기(`bookmarker_bridge.apply_to_pdf`)는 pypdf 쓰개를 부르지 않는다")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
