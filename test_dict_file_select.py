# -*- coding: utf-8 -*-
"""261103-2(사용자 지시) 단어장 관리의 사전(출처) 선택 — 단어장 SOT §11.1·§13.

A. [전체 해제] + '이후 PDF 에도' 끔 + 창 X(reject) → 이 PDF 만 사전 없음, 다른 PDF·기본 선택은 그대로
B. 다시 열면 '이 PDF 만의 선택' 이 보이고 '이후' 체크가 꺼져 있다 / 일부 선택 + '이후' 켬 → 기본 선택이 되고 이 PDF 의 선택은 지워진다
C. [전체 선택] + '이후' 켬 → 모든 PDF 에 모든 사전
D. 패널 '출처 ▾' 메뉴 — 이 PDF 의 선택이 있으면 그것만, 없으면 기본 선택을 고친다
E. 이름 변경(filesRelocated) → 이 PDF 의 선택이 새 경로를 따라간다 · 복사는 따라가지 않는다
F. settings.json — 허용목록·개인 항목(배포 기본값에서 뺌)
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import Qt, QStandardPaths
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

QStandardPaths.setTestModeEnabled(True)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

app = QApplication.instance() or QApplication(sys.argv)
root = Path(tempfile.mkdtemp(prefix="polypdf_dictsel_"))

from viewer.study import dict_store as ds
from viewer.study_controller import StudyMixin
from viewer.widgets.dict_manager_dialog import DictManagerDialog
from viewer.widgets.study_panel import StudyPanel

dic = ds.DictStore(root / "dict.db")
for sid, name in (("g1", "도로 용어집"), ("g2", "건설 용어집")):
    dic.add_source(sid, name, kind="base", priority=50)
dic.add_entry(source_id="g1", term_ko="포장", def_ko="도로 포장")
dic.add_entry(source_id="g2", term_ko="골재", def_ko="모래·자갈")

pdf_a = str(root / "a.pdf"); pdf_b = str(root / "b.pdf")


class Host(StudyMixin):
    """단어장 처리기만 쓰는 작은 창 대역 — 사전 연결은 시험 폴더의 dict.db."""
    def __init__(self):
        self._prefs = {}
        self._dict_store = dic
        self._study_pdf = None
        self._spot_terms_cache = None
        self.refreshed = 0
        self.main_view = type("MV", (), {"current_page": lambda _s: 0})()
    def _refresh_study_panel(self, page):
        self.refreshed += 1


host = Host()

def use(pdf):
    host._study_pdf = Path(pdf) if pdf else None
    return host._study_get_dict()

def found(pdf, term):
    return bool(use(pdf).lookup(term))

def open_dlg(pdf):
    use(pdf)
    d = DictManagerDialog(host._study_get_dict(), host._prefs, host=host)
    d.show(); QTest.qWait(10)
    return d

def row_of(d, sid):
    for r in range(d.table.rowCount()):
        if d.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == sid:
            return r
    return -1

def checked(d):
    return {d.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            for r in range(d.table.rowCount())
            if d.table.item(r, 0).checkState() == Qt.CheckState.Checked}

# ---- A ----
chk(found(pdf_a, "포장") and found(pdf_b, "골재"), "A0 처음엔 모든 PDF 에 기본 선택(모두 켜짐)")
d = open_dlg(pdf_a)
chk(d.chk_default.isChecked(), "A1 이 PDF 의 선택이 없으면 '이후 PDF 에도' 켜짐")
QTest.mouseClick(d.btn_none, Qt.MouseButton.LeftButton)
chk(not checked(d), "A2 [전체 해제] → 모든 칸 꺼짐")
d.chk_default.click()
chk(not d.chk_default.isChecked(), "A3 '이후 PDF 에도' 끔")
d.reject()                         # 창 X·Esc 와 같은 길
chk(not found(pdf_a, "포장") and not found(pdf_a, "골재"), "A4 이 PDF(a) 는 사전 없음(닫기 단추가 아니어도 저장)")
chk(found(pdf_b, "포장") and found(pdf_b, "골재"), "A5 다른 PDF(b) 는 그대로")
chk(all(s["enabled"] for s in dic.list_sources()), "A6 기본 선택(dict.db enabled)은 그대로")

# ---- B ----
d = open_dlg(pdf_a)
chk(not d.chk_default.isChecked() and "이 PDF 만" in d.lbl_file.text(),
    "B1 다시 열면 이 PDF 만의 선택 — '이후' 꺼짐", d.lbl_file.text())
chk(not checked(d), "B2 표는 이 PDF 의 선택(모두 꺼짐)을 보인다")
it = d.table.item(row_of(d, "g1"), 0)
it.setCheckState(Qt.CheckState.Checked)                  # 일부 선택
d.chk_default.click()
QTest.mouseClick(d.btn_close, Qt.MouseButton.LeftButton)
chk(found(pdf_a, "포장") and not found(pdf_a, "골재"), "B3 a: 고른 g1 만")
chk(found(pdf_b, "포장") and not found(pdf_b, "골재"), "B4 이후 PDF(b) 도 g1 만(기본 선택이 됨)")
chk(not (host._prefs.get("dict_file_off") or {}), "B5 이 PDF 의 선택은 지워짐(기본을 따른다)")

# ---- C ----
d = open_dlg(pdf_b)
QTest.mouseClick(d.btn_all, Qt.MouseButton.LeftButton)
chk(checked(d) == {s["source_id"] for s in dic.list_sources()}, "C1 [전체 선택] → 모든 칸 켜짐")
QTest.keyClick(d, Qt.Key.Key_Escape)
chk(found(pdf_a, "골재") and found(pdf_b, "골재"), "C2 Esc 로 닫아도 기본 선택으로 저장 → 모든 PDF")

# ---- D ----
panel = StudyPanel()
panel.sourceToggled.connect(host._on_study_source_toggled)
def menu_toggle(pdf, sid, on):
    use(pdf)
    panel.set_dict_sources(host._study_get_dict().list_sources())
    acts = [a for a in panel.btn_src.menu().actions() if a.isCheckable()]
    for sub in getattr(panel, "_src_submenus", []):
        acts += [a for a in sub.actions() if a.isCheckable()]
    name = dic.get_source(sid)["name"]
    a = next(a for a in acts if name in a.text())
    if a.isChecked() != on:
        a.trigger()
d = open_dlg(pdf_a)                              # a 만의 선택을 만든다(모두 켜짐)
d.chk_default.click()
d.accept()
menu_toggle(pdf_a, "g2", False)
chk(not found(pdf_a, "골재") and found(pdf_b, "골재"), "D1 a 만의 선택이 있으면 메뉴는 a 만 고친다")
menu_toggle(pdf_b, "g1", False)
chk(not found(pdf_b, "포장") and not dic.get_source("g1")["enabled"], "D2 b(선택 없음) → 기본 선택을 고친다(종전 동작)")
chk(found(pdf_a, "포장"), "D3 a 는 자기 선택이라 영향 없음")
use(pdf_a)
panel.set_dict_sources(host._study_get_dict().list_sources())
g2_act = [a for a in panel.btn_src.menu().actions() if "건설" in a.text()]
chk(g2_act and not g2_act[0].isChecked(), "D4 메뉴 체크는 이 PDF 에 쓰는 출처(active)")

# ---- E ----
pdf_a2 = str(root / "a_새이름.pdf")
host._relocate_dict_file_sel([[pdf_a, pdf_a2]])
chk(not found(pdf_a2, "골재") and found(pdf_a2, "포장"), "E1 이름 바꾼 a 도 자기 선택 그대로")
chk(not found(pdf_a, "포장"), "E2 옛 이름 키는 없어짐(옛 경로는 기본 선택을 따른다)")
host._relocate_dict_file_sel([["", str(root / "copy.pdf")]])
chk(found(str(root / "copy.pdf"), "골재"), "E3 복사본은 기본 선택")
src_app = (Path(__file__).parent / "viewer" / "app.py").read_text(encoding="utf-8")
chk("self._relocate_dict_file_sel(pairs)" in src_app, "E4 _on_files_relocated 가 부른다")

# ---- F ----
from viewer import settings_store
chk("dict_file_off" in settings_store.PERSONAL_PREF_KEYS, "F1 개인 항목(이 PC 경로)")
out = settings_store.extract_distributable_defaults({"preferences": {"dict_file_off": {"x": ["g1"]}}})
chk("dict_file_off" not in out["preferences"], "F2 배포 기본값에서 뺀다")
chk('"dict_file_off": dict(prefs.get("dict_file_off"' in src_app, "F3 저장 허용목록에 있다")

dic.close()
print("\nFAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
