# -*- coding: utf-8 -*-
"""261012-6: '선과 텍스트 입력 설정' 글쓰기 탭 — 고친 뒤 [저장] 하지 않고 [확인] 을 누르면 묻는다 (마스터 §4.5.0).

A. 고친 것이 없으면 묻지 않고 닫힌다
B. 글자 크기를 바꾸고 [확인](실제 단추) → 묻는다 · [취소] 면 창에 남고 글쓰기 탭으로
C. [저장하지 않고 닫기] → 닫히고 스타일은 그대로
D. [저장하고 닫기] → 고른 스타일에 들어가 닫힌다 · [저장] 뒤 [확인] 은 묻지 않는다
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialogButtonBox

app = QApplication.instance() or QApplication(sys.argv[:1])
from viewer.widgets.line_text_settings_dialog import LineTextSettingsDialog

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


PENS = [{"color": "#ff0000", "width": 3, "alpha": 100}] * 5
STYLES = [{"name": "본문", "color": "#111111", "size_pt": 11.0, "bold": False},
          {"name": "제목", "color": "#111111", "size_pt": 18.0, "bold": True}]
asked = []
pick = {"t": None}


def _exec(box):
    asked.append(box.text())
    box._pick = next((b for b in box.buttons() if pick["t"] and b.text() == pick["t"]), None)
    return 0


QMessageBox.exec = _exec
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)   # 같은 이름 스타일 덮어쓰기 확인
QMessageBox.clickedButton = lambda box: getattr(box, "_pick", None)


def ok_button(dlg):
    bb = dlg.findChild(QDialogButtonBox)
    return bb.button(QDialogButtonBox.StandardButton.Ok)


try:
    d = LineTextSettingsDialog(PENS, [12, 30], 35, STYLES)
    d.show(); app.processEvents()
    ok_button(d).click(); app.processEvents()
    chk(not asked and d.result() == d.DialogCode.Accepted, "A 고친 것이 없으면 묻지 않고 닫힌다")

    d = LineTextSettingsDialog(PENS, [12, 30], 35, STYLES)
    d.show(); app.processEvents()
    d._tabs.setCurrentIndex(0)
    d._sp_size.setValue(14.0)
    asked.clear(); pick["t"] = "취소"
    ok_button(d).click(); app.processEvents()
    chk(asked and d.isVisible() and d._tabs.currentIndex() == 1,
        "B 크기를 바꾸고 [확인] → 묻는다 · [취소] 면 창에 남고 글쓰기 탭으로", str(asked[:1]))
    pick["t"] = "저장하지 않고 닫기"
    ok_button(d).click(); app.processEvents()
    chk(d.result() == d.DialogCode.Accepted and d.result_styles()[0]["size_pt"] == 11.0,
        "C [저장하지 않고 닫기] → 닫히고 스타일은 그대로")

    d = LineTextSettingsDialog(PENS, [12, 30], 35, STYLES)
    d.show(); app.processEvents()
    d._sp_size.setValue(15.0)
    pick["t"] = "저장하고 닫기"
    ok_button(d).click(); app.processEvents()
    chk(d.result() == d.DialogCode.Accepted and d.result_styles()[0]["size_pt"] == 15.0,
        "D1 [저장하고 닫기] → 고른 스타일(본문)에 들어가 닫힌다", str(d.result_styles()[0]))
    d = LineTextSettingsDialog(PENS, [12, 30], 35, STYLES)
    d.show(); app.processEvents()
    d._sp_size.setValue(16.0)
    d._style_save()
    asked.clear()
    ok_button(d).click(); app.processEvents()
    chk(not asked and d.result_styles()[0]["size_pt"] == 16.0, "D2 [저장] 뒤 [확인] 은 묻지 않는다")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
