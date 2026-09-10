# -*- coding: utf-8 -*-
"""260911: 본문 읽기 모드 — 어디까지 읽고 어떻게 되풀이하나 (영상·음성 SOT §1.1).

사용자 보고: **"읽기가 전체로 선택되어 있는데, 다음 페이지로 안 넘어가고 다시 해당
페이지를 읽어."** 그리고 규격을 확정해 줬다.

  1회      = 지금 쪽 한 번
  연속      = 지금 쪽 반복
  전체      = 1쪽~끝 한 번
  전체연속   = 1쪽~끝을 되풀이

종전 규격은 전체·전체연속이 **지금 쪽 → 마지막 쪽**이었다. 마지막 쪽에서 전체연속을
걸면 그 쪽만 끝없이 되풀이했고, 18쪽에서 전체를 걸면 앞 18쪽은 영영 안 읽혔다.
"""
import os, sys, inspect

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject
app = QApplication.instance() or QApplication([])
from viewer.widgets.read_aloud import ReadAloud


class _Status:
    def showMessage(self, *a, **k):
        pass


class _MW(QObject):
    status = _Status()
    main_view = None


def mk(mode, total=21):
    class _Doc:
        page_count = total

    class _View:
        def __init__(self):
            self._doc = _Doc()
            self._page = 0

        def current_page(self):
            return self._page

    r = ReadAloud(_MW())
    r.set_target(_View(), 0)
    r.mode = mode
    return r


print("=== (1) 쪽 목록은 한 곳에서 만든다 ===")
r = mk("전체")
chk(hasattr(r, "_page_plan"), "(1) `_page_plan` 이 있다")
src = inspect.getsource(ReadAloud.start)
chk("_page_plan" in src, "(1) 시작할 때 그것을 쓴다")
rs = inspect.getsource(ReadAloud._restart_at_page)
chk("_page_plan" in rs,
    "(1) 읽는 중 쪽을 옮겼을 때도 같은 규칙 — 두 곳이 어긋나면 모드가 달라진다")
chk("all_pages" not in src and "all_pages" not in rs,
    "(1) 옛 '지금 쪽부터' 셈이 남아 있지 않다")

print()
print("=== (2) 모드마다 읽는 범위 (§1.1) ===")
cases = [("1회", 18, [18], False),
         ("연속", 18, [18], True),
         ("전체", 18, list(range(21)), False),
         ("전체연속", 18, list(range(21)), True)]
for mode, start, want_pages, want_repeat in cases:
    r = mk(mode)
    pages, pi = r._page_plan(start)
    rep = r.mode in ("연속", "전체연속")
    chk(pages == want_pages, "(2) %s 의 읽을 쪽" % mode,
        "%d개 %s" % (len(pages), pages[:4]))
    chk(pi == 0, "(2) %s 는 목록 처음부터 시작" % mode, str(pi))
    chk(rep == want_repeat, "(2) %s 의 되풀이 여부" % mode, str(rep))

print()
print("=== (3) 사용자가 본 결함이 재현되지 않는다 ===")
r = mk("전체연속")
pages, pi = r._page_plan(20)          # 마지막 쪽에서 걸었다
chk(len(pages) == 21, "(3) 마지막 쪽에서 전체연속 — 그 쪽만 되풀이하지 않는다",
    "%d쪽" % len(pages))
r = mk("전체")
pages, _ = r._page_plan(20)
chk(len(pages) == 21, "(3) 마지막 쪽에서 전체 — 문서를 다 읽는다", "%d쪽" % len(pages))
r = mk("전체")
pages, _ = r._page_plan(18)
chk(pages[0] == 0, "(3) 18쪽에서 걸어도 1쪽부터 — 앞쪽이 빠지지 않는다", str(pages[:3]))

print()
print("=== (4) 가장자리 ===")
r = mk("전체", total=1)
chk(r._page_plan(0) == ([0], 0), "(4) 1쪽짜리 문서", str(r._page_plan(0)))
r = mk("1회", total=5)
chk(r._page_plan(99) == ([4], 0), "(4) 범위 밖 쪽은 마지막으로 여민다",
    str(r._page_plan(99)))
chk(r._page_plan(-3) == ([0], 0), "(4) 음수도 여민다", str(r._page_plan(-3)))

print()
print("=== (5) 다 읽으면 시작한 쪽으로 돌아온다 (§1.1) ===")
done = inspect.getsource(ReadAloud._tick)
chk("_home_page" in done, "(5) 시작한 쪽을 기억해 둔다")
st = inspect.getsource(ReadAloud.start)
chk("_home_page = start_page" in st, "(5) 누른 자리를 기억한다")
chk("current_page() != int(home)" in done,
    "(5) 이미 그 쪽이면 옮기지 않는다 — 쓸데없이 한 번 더 움직이지 않게")
chk(done.index("self.stop()") < done.index("go_to_page"),
    "(5) 멈춘 뒤에 옮긴다 — 옮기다 다시 읽히지 않게")

print()
print("=== (6) 강조는 OCR 낱말이 없어도 된다 (§1.2) ===")
chk(hasattr(ReadAloud, "_layer_words"), "(6) 글자층 낱말을 쓸 길이 있다")
lw = inspect.getsource(ReadAloud._layer_words)
chk('get_text("words")' in lw, "(6) PDF 글자층의 낱말 상자를 읽는다")
chk("words_in_reading_order" in lw,
    "(6) 그 낱말도 단 차례로 — 읽는 글과 어긋나면 강조가 튄다")
lo = inspect.getsource(ReadAloud._load_owords)
chk("if not self._owords:" in lo and "_layer_words" in lo,
    "(6) study.db 에 낱말이 없을 때만 물러선다")
chk("self._oscale = 1.0" in lo, "(6) 글자층 좌표는 이미 pt 라 배율 1")

print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for msg in fails:
    print(" -", msg)
sys.stdout.flush()
os._exit(0 if not fails else 1)
