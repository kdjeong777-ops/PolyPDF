# -*- coding: utf-8 -*-
"""그림 전용 PDF 에서 책갈피창 선택·우클릭이 창을 세우지 않는다 (261107-19, 응답성 SOT §6 `get_text` 행·§4 ③·§7.5).

사용자 보고: "이전보다 책갈피 창을 선택하고, 옵션을 띄우는 경우 오래걸려 … 사진을 선택해서 만든 pdf파일들".
그 파일들은 쪽마다 2048px FlateDecode 그림 띠뿐이고, 글 자리만 쓰는 `get_text("rawdict")` 가 기본 플래그로
쪽의 그림을 모두 풀어 쪽당 0.8~1.4초 — 본문의 글 자리(`_view_src`)와 텍스트 창 워커가 각각 그만큼 서서 최장 2초+.
A. `viewer/`(`_vendor` 제외)에 그림을 푸는 기본 플래그의 `get_text("rawdict"|"dict"|"html"|"xhtml")` 가 없다
B. `text_extract2.text_dict` 의 글 블록이 기본 플래그와 같다(글 PDF) — 결과는 그대로
C. 그림 전용 쪽(`test_fixtures.image_strips_pdf`)의 `page_lines` 가 빠르다(< 0.3초, 수정 전 ~1.5초)
D. 실제 `_on_activated` 로 그 파일을 고를 때 20ms 박동 최장 < 1초
E. 처음 보는 파일 우클릭: 메인에서 파일을 열지 않고(`_probe_pdf` 0번) 메뉴를 띄우며 배경 검사 줄에 넣는다 —
   결과가 오면 암호 표식이 붙고 다음 우클릭 메뉴에 '암호 입력' 이 있다
"""
import os, sys, re, shutil, tempfile, time, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_text_dict_noimg_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "그림 전용 PDF", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=10.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        time.sleep(0.01)
    return cond is None


class Beat:
    def __init__(self):
        self.t = QTimer(); self.t.setInterval(20); self.t.timeout.connect(self._tick)
        self.reset(); self.t.start()

    def reset(self):
        self.last = time.monotonic(); self.worst = 0.0

    def _tick(self):
        now = time.monotonic(); self.worst = max(self.worst, now - self.last); self.last = now


# ── A ──
CALL = re.compile(r"""\.get_text\(\s*(["'])(rawdict|dict|html|xhtml)\1""")
bad = []
for p in sorted((Path(HERE) / "viewer").rglob("*.py")):
    if "_vendor" in p.parts:
        continue
    src = p.read_text(encoding="utf-8")
    for m in CALL.finditer(src):
        depth, i = 0, m.start() + len(".get_text")
        while i < len(src):                       # 괄호 짝까지 — 그 호출 안에 flags= 가 있나
            depth += {"(": 1, ")": -1}.get(src[i], 0)
            i += 1
            if depth == 0:
                break
        if "flags" not in src[m.start():i]:
            bad.append("%s:%d" % (p.relative_to(HERE), src.count("\n", 0, m.start()) + 1))
chk(not bad, "A viewer/ 에 그림을 푸는 기본 플래그의 get_text(rawdict·dict·html·xhtml) 가 없다 — text_extract2.text_dict 를 쓴다", str(bad))

import fitz
import test_fixtures as tf
from viewer import text_extract2 as tx

# ── B ──
def text_blocks(d):
    return [(tuple(round(v, 2) for v in b["bbox"]), [[(s.get("text") if "text" in s else "".join(c["c"] for c in s.get("chars", [])),
                                                      round(s["size"], 2)) for s in ln["spans"]] for ln in b["lines"]])
            for b in d["blocks"] if b.get("type") == 0]

doc = fitz.open(tf.text_pdf())
same = hasattr(tx, "text_dict")
for i in ((0, 5, 29) if same else ()):
    pg = doc[i]
    for raw in (True, False):
        a = text_blocks(pg.get_text("rawdict" if raw else "dict"))
        b = text_blocks(tx.text_dict(pg, raw=raw))
        same = same and a == b and len(a) > 0
chk(same, "B text_dict 가 있고 글 블록(자리·글·크기)이 기본 플래그와 같다(글 PDF 세 쪽, rawdict·dict)")
doc.close()

# ── C ──
img_pdf = tf.image_strips_pdf()
doc = fitz.open(img_pdf)
t = time.perf_counter()
rows = tx.page_lines(doc, img_pdf, 0, tables="off", join_lines=False)
dt = time.perf_counter() - t
chk(dt < 0.3, "C 그림 전용 쪽의 page_lines 가 빠르다 (< 0.3초)", "%.2f초" % dt)
doc.close()

# ── D·E ──
tmp = Path(tempfile.mkdtemp(prefix="polypdf_noimg_"))
try:
    folder = tmp / "f"; folder.mkdir()
    shutil.copy2(img_pdf, folder / "a_photo.pdf")
    enc = fitz.open(tf.text_pdf())
    enc.save(str(folder / "b_locked.pdf"), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="own", user_pw="usr")
    enc.close()

    from viewer.app import MainWindow
    from viewer.widgets import bookmark_tree as bt
    menus = []

    def fake_exec(self, *a, **k):
        def texts(m):
            out = []
            for act in m.actions():
                out.append(act.text())
                if act.menu() is not None:
                    out += texts(act.menu())
            return out
        menus.append(texts(self))
        return None
    QMenu.exec = fake_exec

    main_opens = []
    _orig_probe = bt.BookmarkTree._probe_pdf

    def probe_spy(self, p):
        if threading.current_thread() is threading.main_thread():
            main_opens.append(str(p))
        return _orig_probe(self, p)
    bt.BookmarkTree._probe_pdf = probe_spy

    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1400, 900); mw.show(); pump(timeout=1.0)
    tree = mw.bookmark_tree

    def row(name):
        stack = [tree.tree.topLevelItem(i) for i in range(tree.tree.topLevelItemCount())]
        while stack:
            y = stack.pop()
            if tree._is_file_node(y) and Path(str(y.data(0, tree.DATA_FILE))).name == name:
                return y
            stack += [y.child(j) for j in range(y.childCount())]
        return None

    # E 먼저 — 폴더를 열자마자(배경 검사 전) 처음 보는 행을 우클릭
    mw.open_folder(folder)
    it_b = row("b_locked.pdf")
    chk(it_b is not None, "E 잠긴 파일 행이 있다")
    if it_b is not None:
        tree._probe_cache = {}
        it_b.setData(0, tree.DATA_PROBED, False)
        tree.probe_provider = None
        main_opens.clear(); menus.clear()
        pos = tree.tree.visualItemRect(it_b).center()
        tree._on_tree_context_menu(pos)
        chk(menus and not main_opens, "E 처음 보는 파일 우클릭 — 메인에서 파일을 열지 않고 메뉴를 띄운다", str(main_opens))
        chk(any(p == str(folder / "b_locked.pdf") for _i, p in tree._probe_queue) or tree._probe_worker is not None
            or str(folder / "b_locked.pdf") in (tree._probe_pending or {}),
            "E 그 행을 배경 검사 줄에 넣는다")
        chk(pump(lambda: bool(it_b.data(0, tree.DATA_ENCRYPTED)), timeout=10.0), "E 배경 검사 결과가 오면 암호 표식이 붙는다")
        menus.clear()
        tree._on_tree_context_menu(pos)
        chk(menus and any("암호 입력" in t for t in menus[0]), "E 다음 우클릭 메뉴에 '암호 입력'", str(menus[:1])[:200])
        chk(not main_opens, "E 두 번째 우클릭도 파일을 열지 않는다(캐시)", str(main_opens))

    # D
    it_a = row("a_photo.pdf")
    chk(it_a is not None, "D 그림 전용 파일 행이 있다")
    if it_a is not None:
        pump(timeout=1.0)
        beat = Beat()
        tree.tree.setCurrentItem(it_a)
        tree._on_activated(it_a, 0)
        pump(timeout=6.0)
        mv = mw._mv[0]
        chk(mv._doc is not None and Path(str(mv._doc.path)).name == "a_photo.pdf", "D 본문에 그 파일이 열렸다")
        chk(beat.worst < 1.0, "D 그림 전용 PDF 를 골라 본문이 열리는 동안 메인 최장 정지 < 1초", "%.2f초" % beat.worst)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(tmp), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
