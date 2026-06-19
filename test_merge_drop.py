# -*- coding: utf-8 -*-
"""260606-21: 병합창 드롭 — 다이얼로그/리스트 어디 놓아도 우측 등록, 안내 오버레이."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def ck(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QMimeData, QUrl, QPointF
from PyQt6.QtGui import QDropEvent, QDragEnterEvent
app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.merge_dialog import MergeFilesDialog, _DropList, _has_pdf_urls

d = MergeFilesDialog([r"C:/x/a.pdf"], None, [])
ck("좌/우 리스트가 _DropList", isinstance(d.left, _DropList) and isinstance(d.right, _DropList))

# 합성 드롭(다이얼로그) → 우측 등록
mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(r"C:/x/dropped.pdf"),
                                  QUrl.fromLocalFile(r"C:/x/note.txt")])
ck("_has_pdf_urls", _has_pdf_urls(mime))
ev = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
before = d.right.count()
d.dropEvent(ev)
items = [it.get("path", "") for it in d.result_items()]
ck("드롭한 PDF가 우측 등록", any(p.endswith("dropped.pdf") for p in items), f"{items}")
ck("PDF 아닌 파일 무시", not any(p.endswith("note.txt") for p in items))

# 오버레이 표시/숨김
d._show_drop_overlay(True)
ck("오버레이 표시", not d._drop_overlay.isHidden())
d._show_drop_overlay(False)
ck("오버레이 숨김", d._drop_overlay.isHidden())

# _DropList: url 드롭은 ignore(부모로 전파)
dl = _DropList()
url_mime = QMimeData(); url_mime.setUrls([QUrl.fromLocalFile(r"C:/x/b.pdf")])
ee = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, url_mime,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
ee.accept()
dl.dropEvent(ee)
ck("_DropList url 드롭 ignore(전파)", not ee.isAccepted())

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
