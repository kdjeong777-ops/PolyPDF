# -*- coding: utf-8 -*-
"""260611-17: X(종료) 시 편집모드면 저장/저장 안 함/취소 선택 및 동작."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QCloseEvent

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_close_"))
d = fitz.open(); d.new_page(width=400, height=600).insert_text((40, 80), "p")
d.save(str(tmp / "T.pdf")); d.close()
(tmp / "bookmarks.json").write_text(
    json.dumps({"version": 1, "bookmarks": [{"title": "T", "file": "T.pdf", "children": []}]}),
    encoding="utf-8")

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(1000, 700); mw.show(); app.processEvents()
mw.open_folder(tmp); app.processEvents()
mw._on_bookmark_activated(mw.bookmark_tree.ordered_pdf_files()[0], 0); app.processEvents()

chk(hasattr(mw, "_confirm_close_edit"), "_confirm_close_edit 존재")

# 1) 편집모드 아님 → 다이얼로그 없이 종료 허용
chk(mw._confirm_close_edit() is True, "비편집 상태 → 종료 그대로 허용")

# 편집모드 진입 + 미저장 변경 모의
mw.bookmark_tree._edit_mode = True
mw._edit_snap = {"pm": None, "hl": None}
mw._edit_dirty = True

# 2) 편집모드 + dirty + 취소 → 종료 거부
calls = {"commit": 0, "save": 0}
mw._commit_edit = lambda: calls.__setitem__("commit", calls["commit"] + 1)
mw.bookmark_tree._dirty = False

def fake_exec_cancel(self):
    self.setResult(0)
    # clickedButton 흉내: 취소 버튼을 누른 것으로
    for b in self.buttons():
        if b.text() == "취소":
            self._clicked = b
    return 0

orig_exec = QMessageBox.exec
orig_clicked = QMessageBox.clickedButton
QMessageBox.exec = lambda self: setattr(self, "_clicked",
    next(b for b in self.buttons() if b.text() == "취소")) or 0
QMessageBox.clickedButton = lambda self: self._clicked
chk(mw._confirm_close_edit() is False, "편집+dirty+취소 → 종료 거부")

# 3) 저장 후 종료 → _commit_edit 호출 + 종료 허용
QMessageBox.exec = lambda self: setattr(self, "_clicked",
    next(b for b in self.buttons() if b.text() == "저장 후 종료")) or 0
mw._edit_dirty = True
r = mw._confirm_close_edit()
chk(r is True and calls["commit"] == 1, "저장 후 종료 → commit 호출+허용", str(calls))
chk(mw._edit_dirty is False, "저장 후 dirty 해제")

# 4) 저장 안 하고 종료 → commit 미호출 + 허용 + dirty 해제
QMessageBox.exec = lambda self: setattr(self, "_clicked",
    next(b for b in self.buttons() if b.text() == "저장 안 하고 종료")) or 0
mw._edit_dirty = True
calls["commit"] = 0
r = mw._confirm_close_edit()
chk(r is True and calls["commit"] == 0, "저장 안 하고 종료 → commit 미호출+허용", str(calls))
chk(mw._edit_dirty is False, "미저장 종료 후 dirty 해제(폐기)")

QMessageBox.exec = orig_exec
QMessageBox.clickedButton = orig_clicked

# 5) closeEvent 연동 — 취소 시 event.ignore()
mw.bookmark_tree._edit_mode = True
mw._edit_dirty = True
mw._confirm_close_edit = lambda: False
ev = QCloseEvent(); ev.accept()
mw.closeEvent(ev)
chk(not ev.isAccepted(), "closeEvent: 취소 → ignore(창 유지)")

mw._confirm_close_edit = lambda: True
ev2 = QCloseEvent(); ev2.accept()
mw.closeEvent(ev2)
chk(ev2.isAccepted(), "closeEvent: 진행 → accept(종료)")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
