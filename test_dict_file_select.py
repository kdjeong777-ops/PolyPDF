# -*- coding: utf-8 -*-
"""261103-2(사용자 지시) 사전(출처) 고르기 — 단어장 SOT §11.1·§13, 디자인 SOT §2.14.

A. 단어장 관리 창 — [← 모두 삭제] + '이후 PDF 에도' 끔 + 창 X(reject) → 이 PDF 만 사전 없음, 다른 PDF·기본 선택은 그대로
B. 다시 열면 '이 PDF 만의 선택' · 왼쪽에서 하나 [추가 →] + '이후' 켬 → 기본 선택이 되고 이 PDF 의 선택은 지워진다
C. [모두 추가 →] + Esc → 모든 PDF 에 모든 사전 · 두 번 누르기로 옮기기 · ▲▼ = 우선순위
D. 스타일 — 저장·고르기·삭제, 패널 '출처 ▾' 맨 위 스타일로 바로 적용
E. 패널 메뉴 — 이 PDF 의 선택이 있으면 그것만, 없으면 기본 선택을 고친다
F. 고급 설정에는 '사전 목록' 이 없다 — 가져오기·지우기·되살리기·폴더 단추는 단어장 관리 창에(261103-8, 사용자 지시)
G. 관리 창 [사전 지우기] — 다시 생기지 않음(폴더 CSV·동봉 시드) · [지운 사전 되살리기...]
H. 이름 변경(filesRelocated) → 이 PDF 의 선택이 새 경로를 따라간다 · 복사는 따라가지 않는다
I. settings.json — 허용목록·개인 항목(배포 기본값에서 뺌)
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import Qt, QStandardPaths, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox, QInputDialog, QDialog, QPushButton
from PyQt6.QtTest import QTest

QStandardPaths.setTestModeEnabled(True)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
app = QApplication.instance() or QApplication(sys.argv)
root = Path(tempfile.mkdtemp(prefix="polypdf_dictsel_"))

from viewer.study import dict_store as ds
from viewer.study import glossary_folder as gf
from viewer.study_controller import StudyMixin
from viewer.widgets.dict_manager_dialog import DictManagerDialog
from viewer.widgets.study_panel import StudyPanel
from viewer.widgets.settings_dialog import AdvancedSettingsDialog

dic = ds.DictStore(root / "dict.db")
for sid, name in (("g1", "도로 용어집"), ("g2", "건설 용어집")):
    dic.add_source(sid, name, kind="base", priority=50)
dic.add_entry(source_id="g1", term_ko="포장시험어zq", def_ko="도로 포장")
dic.add_entry(source_id="g2", term_ko="골재시험어zq", def_ko="모래·자갈")

pdf_a = str(root / "a.pdf"); pdf_b = str(root / "b.pdf")


class Host(StudyMixin):
    """단어장 처리기만 쓰는 작은 창 대역 — 사전 연결은 시험 폴더의 dict.db."""
    def __init__(self):
        self._prefs = {"glossary_dir": str(root / "gl")}
        self._dict_store = dic
        self._study_pdf = None
        self._spot_terms_cache = None
        self.refreshed = 0
        self.main_view = type("MV", (), {"current_page": lambda _s: 0})()
    def _refresh_study_panel(self, page):
        self.refreshed += 1


host = Host()
panel = StudyPanel()
host.study_panel = panel
panel.sourceToggled.connect(host._on_study_source_toggled)
panel.styleChosen.connect(host._on_dict_style_chosen)

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

def click(btn):
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)

def select(lst, sids):
    lst.clearSelection()
    for i in range(lst.count()):
        it = lst.item(i)
        if it.data(Qt.ItemDataRole.UserRole) in sids:
            it.setSelected(True); lst.setCurrentItem(it)

def dclick(lst, sid):
    """실제 두 번 누르기 — Qt6 QTest 는 누름 뒤에 두 번 누름을 보내야 itemDoubleClicked 가 난다."""
    pos = lst.visualItemRect(item_of(lst, sid)).center()
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseDClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=pos)

def item_of(lst, sid):
    return next(lst.item(i) for i in range(lst.count())
                if lst.item(i).data(Qt.ItemDataRole.UserRole) == sid)

ALL = {"user", "g1", "g2"}

# ---- A ----
chk(found(pdf_a, "포장시험어zq") and found(pdf_b, "골재시험어zq"), "A0 처음엔 모든 PDF 에 기본 선택(모두 켜짐)")
d = open_dlg(pdf_a)
chk(set(d.use_ids()) == ALL and not d.wait_ids(), "A1 오른쪽(적용할 사전)에 지금 쓰는 사전, 왼쪽은 비어 있음")
chk(d.chk_default.isChecked(), "A2 이 PDF 의 선택이 없으면 '이후 PDF 에도' 켜짐")
chk(d.btn_delete.text() == "사전 지우기" and d.btn_remove.text() == "← 삭제",
    "A3 적용 목록에서 빼기([← 삭제])와 사전 지우기([사전 지우기])는 다른 단추")
click(d.btn_remove_all)
chk(not d.use_ids() and set(d.wait_ids()) == ALL, "A4 [← 모두 삭제] → 모두 대기 사전으로")
d.chk_default.click()
d.reject()                         # 창 X·Esc 와 같은 길
chk(not found(pdf_a, "포장시험어zq") and not found(pdf_a, "골재시험어zq"), "A5 이 PDF(a) 는 사전 없음(닫기 단추가 아니어도 저장)")
chk(found(pdf_b, "포장시험어zq") and found(pdf_b, "골재시험어zq"), "A6 다른 PDF(b) 는 그대로")
chk(all(s["enabled"] for s in dic.list_sources()), "A7 기본 선택(dict.db enabled)은 그대로")

# ---- B ----
d = open_dlg(pdf_a)
chk(not d.chk_default.isChecked() and "이 PDF 만" in d.lbl_file.text(),
    "B1 다시 열면 이 PDF 만의 선택 — '이후' 꺼짐", d.lbl_file.text())
select(d.lst_wait, {"g1"})
click(d.btn_add)
chk(d.use_ids() == ["g1"], "B2 [추가 →] — 고른 것만 오른쪽으로", str(d.use_ids()))
d.chk_default.click()
click(d.btn_close)
chk(found(pdf_a, "포장시험어zq") and not found(pdf_a, "골재시험어zq"), "B3 a: 고른 g1 만")
chk(found(pdf_b, "포장시험어zq") and not found(pdf_b, "골재시험어zq"), "B4 이후 PDF(b) 도 g1 만(기본 선택이 됨)")
chk(not (host._prefs.get("dict_file_off") or {}), "B5 이 PDF 의 선택은 지워짐(기본을 따른다)")

# ---- C ----
d = open_dlg(pdf_b)
click(d.btn_add_all)
chk(set(d.use_ids()) == ALL, "C1 [모두 추가 →]")
dclick(d.lst_use, "g2")
chk("g2" in d.wait_ids(), "C2 두 번 누르면 반대쪽으로")
dclick(d.lst_wait, "g2")
order0 = d.use_ids()
select(d.lst_use, {"g2"})
click(d.btn_up)
chk(d.use_ids().index("g2") == order0.index("g2") - 1, "C3 ▲ — 오른쪽 차례가 바뀜", f"{order0} → {d.use_ids()}")
chk([s["source_id"] for s in dic.list_sources()].index("g2")
    < [s["source_id"] for s in dic.list_sources()].index("g1"), "C4 ▲ 는 dict.db 우선순위를 바로 고친다")
QTest.keyClick(d, Qt.Key.Key_Escape)
chk(found(pdf_a, "골재시험어zq") and found(pdf_b, "골재시험어zq"), "C5 Esc 로 닫아도 기본 선택으로 저장 → 모든 PDF")

# ---- D 스타일 ----
d = open_dlg(pdf_b)
select(d.lst_use, {"g2"}); click(d.btn_remove)
QInputDialog.getText = staticmethod(lambda *a, **k: ("도로만", True))
click(d.btn_style_save)
chk([s["name"] for s in host._dict_styles()] == ["도로만"] and "g2" not in host._dict_styles()[0]["sources"],
    "D1 [저장...] — 오른쪽 조합을 스타일로")
click(d.btn_add_all)
d.cmb_style.activated.emit(d.cmb_style.findText("도로만"))
chk("g2" not in d.use_ids() and "g1" in d.use_ids(), "D2 스타일 고르면 오른쪽 목록이 그 조합으로")
d.accept()
chk(not found(pdf_b, "골재시험어zq") and found(pdf_b, "포장시험어zq"), "D3 닫으면 그 조합이 적용")
d = open_dlg(pdf_b); click(d.btn_add_all); d.accept()      # 다시 모두
host._refresh_dict_sources_menu()
sty = [a for a in panel.btn_src.menu().actions() if a.text().strip() == "도로만"]
chk(bool(sty), "D4 패널 '출처 ▾' 맨 위에 스타일")
sty and sty[0].trigger()
chk(not found(pdf_b, "골재시험어zq") and found(pdf_b, "포장시험어zq"), "D5 패널에서 스타일 → 바로 적용(기본 선택)")
d = open_dlg(pdf_b)
d.cmb_style.setCurrentIndex(d.cmb_style.findText("도로만"))
click(d.btn_style_del)
chk(not host._dict_styles(), "D6 스타일 [삭제] — 스타일만 지움")
click(d.btn_add_all); d.accept()

# ---- E 패널 메뉴 ----
def menu_toggle(pdf, sid, on):
    use(pdf)
    host._refresh_dict_sources_menu()
    acts = [a for a in panel.btn_src.menu().actions() if a.isCheckable()]
    for sub in getattr(panel, "_src_submenus", []):
        acts += [a for a in sub.actions() if a.isCheckable()]
    name = dic.get_source(sid)["name"]
    a = next(a for a in acts if name in a.text())
    if a.isChecked() != on:
        a.trigger()
d = open_dlg(pdf_a); d.chk_default.click(); d.accept()     # a 만의 선택(모두)
menu_toggle(pdf_a, "g2", False)
chk(not found(pdf_a, "골재시험어zq") and found(pdf_b, "골재시험어zq"), "E1 a 만의 선택이 있으면 메뉴는 a 만 고친다")
menu_toggle(pdf_b, "g1", False)
chk(not found(pdf_b, "포장시험어zq") and not dic.get_source("g1")["enabled"], "E2 b(선택 없음) → 기본 선택을 고친다(종전 동작)")
chk(found(pdf_a, "포장시험어zq"), "E3 a 는 자기 선택이라 영향 없음")
menu_toggle(pdf_b, "g1", True)

# ---- F 고급 설정에는 사전 목록이 없다(단어장 관리로 옮김) ----
from PyQt6.QtWidgets import QGroupBox
adv = AdvancedSettingsDialog(dict(host._prefs), None)
adv.show(); QTest.qWait(10)
chk(not [g for g in adv.findChildren(QGroupBox) if g.title() == "사전 목록"] and not hasattr(adv, "grp_dict_list"),
    "F0 고급 설정에 '사전 목록' 묶음이 없다")
adv.reject()
d = open_dlg(pdf_b)
chk(all(hasattr(d, n) for n in ("btn_import", "btn_delete", "btn_restore")), "F1 관리 창에 [가져오기...]·[사전 지우기]·[지운 사전 되살리기...]")
chk({"폴더 열기", "새로고침", "양식 CSV"} <= {b.text() for b in d.findChildren(QPushButton)}, "F2 관리 창에 [폴더 열기]·[새로고침]·[양식 CSV]")
d.reject()

# ---- G 사전 지우기·되살리기(관리 창) ----
gf.write_sample(root / "gl")
gf.sync_folder(dic, host._prefs)
fid = next(s["source_id"] for s in dic.list_sources() if s["source_id"].startswith("folder__"))
d = open_dlg(pdf_b)
select(d.lst_use, {fid}); select(d.lst_wait, {"g1"})
if "g1" in d.use_ids():
    item_of(d.lst_use, "g1").setSelected(True)
click(d.btn_delete)
ids = {s["source_id"] for s in dic.list_sources()}
chk(fid not in ids and "g1" not in ids, "G1 [사전 지우기] — 두 목록 어디서 골라도 지움")
chk(fid not in d.use_ids() + d.wait_ids(), "G1b 관리 창 목록에서도 바로 빠진다")
gf.sync_folder(dic, host._prefs)
chk(fid not in {s["source_id"] for s in dic.list_sources()}, "G2 폴더에 파일이 있어도 [새로고침] 에 다시 안 생김")
chk(not dic.seed_source_if_newer("g1", "도로 용어집", reference="", version=99,
                                 rows=[{"term_ko": "포장시험어zq"}]), "G3 동봉 시드도 지운 사전은 건너뜀")
chk((root / "gl" / "예제_단어장.csv").exists(), "G4 원본 파일은 그대로")
chk(d.btn_restore.isEnabled(), "G5 [지운 사전 되살리기...] 켜짐")
QTimer.singleShot(50, lambda: d._restore_dialog.accept())
click(d.btn_restore)
ids = {s["source_id"] for s in dic.list_sources()}
chk(fid in ids and fid in d.use_ids() + d.wait_ids(), "G6 되살리기 → 폴더 사전 다시 실림(관리 창에도)")
chk("g1" not in ids and "도로 용어집" in d.info.text(), "G7 가져온(동봉 아님) 사전은 다시 가져오라고 알림", d.info.text())
d.accept()

# ---- H 이름 변경 ----
d = open_dlg(pdf_a); d.chk_default.setChecked(False); select(d.lst_use, {"g2"}); click(d.btn_remove); d.accept()
pdf_a2 = str(root / "a_새이름.pdf")
host._relocate_dict_file_sel([[pdf_a, pdf_a2]])
chk(not found(pdf_a2, "골재시험어zq"), "H1 이름 바꾼 a 도 자기 선택 그대로")
chk(found(pdf_a, "골재시험어zq"), "H2 옛 이름 키는 없어짐(옛 경로는 기본 선택을 따른다)")
host._relocate_dict_file_sel([["", str(root / "copy.pdf")]])
chk(found(str(root / "copy.pdf"), "골재시험어zq"), "H3 복사본은 기본 선택")
src_app = (Path(__file__).parent / "viewer" / "app.py").read_text(encoding="utf-8")
chk("self._relocate_dict_file_sel(pairs)" in src_app, "H4 _on_files_relocated 가 부른다")
chk("self.study_panel.styleChosen.connect(self._on_dict_style_chosen)" in src_app, "H5 앱이 패널 스타일을 잇는다")

# ---- I ----
from viewer import settings_store
chk({"dict_file_off", "dict_styles"} <= settings_store.PERSONAL_PREF_KEYS, "I1 개인 항목(이 PC 경로·사전 ID)")
out = settings_store.extract_distributable_defaults(
    {"preferences": {"dict_file_off": {"x": ["g1"]}, "dict_styles": [{"name": "a", "sources": []}]}})
chk("dict_file_off" not in out["preferences"] and "dict_styles" not in out["preferences"], "I2 배포 기본값에서 뺀다")
chk('"dict_file_off": dict(prefs.get("dict_file_off"' in src_app and '"dict_styles": list(prefs.get("dict_styles"' in src_app,
    "I3 저장 허용목록에 있다")

dic.close()
print("\nFAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
