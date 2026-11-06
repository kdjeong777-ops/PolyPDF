# -*- coding: utf-8 -*-
"""261106-23(응답성 SOT §4.1 '목록의 파일마다 열지 않는다'): 메인 스레드에서 **목록의 파일마다** zip·폴더·그림을 열지 않는다.

책갈피창 PDF 모드 목록 거르기(`_list_keep`)가 zip 마다 zip 을 열고, zip 줄을 펼칠 때 메인에서 zip 을 열었다(지휘 점검).
같은 꼴이 사진 크롭 창(261106-14)·사진 우클릭 메뉴(261106-21)에서도 났다 — 규칙은 있었지만 한 곳에서만 검사했다.

A (소스) — 메인에서 도는 코드(`viewer/widgets/*.py`·`viewer/*_controller.py`·`viewer/app.py`, 워커 클래스와 `run` 은 빼고)에서
  ① 반복문·내포(for·while·comprehension) 안이나 ② 걸러내기 함수(안쪽 `def`·`lambda`, `_list_keep`) 안에서
  zip 을 여는 함수(`zipfile.ZipFile`·`zip_unpack.members`·`has_pdfs`·`has_kind`·`photo_zip.has_photos`·`photo_members`·`cached_to_member`)를 부르면 실패.
  메뉴 만들기·목록 거르기(이름에 menu·context·_action·keep·_fill_ ·_render)에서는 `os.scandir`·`os.listdir`·`Image.open` 도.
  기억만 보는 `peek_*` 은 괜찮다. 다른 세션이 고치는 중인 곳은 `PENDING` 에 작업 번호와 함께(끝나면 뺀다).
B (실제 흐름) — PDF 모드 책갈피창에 zip 이 든 폴더를 열 때와 zip 줄을 펼칠 때 메인 스레드가 zip 을 열지 않는다
  (`zipfile.ZipFile.__init__` 을 감싸 메인에서 불린 횟수를 센다). 목록에는 PDF 든 zip 만, 펼치면 안의 PDF.
C — `zip_unpack.members` 는 같은 zip 을 다시 열지 않는다(기억), 묶음 접미사는 `share_bundle.SUFFIX` 한 곳.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
FAILS: list = []


def chk(ok, msg):
    print(("  OK  " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


# ── A. 소스 ──────────────────────────────────────────────────────────────
ZIP_OPENERS = {"ZipFile", "members", "has_pdfs", "has_kind", "has_photos", "photo_members", "cached_to_member",
               "_read_members"}
FS_OPENERS = {"scandir", "listdir", "Image.open"}
LISTY = ("menu", "context", "_action", "keep", "_fill_", "_render")
# 다른 세션이 고치는 중 — (파일, 함수): 작업 번호. 고친 뒤 빼야 한다(빼지 않으면 '고쳐졌는데 아직 목록에' 로 실패).
PENDING: dict = {}       # 예: {("viewer/photo_controller.py", "_zip_unpack_cached"): "261106-21"} — 261106-21 에서 고쳐 뺐다


def _callee(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        if isinstance(f.value, ast.Name) and f.value.id == "Image" and f.attr == "open":
            return "Image.open"
        return f.attr
    return ""


def _scan_file(path: Path) -> list:
    rel = path.relative_to(ROOT).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []

    def walk(node, func, cls, in_loop, in_filter):
        for ch in ast.iter_child_nodes(node):
            f2, l2, flt2, c2 = func, in_loop, in_filter, cls
            if isinstance(ch, ast.ClassDef):
                c2 = ch.name
                if ch.name.endswith("Worker") or ch.name.endswith("Thread"):
                    continue                                  # 배경 스레드에서 돈다
            elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if ch.name == "run":
                    continue
                if func is None:
                    f2, l2, flt2 = ch.name, False, ch.name == "_list_keep"
                else:
                    flt2 = True                               # 안쪽 def — 목록마다 불리는 걸러내기
            elif isinstance(ch, ast.Lambda) and func is not None:
                flt2 = flt2 or False
            elif isinstance(ch, (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                l2 = True
            elif isinstance(ch, ast.Call) and func is not None:
                name = _callee(ch)
                listy = any(k in func.lower() for k in LISTY)
                bad = (name in ZIP_OPENERS and (in_loop or in_filter)) or \
                      (name in FS_OPENERS and listy and (in_loop or in_filter))
                if bad:
                    hits.append((rel, func, ch.lineno, name))
            walk(ch, f2, c2, l2, flt2)

    walk(tree, None, None, False, False)
    return hits


files = sorted(set((ROOT / "viewer" / "widgets").glob("*.py")) | set((ROOT / "viewer").glob("*_controller.py"))
               | {ROOT / "viewer" / "app.py"})
all_hits = []
for p in files:
    all_hits.extend(_scan_file(p))
new = [h for h in all_hits if (h[0], h[1]) not in PENDING]
chk(not new, "A 메인 코드에서 목록의 파일마다 zip·폴더를 열지 않는다"
    + ("" if not new else " — " + "; ".join("%s:%d %s() %s" % (h[0], h[2], h[1], h[3]) for h in new)))
stale = [k for k in PENDING if not any((h[0], h[1]) == k for h in all_hits)]
chk(not stale, "A PENDING 목록이 낡지 않았다(고쳐진 곳은 뺀다)" + ("" if not stale else " — " + ", ".join(
    "%s %s (%s)" % (k[0], k[1], PENDING[k]) for k in stale)))

# ── C. 기억·접미사 ───────────────────────────────────────────────────────
from viewer import share_bundle, zip_unpack  # noqa: E402

chk(not hasattr(zip_unpack, "BUNDLE_SUFFIX") and zip_unpack.is_bundle is share_bundle.is_bundle,
    "C 묶음 접미사는 share_bundle 한 곳(zip_unpack 은 가져다 쓴다)")

tmp = Path(tempfile.mkdtemp(prefix="polypdf_mainlist_"))
import fitz  # noqa: E402


def _pdf_bytes(text):
    d = fitz.open()
    d.new_page().insert_text((72, 72), text)
    b = d.tobytes()
    d.close()
    return b


fold = tmp / "folder"
fold.mkdir()
(fold / "a.pdf").write_bytes(_pdf_bytes("a"))
with zipfile.ZipFile(fold / "has_pdf.zip", "w") as z:
    z.writestr("in/one.pdf", _pdf_bytes("one"))
    z.writestr("in/two.pdf", _pdf_bytes("two"))
    z.writestr("note.txt", "x")
with zipfile.ZipFile(fold / "no_pdf.zip", "w") as z:
    z.writestr("note.txt", "x")
with zipfile.ZipFile(fold / ("send" + share_bundle.SUFFIX), "w") as z:
    z.writestr("x.pdf", _pdf_bytes("x"))

MAIN = threading.main_thread()
opens = {"main": 0, "bg": 0}
_orig_init = zipfile.ZipFile.__init__


def _counting_init(self, *a, **k):
    opens["main" if threading.current_thread() is MAIN else "bg"] += 1
    return _orig_init(self, *a, **k)


zipfile.ZipFile.__init__ = _counting_init

_forget = getattr(zip_unpack, "toc_forget", lambda *a: None)     # 수정 전 코드에는 없다(그래도 B 까지 돌려 실패를 본다)
_forget()
zp = str(fold / "has_pdf.zip")
opens["main"] = 0
m1 = zip_unpack.members(zp, (".pdf",))
m2 = zip_unpack.members(zp, (".pdf",))
chk(len(m1) == 2 and m1 == m2 and opens["main"] == 1, "C members 는 같은 zip 을 한 번만 연다 (열기 %d)" % opens["main"])
_forget()
paced = []
try:
    out = tmp / "out"
    w_, s_, st_ = zip_unpack.unpack(zp, out, pace=lambda: paced.append(1))
    chk(len(w_) == 3 and len(paced) >= 2, "C 풀기는 항목 사이에 양보한다 (pace %d번, 쓴 파일 %d)" % (len(paced), len(w_)))
except TypeError as e:
    chk(False, "C 풀기는 항목 사이에 양보한다 — %s" % e)

# ── B. 실제 흐름 — PDF 모드 책갈피창 ────────────────────────────────────
from PyQt6.QtCore import QCoreApplication, QStandardPaths  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_mainlist_%d" % os.getpid())
app = QApplication.instance() or QApplication(sys.argv)
import modal_guard  # noqa: E402

modal_guard.install()
from viewer.widgets.bookmark_tree import BookmarkTree  # noqa: E402


def pump(cond, sec=10.0):
    import time
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    app.processEvents()
    return cond()


bt = BookmarkTree()
opens["main"] = 0
bt.load_folder(fold)


def _names():
    return sorted(Path(str(it.data(0, bt.DATA_FILE))).name for it in bt._iter_file_nodes())


ok = pump(lambda: _names() == ["a.pdf", "has_pdf.zip"], 15)
chk(ok, "B 목록 — PDF 와 PDF 든 zip 만 (%s)" % _names())
chk(opens["main"] == 0, "B 폴더 열기 동안 메인에서 zip 을 열지 않았다 (메인 %d번, 배경 %d번)" % (opens["main"], opens["bg"]))

zitem = next((it for it in bt._iter_file_nodes() if str(it.data(0, bt.DATA_FILE)).endswith("has_pdf.zip")), None)
opens["main"] = 0
if zitem is not None:
    zitem.setExpanded(True)
    bt._on_item_expanded(zitem)


def _kids():
    if zitem is None:
        return []
    return sorted(zitem.child(i).text(0) for i in range(zitem.childCount())
                  if zitem.child(i).data(0, bt.DATA_ZIP_MEMBER))


chk(pump(lambda: _kids() == ["one", "two"], 10), "B zip 줄 펼치기 — 안의 PDF (%s)" % _kids())
chk(opens["main"] == 0, "B zip 줄 펼치기 동안 메인에서 zip 을 열지 않았다 (메인 %d번)" % opens["main"])

# 기억이 없을 때 펼치면 — '…' 를 두고 배경에서 읽어 채운다
_forget()
opens["main"] = 0
if zitem is not None:
    zitem.setData(0, bt.DATA_TOC_LOADED, False)
    bt._on_item_expanded(zitem)
chk(pump(lambda: _kids() == ["one", "two"], 10) and opens["main"] == 0,
    "B 기억이 없을 때 펼치기 — 배경에서 읽어 채운다 (메인 %d번, %s)" % (opens["main"], _kids()))

zipfile.ZipFile.__init__ = _orig_init
bt.deleteLater()
app.processEvents()

print()
if FAILS:
    print("FAILED %d" % len(FAILS))
    sys.exit(1)
print("ALL PASS")
sys.exit(0)
