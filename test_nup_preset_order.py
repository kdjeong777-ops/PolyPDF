# -*- coding: utf-8 -*-
"""261008-4: 다단 생성 설정 — 스타일 목록 순서 바꾸기 · 고쳐 저장해도 자리 유지 (마스터 §11.10).

사용자 요청: "다단 생성 설정의 스타일의 목록 순서를 바꿀 수 있도록 수정해. 현재는 만든 순서로 되어 있는데,
기존 내용을 수정시 밑으로 바뀌어서 사용하기 어려워"

A. 같은 이름으로 다시 저장하면 **그 자리**에 덮어쓴다(종전: 맨 아래로) · 새 이름은 끝에
B. ▲▼ 로 고른 스타일이 한 칸씩 옮겨지고 설정 파일(prefs)에 남는다 · 옮긴 스타일이 계속 골라져 있다
C. 맨 위에서 ▲, 맨 아래에서 ▼ 는 꺼진다 · 순서 기능이 없는 창(preset_api 없음)은 둘 다 꺼진다
D. 옮겨도 창의 설정 값은 바뀌지 않는다(순서만)
"""
import os, sys, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)

from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


try:
    from viewer.app import MainWindow
    from viewer.widgets.twoup_dialog import TwoUpSettingsDialog
    mw = MainWindow()
    names = lambda: [p.get("name") for p in mw._prefs.get("merge_presets") or []]
    mw._prefs["merge_presets"] = [{"name": n, "nup": 2} for n in ("가", "나", "다", "라")]
    api = mw._merge_preset_api()

    # ── A ──
    api["save_preset"]("나", {"nup": 4})
    chk(names() == ["가", "나", "다", "라"], "A 같은 이름 다시 저장 → 그 자리(종전: 맨 아래로)", str(names()))
    chk(mw._prefs["merge_presets"][1].get("nup") == 4, "A 내용은 새 값으로 덮어쓴다")
    api["save_preset"]("마", {"nup": 2})
    chk(names()[-1] == "마", "A 새 이름은 끝에", str(names()))

    # 창의 실제 '저장…' 단추 길(이름 묻기 → 같은 이름이면 업데이트 확인)
    QInputDialog.getText = staticmethod(lambda *a, **k: ("다", True))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    dlg = TwoUpSettingsDialog({"nup": 6}, None, preset_api=api)
    dlg.cmb_preset.setCurrentIndex(2)
    dlg._save_preset()
    chk(names() == ["가", "나", "다", "라", "마"] and dlg.cmb_preset.currentText() == "다",
        "A 창의 '저장…' 으로 고쳐 저장해도 자리 그대로", str(names()))

    # ── B·C·D ──
    nup_before = dlg.cmb_nup.currentData()
    dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findText("라"))
    dlg.btn_preset_up.click(); dlg.btn_preset_up.click()
    chk(names() == ["가", "라", "나", "다", "마"], "B ▲ 두 번 → 두 칸 위로(설정에 저장)", str(names()))
    chk(dlg.cmb_preset.currentText() == "라", "B 옮긴 스타일이 계속 골라져 있다(연달아 누를 수 있게)")
    chk([dlg.cmb_preset.itemText(i) for i in range(dlg.cmb_preset.count())] == names(), "B 목록도 같은 순서")
    dlg.btn_preset_dn.click()
    chk(names() == ["가", "나", "라", "다", "마"], "B ▼ 한 칸 아래로", str(names()))
    chk(dlg.cmb_nup.currentData() == nup_before, "D 옮겨도 창의 설정 값은 그대로(순서만)")
    dlg.cmb_preset.setCurrentIndex(0)
    chk(not dlg.btn_preset_up.isEnabled() and dlg.btn_preset_dn.isEnabled(), "C 맨 위에서는 ▲ 꺼짐")
    dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.count() - 1)
    chk(dlg.btn_preset_up.isEnabled() and not dlg.btn_preset_dn.isEnabled(), "C 맨 아래에서는 ▼ 꺼짐")
    dlg.done(0)
    d2 = TwoUpSettingsDialog({}, None, preset_api=None)
    chk(not d2.btn_preset_up.isEnabled() and not d2.btn_preset_dn.isEnabled(), "C 순서 기능이 없는 창은 둘 다 꺼짐")
    d2.done(0)

    # 다른 창(인쇄 창 스타일 콤보)도 같은 순서를 읽는다
    from viewer.widgets.print_dialog import PrintScopeDialog
    pd = PrintScopeDialog(1, 0, 0, 0, None, preset_api=api)
    chk([pd.cmb_preset.itemText(i) for i in range(1, pd.cmb_preset.count())] == names(),
        "인쇄 창 스타일 목록도 바꾼 순서", str([pd.cmb_preset.itemText(i) for i in range(pd.cmb_preset.count())]))
    pd.done(0)
    mw._prefs["merge_presets"] = []
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
