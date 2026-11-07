# -*- coding: utf-8 -*-
"""261107-22(SOT 점검 C3) `@korea_only` 는 **처리기**에만 — 다국어 SOT §7.

`korea_only` 는 한국어 화면이 아니면 아무것도 하지 않고 None 을 돌려준다. 이것을 처리기가 부르는 **공용 도우미**에 붙이면
처리기는 None 을 '성공' 으로 읽어 하지 않은 일을 했다고 알린다 — 실제로 `_dict_file_job` 에 붙어
영어 화면에서 [백업] 이 아무것도 하지 않고 '백업했습니다' 창을 띄웠다.

A. 영어 화면에서 사전 [백업]·[복원] 처리기를 불러도 파일 창·성공 창이 뜨지 않고 일도 하지 않는다(수정 전 코드는 성공 창)
B. `@korea_only` 가 붙은 함수는 처리기 이름(`_action_`·`_vm_`·`_on_`)뿐 — 소스 전체를 AST 로 본다
"""
import ast, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QWidget

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)          # 사용자 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3
QCoreApplication.setApplicationName("polypdf_korea_only_%d" % os.getpid())
fails = []


def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra if not c else "")
    if not c:
        fails.append(m)


seen = []
QMessageBox.information = staticmethod(lambda *a, **k: seen.append(("info", a[1] if len(a) > 1 else "")))
QMessageBox.warning = staticmethod(lambda *a, **k: seen.append(("warn", a[1] if len(a) > 1 else "")))
QMessageBox.question = staticmethod(lambda *a, **k: seen.append(("ask", "")) or QMessageBox.StandardButton.Yes)
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: seen.append(("save", "")) or ("x.zip", ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: seen.append(("open", "")) or ("x.zip", ""))

from viewer import i18n
from viewer.study import dict_backup
from viewer.study_controller import StudyMixin

ran = []
dict_backup.backup_to = lambda *a, **k: ran.append("backup")
dict_backup.restore_from = lambda *a, **k: ran.append("restore")


class Host(QWidget, StudyMixin):
    def __init__(self):
        super().__init__()
        self._prefs = {}
        self._dict_store = None
        self._study_pdf = None
        self._spot_terms_cache = None
        self.main_view = type("MV", (), {"current_page": lambda _s: 0})()
    def _refresh_study_panel(self, page):
        pass


h = Host()
_orig = i18n._lang
i18n._lang = "en"
try:
    h._action_backup_dict()
    h._action_restore_dict()
finally:
    i18n._lang = _orig
chk(not seen and not ran, "A 영어 화면 — [백업]·[복원] 처리기는 창도 일도 없다(하지 않은 일을 했다고 알리지 않음)", str(seen + ran))

# ---- B ----
ROOT = Path(__file__).resolve().parent
bad = []
for p in sorted((ROOT / "viewer").rglob("*.py")):
    try:
        tree = ast.parse(p.read_text(encoding="utf-8-sig"))
    except SyntaxError:
        continue
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [d.id if isinstance(d, ast.Name) else getattr(d, "attr", "") for d in n.decorator_list]
            if "korea_only" in names and not n.name.startswith(("_action_", "_vm_", "_on_")):
                bad.append("%s:%s" % (p.relative_to(ROOT).as_posix(), n.name))
chk(not bad, "B @korea_only 는 처리기(_action_·_vm_·_on_)에만 — 공용 도우미에 붙이지 않는다", str(bad))

print()
print("FAIL", len(fails), fails) if fails else print("ALL PASS")
sys.stdout.flush()
os._exit(1 if fails else 0)
