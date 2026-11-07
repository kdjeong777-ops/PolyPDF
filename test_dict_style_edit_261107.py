# -*- coding: utf-8 -*-
"""261107-25(사용자 지시 '설정한 사전 스타일을 저장/삭제/수정할 수 있도록') — 단어장 SOT §11.1.

A. 이 PDF 의 사전 창 — 스타일 줄([저장]·[수정]·[삭제])이 보이고, 누르면 바로 settings `dict_styles` 에 + 패널 '출처 ▾' 메뉴
B. [수정] — 고른 스타일을 지금 오른쪽 목록으로, 이름도 바꿈(옛 이름은 사라짐, 자리 그대로)
C. [저장] 이 같은 이름이면 덮어쓸지 묻는다 — 아니오면 그대로, 예면 덮어씀
D. [수정]·[삭제] 는 스타일을 고른 동안만 켜짐 · [삭제] 는 바로 지움
E. 환경설정 판 — 저장·수정·삭제는 판 안에만, [적용] 때 settings 에([취소] = 적용 안 함이면 그대로)
F. [기본 사전으로] — 묻고(아니오면 그대로), 예면 기본 선택이 오른쪽 목록으로·이 PDF 의 선택 지움·다른 PDF 의 선택은 그대로(이후 여는 PDF 는 새 기본)
수정 전 코드: 이 PDF 창에 스타일 단추가 숨어 있고 [수정] 이 없다 → A·B·D 실패.
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import Qt, QStandardPaths
from PyQt6.QtWidgets import QApplication, QMessageBox, QInputDialog
from PyQt6.QtTest import QTest

QStandardPaths.setTestModeEnabled(True)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

ANSWER = {"q": QMessageBox.StandardButton.Yes, "name": ("", True), "asked": 0}
def _question(*a, **k):
    ANSWER["asked"] += 1
    return ANSWER["q"]
QMessageBox.question = staticmethod(_question)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QInputDialog.getText = staticmethod(lambda *a, **k: ANSWER["name"])
app = QApplication.instance() or QApplication(sys.argv)
root = Path(tempfile.mkdtemp(prefix="polypdf_dictstyle_"))

from viewer.study import dict_store as ds
from viewer.study_controller import StudyMixin
from viewer.widgets.dict_manager_dialog import DictFileDialog, DictManagerPanel
from viewer.widgets.study_panel import StudyPanel

dic = ds.DictStore(root / "dict.db")
for sid, name in (("g1", "도로 용어집"), ("g2", "건설 용어집")):
    dic.add_source(sid, name, kind="base", priority=50)
dic.add_entry(source_id="g1", term_ko="포장시험어zq", def_ko="도로 포장")
dic.add_entry(source_id="g2", term_ko="골재시험어zq", def_ko="모래·자갈")
pdf_a = str(root / "a.pdf")


class Host(StudyMixin):
    def __init__(self):
        self._prefs = {"glossary_dir": str(root / "gl")}
        self._dict_store = dic
        self._study_pdf = Path(pdf_a)
        self._spot_terms_cache = None
        self.main_view = type("MV", (), {"current_page": lambda _s: 0})()
    def _refresh_study_panel(self, page):
        pass


host = Host()
panel = StudyPanel()
host.study_panel = panel

def click(btn):
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)

def select(lst, sids):
    lst.clearSelection()
    for i in range(lst.count()):
        it = lst.item(i)
        if it.data(Qt.ItemDataRole.UserRole) in sids:
            it.setSelected(True); lst.setCurrentItem(it)

def styles():
    return [(s["name"], sorted(s["sources"])) for s in host._dict_styles()]

def menu_styles():
    host._refresh_dict_sources_menu()
    names = [a.text().strip() for a in panel.btn_src.menu().actions()]
    return [n for n in ("도로만", "도로·건설", "전부") if n in names]

def pick(p, name):
    p.cmb_style.setCurrentIndex(p.cmb_style.findText(name))

# ---- A 이 PDF 창 [저장] → 바로 ----
d = DictFileDialog(host._study_get_dict(), host._prefs, host=host)
d.show(); QTest.qWait(10)
btn_edit = getattr(d.panel, "btn_style_edit", None)
chk(d.btn_style_save.isVisibleTo(d) and d.btn_style_del.isVisibleTo(d) and btn_edit is not None and btn_edit.isVisibleTo(d),
    "A1 이 PDF 창에 스타일 [저장]·[수정]·[삭제]")
select(d.lst_use, {"g2"}); click(d.btn_remove)
ANSWER["name"] = ("도로만", True)
click(d.btn_style_save)
chk(styles() == [("도로만", ["g1", "user"])], "A2 [저장] — 창을 닫기 전에 settings 에", str(styles()))
chk(menu_styles() == ["도로만"], "A3 패널 '출처 ▾' 메뉴에도 바로", str(menu_styles()))

# ---- D 단추 켜짐 ----
d.cmb_style.setCurrentIndex(0)
chk(btn_edit is not None and not btn_edit.isEnabled() and not d.btn_style_del.isEnabled(),
    "D1 스타일을 고르지 않으면 [수정]·[삭제] 꺼짐")
pick(d, "도로만")
chk(btn_edit is not None and btn_edit.isEnabled() and d.btn_style_del.isEnabled(), "D2 고르면 켜짐")

# ---- B [수정] — 내용·이름 ----
ANSWER["name"] = ("전부", True); click(d.btn_style_save)          # 다른 스타일 하나 더(자리 확인용)
pick(d, "도로만")
click(d.btn_add_all)
ANSWER["name"] = ("도로·건설", True)
if btn_edit is not None:
    click(btn_edit)
chk(styles() == [("도로·건설", ["g1", "g2", "user"]), ("전부", ["g1", "user"])],
    "B1 [수정] — 고른 스타일이 지금 목록으로, 이름도 바뀌고 자리는 그대로", str(styles()))
chk(d.cmb_style.currentText() == "도로·건설", "B2 콤보는 고친 스타일", d.cmb_style.currentText())

# ---- C 같은 이름 [저장] ----
select(d.lst_use, {"g1"}); click(d.btn_remove)
ANSWER["name"] = ("전부", True); ANSWER["q"] = QMessageBox.StandardButton.No; ANSWER["asked"] = 0
click(d.btn_style_save)
chk(ANSWER["asked"] == 1 and ("전부", ["g1", "user"]) in styles(), "C1 같은 이름 — 묻고, 아니오면 그대로", str(styles()))
ANSWER["q"] = QMessageBox.StandardButton.Yes
click(d.btn_style_save)
chk(("전부", ["g2", "user"]) in styles() and len(styles()) == 2, "C2 예면 덮어씀(하나만)", str(styles()))

# ---- D3 [삭제] ----
pick(d, "전부")
click(d.btn_style_del)
chk([n for n, _ in styles()] == ["도로·건설"], "D3 [삭제] — 바로 지움", str(styles()))
chk(menu_styles() == ["도로·건설"], "D4 메뉴에서도 빠짐", str(menu_styles()))
d.reject()

# ---- E 환경설정 판 — [적용] 때만 ----
before = styles()
p = DictManagerPanel(host._study_get_dict(), host._prefs, host=host, mode="default")
p.show(); QTest.qWait(10)
ANSWER["name"] = ("전부", True); click(p.btn_add_all); click(p.btn_style_save)
pick(p, "도로·건설"); select(p.lst_use, {"g2"}); click(p.btn_remove)
ANSWER["name"] = ("도로만", True)
if getattr(p, "btn_style_edit", None) is not None:
    click(p.btn_style_edit)
chk(styles() == before, "E1 환경설정 판 — [적용] 전에는 settings 그대로([취소] 면 그대로 남음)", str(styles()))
chk([s["name"] for s in p.styles()] == ["도로만", "전부"], "E2 판 안에는 수정·저장이 들어 있다", str(p.styles()))
host._prefs["dict_styles"] = p.styles()          # [적용] 과 같은 길(_settings_apply → _apply_prefs)
chk(styles() == [("도로만", ["g1", "user"]), ("전부", ["g1", "g2", "user"])], "E3 [적용] 뒤 settings 에", str(styles()))
p.close()

# ---- F [기본 사전으로] (사용자 지시 '선택한 사전을 기본사전으로 변경 도 추가') ----
pdf_b = str(root / "b.pdf"); pdf_c = str(root / "c.pdf")
def use(pdf):
    host._study_pdf = Path(pdf)
    return host._study_get_dict()
def found(pdf, term):
    return bool(use(pdf).lookup(term))
def open_file(pdf):
    use(pdf)
    dd = DictFileDialog(host._study_get_dict(), host._prefs, host=host)
    dd.show(); QTest.qWait(10)
    return dd
# b 는 이 PDF 만의 선택(g2 만 끔)
dd = open_file(pdf_b); select(dd.lst_use, {"g2"}); click(dd.btn_remove); dd.accept()
chk(found(pdf_b, "포장시험어zq") and not found(pdf_b, "골재시험어zq"), "F0 b: 이 PDF 만의 선택(g1 만)")
dd = open_file(pdf_a)
btn = getattr(dd, "btn_make_default", None)
chk(btn is not None and btn.isVisibleTo(dd), "F1 이 PDF 창에 [기본 사전으로]")
select(dd.lst_use, {"g1"}); click(dd.btn_remove)             # a: g2·user 만
en0 = {s["source_id"]: bool(s["enabled"]) for s in dic.list_sources()}
ANSWER["q"] = QMessageBox.StandardButton.No; ANSWER["asked"] = 0
if btn is not None:
    click(btn)
chk(ANSWER["asked"] == 1 and dd.isVisible() and {s["source_id"]: bool(s["enabled"]) for s in dic.list_sources()} == en0,
    "F2 먼저 묻는다 — 아니오면 기본 선택 그대로, 창도 그대로")
ANSWER["q"] = QMessageBox.StandardButton.Yes
if btn is not None:
    click(btn)
en1 = {s["source_id"]: bool(s["enabled"]) for s in dic.list_sources()}
chk(not dd.isVisible() and en1.get("g1") is False and en1.get("g2") is True, "F3 예 — 기본 선택이 오른쪽 목록으로, 창 닫힘", str(en1))
off = host._prefs.get("dict_file_off") or {}
chk(host._dict_file_key() not in off if hasattr(host, "_dict_file_key") else False, "F4 지금 PDF(a) 는 이 PDF 의 선택이 지워져 기본을 따른다", str(off))
chk(not found(pdf_c, "포장시험어zq") and found(pdf_c, "골재시험어zq"), "F5 이후 여는 PDF(c) 는 새 기본 사전")
chk(found(pdf_b, "포장시험어zq") and not found(pdf_b, "골재시험어zq"), "F6 이 PDF 만의 선택이 있는 b 는 그대로")

# ---- G 사전은 단어장 단어에 뜻을 붙인다 — 안내 한 줄(동작은 그대로) ----
from PyQt6.QtWidgets import QLabel
dd = open_file(pdf_a)
chk(any("[단어장 생성]" in w.text() and "사전" in w.text() for w in dd.findChildren(QLabel)),
    "G1 이 PDF 창 안내 — 고른 사전은 [단어장 생성] 으로 만든 단어에 뜻을 붙인다")
dd.reject()
host._study_get_store = lambda: type("S", (), {"vocab_count": lambda _s, _k: 0})()
host._apply_vocab_marks = lambda *a, **k: None
StudyMixin._refresh_study_panel(host, 0)
st = panel.lbl_status.text()
chk("[단어장 생성]" in st and "사전" in st and "뜻" in st, "G2 빈 패널 상태 줄도 같은 뜻", st)

print("\nALL PASS" if not fails else f"\nFAIL {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
