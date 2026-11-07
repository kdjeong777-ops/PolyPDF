# -*- coding: utf-8 -*-
"""261107-13(사용자 결정 '단추 하나 + 창으로 모음') 사전 관리 정리 — 단어장 SOT §11.1·§7, 디자인 SOT §2.9.1.

A. 도구 탭 '사전 관리' 는 하위 메뉴 없는 단추 하나(명령 id tools.dict) — 누르면 사전 관리 창
   · '인터넷 사전 보강' 은 생성 묶음 '단어장' 바로 뒤(tools.online_enrich), 둘 다 한국 전용
B. 사전 관리 창 — 제목 '사전 관리', [가져오기]·[내보내기]·[백업]·[복원]·[고급 ▾](사전 정리·온용어 다시 분류),
   [사전 지우기]·[지운 사전 되살리기]·[폴더 열기]·[새로고침]·[양식 CSV]·[사용자 뜻 편집] — 단추 이름에 '…' 없음
C. [백업] → 항목 더함 → [복원] 을 창에서 눌러 실제 zip 왕복 — 창의 사전 연결이 닫힌 채 남지 않는다(목록을 다시 읽음)
D. [가져오기] — 파일을 고르면 **한 창**에서 이름·참고문헌·넣을 곳·종류·구분(종전 입력 창 다섯 번) · 값이 그대로 사전에
E. 양식 CSV 는 한 길 — 창의 [양식 CSV](단어장 폴더), 메뉴 길(_action_save_csv_sample)은 없다
"""
import os, sys, tempfile, zipfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import Qt, QStandardPaths, QCoreApplication, QTimer
from PyQt6.QtWidgets import (QApplication, QMessageBox, QInputDialog, QFileDialog, QPushButton, QDialog)
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
# 사용자 실제 설정 폴더(dict.db·settings.json)를 쓰지 않는다 — 마스터 §14.7.2 의 3
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_dict_manage_%d" % os.getpid())
import modal_guard                    # 모달이 떠서 검사가 멈추지 않게(마스터 §14.7.2 의 6)
guard = modal_guard.install(label=lambda: "검사", dialogs=False)   # 창 안을 눌러 보는 검사 — exec 는 그대로(감시 타이머는 남는다)
fails = []
import traceback
sys.excepthook = lambda *a: (traceback.print_exception(*a, file=sys.stdout), fails.append("처리 안 된 예외"))   # 슬롯 예외를 실패로 적는다


def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra if not c else "")
    if not c:
        fails.append(m)


QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
asked = []                                            # 입력 창(QInputDialog)이 몇 번 떴나
QInputDialog.getText = staticmethod(lambda *a, **k: asked.append("text") or ("x", True))
QInputDialog.getItem = staticmethod(lambda *a, **k: asked.append("item") or (a[3][0] if len(a) > 3 else "", True))
root = Path(tempfile.mkdtemp(prefix="polypdf_dictmanage_"))

# ---- A 도구 탭 ----
from viewer.app import MainWindow
from viewer.widgets.ribbon import cmd_id
mw = MainWindow(); mw.show(); app.processEvents()
menu = next(a.menu() for a in mw.menuBar().actions() if a.text().startswith("도구"))
ids = [cmd_id(a) for a in menu.actions() if cmd_id(a)]
a_dict = mw._cmds.get("tools.dict")
chk(a_dict is not None and a_dict.menu() is None and a_dict.text() == "사전 관리",
    "A1 '사전 관리' 는 하위 메뉴 없는 단추 하나", str(a_dict.menu() if a_dict else None))
chk("tools.online_enrich" in ids and ids.index("tools.online_enrich") == ids.index("tools.build_study") + 1
    and mw._cmds["tools.online_enrich"].text() == "인터넷 사전 보강",
    "A2 '인터넷 사전 보강' 은 '단어장 생성' 바로 뒤", str(ids[:6]))
ko = set(map(id, mw._ko_only_acts))
chk(a_dict is not None and id(a_dict) in ko and id(mw._cmds.get("tools.online_enrich")) in ko,
    "A3 둘 다 한국 전용(다국어 SOT §7)")
opened = []
from viewer.widgets import dict_manager_dialog as _dmd
_orig_exec = _dmd.DictManagerDialog.exec
_dmd.DictManagerDialog.exec = lambda self: opened.append(self.windowTitle()) or 0   # 창은 띄우지 않고 무엇이 열렸나만
if a_dict is not None:
    a_dict.trigger()
_dmd.DictManagerDialog.exec = _orig_exec
chk(opened == ["사전 관리"], "A4 누르면 사전 관리 창을 연다", str(opened))
mw._skip_save_on_close = True
mw.close()

# ---- B 사전 관리 창 ----
from viewer.study import dict_store as ds
from viewer.study_controller import StudyMixin
from viewer.widgets.dict_manager_dialog import DictManagerDialog


from PyQt6.QtWidgets import QWidget


class Host(QWidget, StudyMixin):
    """단어장 처리기만 쓰는 작은 창 대역(앱처럼 위젯 — 처리기의 창 부모) — 사전은 시험 프로필의 기본 dict.db(백업·복원이 그 경로를 쓴다)."""
    def __init__(self):
        super().__init__()
        self._prefs = {"glossary_dir": str(root / "gl")}
        self._dict_store = None
        self._study_pdf = None
        self._spot_terms_cache = None
        self.main_view = type("MV", (), {"current_page": lambda _s: 0})()
        self.status = type("ST", (), {"showMessage": lambda _s, *a, **k: None})()
    def _refresh_study_panel(self, page):
        pass


host = Host()
d = DictManagerDialog(host._study_get_dict(), host._prefs, host=host)
d.show(); QTest.qWait(10)
chk(d.windowTitle() == "사전 관리", "B1 창 제목 '사전 관리'", d.windowTitle())
texts = [b.text() for b in d.findChildren(QPushButton)]
WANT = ["가져오기", "내보내기", "백업", "복원", "고급 ▾", "사전 지우기", "지운 사전 되살리기",
        "폴더 열기", "새로고침", "양식 CSV", "사용자 뜻 편집"]
chk(all(w in texts for w in WANT), "B2 사전 파일 단추가 모두 창 안에", str(texts))
chk(not [t for t in texts if t.endswith("...") or t.endswith("…")], "B3 단추 이름에 '…' 없음", str(texts))
adv = getattr(d, "btn_adv", None)
adv_items = [a.text() for a in adv.menu().actions()] if adv is not None and adv.menu() else []
chk(adv_items == ["사전 정리 (HTML 마크업 제거)", "온용어 다시 분류"], "B4 [고급 ▾] = 사전 정리·온용어 다시 분류", str(adv_items))
called = []
host._action_sanitize_dict = lambda *a, **k: called.append("sanitize")
if adv_items:
    adv.menu().actions()[0].trigger()
chk(called == ["sanitize"], "B5 [고급 ▾] 사전 정리는 앱의 같은 처리기")

# ---- C 백업 → 복원(창에서) ----
zp = str(root / "backup.zip")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (zp, ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (zp, ""))
dic = host._study_get_dict()
dic.add_source("bk1", "백업 시험 사전", kind="base")
dic.add_entry(source_id="bk1", term_ko="백업시험어zq", def_ko="백업 전")
d._load()
btn_backup = getattr(d, "btn_backup", None)
btn_restore_all = getattr(d, "btn_restore_all", None)
if btn_backup is not None:
    QTest.mouseClick(btn_backup, Qt.MouseButton.LeftButton)
chk(Path(zp).exists() and "dict.db" in zipfile.ZipFile(zp).namelist(), "C1 [백업] — dict.db 가 든 zip")
ok_after_backup = False
try:
    ok_after_backup = "bk1" in {s["source_id"] for s in d._store.list_sources()}
except Exception as e:
    print("   백업 뒤 창 사전:", type(e).__name__, e)
chk(ok_after_backup, "C2 [백업] 뒤에도 창의 사전 연결이 살아 있다(목록을 다시 읽음)")
host._study_get_dict().delete_source("bk1")
d._load()
if btn_restore_all is not None:
    QTest.mouseClick(btn_restore_all, Qt.MouseButton.LeftButton)
back = False
try:
    back = "bk1" in {s["source_id"] for s in d._store.list_sources()} and "bk1" in d.use_ids() + d.wait_ids()
except Exception as e:
    print("   복원 뒤 창 사전:", type(e).__name__, e)
chk(back, "C3 [복원] — 백업 때의 사전이 돌아오고 창 목록에도 보인다")
chk(bool(host._study_get_dict().lookup("백업시험어zq")), "C4 복원한 사전으로 조회된다")

# ---- D 가져오기 한 창 ----
csvp = root / "road_terms.csv"
csvp.write_text("term_ko,term_en,def_ko\n가져오기시험어zq,import test,가져오기 뜻\n", encoding="utf-8-sig")
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(csvp), ""))
asked.clear()
seen = []


def fill_import():
    dlg = getattr(host, "_glossary_import_dialog", None)
    if dlg is None or not dlg.isVisible():
        QTimer.singleShot(30, fill_import)
        return
    seen.append(dlg)
    dlg.ed_name.setText("도로 시험 용어")
    dlg.ed_ref.setText("시험 참고문헌")
    dlg.cmb_kind.setCurrentIndex(1)                 # 내 사전(User)
    dlg.cmb_tb.setCurrentIndex(1)                   # 일반 사전
    dlg.cmb_cat.setEditText("시험구분")
    dlg.accept()


QTimer.singleShot(30, fill_import)
btn_import = getattr(d, "btn_import", None)
if btn_import is not None:
    QTest.mouseClick(btn_import, Qt.MouseButton.LeftButton)
chk(not asked, "D1 입력 창(QInputDialog)을 잇달아 띄우지 않는다", str(asked))
chk(len(seen) == 1, "D2 이름·참고문헌·넣을 곳·종류·구분은 한 창", str(seen))
src = next((s for s in host._study_get_dict().list_sources() if s["source_id"] == "road_terms"), None)
chk(src is not None and src.get("name") == "도로 시험 용어" and src.get("category") == "시험구분"
    and src.get("kind") == "user" and not src.get("is_termbase"),
    "D3 한 창의 값이 그대로 사전에(이름·구분·넣을 곳·종류)", str(src))
chk("road_terms" in d.use_ids() + d.wait_ids(), "D4 가져온 사전이 창 목록에 바로 보인다")

# ---- E 양식 한 길 ----
chk(not hasattr(StudyMixin, "_action_save_csv_sample"), "E1 메뉴 길 양식 저장(_action_save_csv_sample)은 없다")
d.accept()

print()
print("FAIL", len(fails), fails) if fails else print("ALL PASS")
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 순서 크래시(판정 무관)를 피한다 — 다른 창 검사와 같다
