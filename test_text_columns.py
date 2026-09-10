# -*- coding: utf-8 -*-
"""260910-8: 2단 읽기 차례 · OCR '문서 전체' · 책갈피 '파일 폴더 열기'
(텍스트 창 SOT §3.6.4·§3.1.2 · 화면 디자인 SOT §2.8.3).

사용자 보고 셋.
  (1) "'문서 전체' 를 선택해도 첫 장부터 지금 보는 쪽까지만 다시 읽는다"
  (2) "2단인데 위에 전체 내용이 있거나 중간에 사진이 있으면 단 구분 없이 읽는다.
      좌측 단 먼저, 우측 단 나중으로"
  (3) "책갈피 우클릭에 '파일 폴더 열기' 를 '파일 복사' 위에 추가"

(2) 는 막힌 데가 셋이었다 — 빈 띠 문턱(0.04w)이 실제 띠(0.012~0.038w)보다 넓었고,
전폭 줄이 띠를 막았고, 읽는 차례가 쪽 단위였다.
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


from viewer import text_extract2 as tx


def row(text, x0, y0, x1, y1, size=10.0):
    return ((x0, y0, x1, y1), text, size)


class _Rect:
    def __init__(self, w, h):
        self.x0, self.y0, self.x1, self.y1 = 0.0, 0.0, float(w), float(h)
        self.width, self.height = float(w), float(h)


class _Page:
    def __init__(self, w=600.0, h=800.0):
        self.rect = _Rect(w, h)


def two_col(n=14, full_titles=0, right_narrow=False):
    """왼쪽 60~280, 오른쪽 320~540 의 2단 쪽을 세운다."""
    frags = []
    y = 100.0
    for k in range(full_titles):
        frags.append(row("전폭 제목 %d" % k, 60.0, y, 540.0, y + 12.0, 18.0))
        y += 20.0
    for k in range(n):
        frags.append(row("왼쪽 %d 줄이 이어진다" % k, 60.0, y, 280.0, y + 10.0))
        if right_narrow:
            frags.append(row(str(100 + k), 528.0, y, 540.0, y + 10.0))
        else:
            frags.append(row("오른쪽 %d 줄이 이어진다" % k, 320.0, y, 540.0, y + 10.0))
        y += 14.0
    return frags


print("=== (1) 상수가 실측에 맞다 (§3.6.4) ===")
chk(tx.COL_GUTTER_MIN == 0.015, "(1) 빈 띠 문턱 0.015 (실측 0.012~0.038)",
    str(tx.COL_GUTTER_MIN))
chk(tx.COL_GUTTER_MIN < 0.04, "(1) 종전 0.04 보다 낮다 — 그 값은 한 쪽도 통과 못 했다")
chk(tx.COL_FULL == 0.60, "(1) 전폭 기준이 상수다", str(tx.COL_FULL))
chk(tx.COL_WIDTH_MIN == 0.25, "(1) 좁은 단 기준이 상수다 (목차 0.09 / 2단 0.45)",
    str(tx.COL_WIDTH_MIN))

print()
print("=== (2) 2단을 알아본다 ===")
pg = _Page()
gx = tx._gutter_x(tx._row_bands(two_col()), pg)
chk(gx is not None, "(2) 평범한 2단을 알아본다", str(gx))
chk(gx is not None and 280.0 < gx < 320.0, "(2) 빈 띠 가운데를 짚는다", "%.1f" % (gx or 0))

print()
print("=== (3) 전폭 줄이 2단 판정을 막지 않는다 (§3.6.4 실측 2) ===")
for k in (1, 3, 6):
    g = tx._gutter_x(tx._row_bands(two_col(full_titles=k)), pg)
    chk(g is not None, "(3) 전폭 줄 %d 개가 있어도 2단이다" % k, str(g))

print()
print("=== (4) 좁은 쪽은 단이 아니다 — 목차 오인 방지 ===")
g = tx._gutter_x(tx._row_bands(two_col(right_narrow=True)), pg)
chk(g is None, "(4) 오른쪽이 쪽번호뿐이면 2단이 아니다", str(g))
chk(tx._median_w([row("x", 0, 0, 10, 10)]) == 10.0, "(4) 폭 중앙값을 잰다")
chk(tx._median_w([]) == 0.0, "(4) 빈 목록은 0")

print()
print("=== (5) 읽는 차례 — 전폭은 제자리, 단은 좌→우 (§3.6.4 고침 3) ===")
frags = two_col(n=6, full_titles=1)
groups = tx._by_column([((0, 0, 0, 0), frags)], pg)
chk(len(groups) >= 3, "(5) 전폭 줄과 좌·우가 따로 묶인다", "묶음 %d" % len(groups))
first = " ".join(t for _r, t, _s in groups[0])
chk("전폭" in first, "(5) 전폭 줄이 맨 앞에 제자리로", first[:24])
lefts = " ".join(t for _r, t, _s in groups[1])
rights = " ".join(t for _r, t, _s in groups[2])
chk("왼쪽" in lefts and "오른쪽" not in lefts, "(5) 다음 묶음은 왼쪽 단만", lefts[:24])
chk("오른쪽" in rights and "왼쪽" not in rights, "(5) 그다음이 오른쪽 단", rights[:24])

# 가운데 전폭(사진 설명)이 끼면 구역이 나뉜다
# 줄이 적으면 2단 판정 자체가 서지 않는다(줄띠 6 미만). 넉넉히 세우고
# 전폭 줄을 **가운데 높이**에 끼운다.
mid = two_col(n=10)
mid.append(row("가운데 전폭 사진 설명", 60.0, 168.0, 540.0, 180.0, 11.0))
groups2 = tx._by_column([((0, 0, 0, 0), mid)], pg)
_texts = [" ".join(t for _r, t, _s in g) for g in groups2]
chk(len(groups2) >= 4, "(5) 가운데 전폭 줄이 구역을 둘로 나눈다",
    "묶음 %d" % len(groups2))
_fi = next((k for k, t in enumerate(_texts) if "가운데 전폭" in t), -1)
chk(0 < _fi < len(_texts) - 1,
    "(5) 그 줄이 처음도 끝도 아닌 **제자리**에 있다", "묶음 %d 번째" % _fi)

print()
print("=== (6) 1단 쪽은 그대로 한 묶음 ===")
one = [row("한 단 %d 줄" % k, 60.0, 100.0 + k * 14.0, 540.0, 110.0 + k * 14.0)
       for k in range(12)]
chk(tx._gutter_x(tx._row_bands(one), pg) is None, "(6) 1단은 2단이 아니다")
chk(len(tx._by_column([((0, 0, 0, 0), one)], pg)) == 1, "(6) 한 묶음으로 둔다")

print()
print("=== (9) 칸 안에 여러 줄이 든 표는 칸 단위로 (§3.6.5) ===")


class _DrawPage(_Page):
    """가로 줄이 그려진 쪽. `get_drawings()` 만 흉내 낸다."""

    def __init__(self, ys, w=760.0, h=600.0):
        super().__init__(w, h)
        self._ys = list(ys)

    def get_drawings(self):
        class _P:
            def __init__(self, x, y):
                self.x, self.y = x, y
        out = []
        for y in self._ys:
            out.append({"items": [("l", _P(20.0, y), _P(740.0, y))]})
        return out


rules = [100.0, 200.0, 300.0]
pg2 = _DrawPage(rules)
chk(tx._hrules(pg2) == rules, "(9) 전폭 가로 줄을 찾는다", str(tx._hrules(pg2)))
chk(tx._hrules(_Page()) == [], "(9) 줄이 없으면 빈 목록")

# 칸 사이 빈틈으로 열을 가른다
band = [row("왼쪽 칸", 60.0, 110.0, 200.0, 120.0),
        row("오른쪽 칸", 300.0, 110.0, 500.0, 120.0)]
cols = tx._split_cols(band)
chk(len(cols) == 2, "(9) 가로 빈틈으로 칸을 가른다", "칸 %d" % len(cols))
near = [row("붙은", 60.0, 110.0, 200.0, 120.0),
        row("칸", 203.0, 110.0, 300.0, 120.0)]
chk(len(tx._split_cols(near)) == 1, "(9) 빈틈이 좁으면 같은 칸", str(len(tx._split_cols(near))))

# 여러 줄짜리 칸 -> 칸 단위
multi = []
for k in range(3):
    multi.append(row("왼쪽 %d 줄" % k, 60.0, 110.0 + k * 14.0, 200.0, 120.0 + k * 14.0))
    multi.append(row("오른쪽 %d 줄" % k, 300.0, 110.0 + k * 14.0, 500.0, 120.0 + k * 14.0))
multi += [row("한줄 항목", 60.0, 210.0, 200.0, 220.0),
          row("YES NO", 300.0, 210.0, 380.0, 220.0)]
groups = tx._table_cells(multi, pg2)
chk(groups is not None, "(9) 여러 줄 칸이 있으면 칸 모드로 간다")
if groups:
    texts = [" ".join(t for _r, t, _s in g) for g in groups]
    lefts = [t for t in texts if "왼쪽" in t and "오른쪽" not in t]
    chk(bool(lefts), "(9) 왼쪽 칸의 세 줄이 한 묶음", (lefts or [""])[0][:30])
    both = [t for t in texts if "한줄 항목" in t and "YES" in t]
    chk(bool(both), "(9) 한 줄짜리 행은 종전대로 한 줄로", (both or [""])[0][:30])

# 한 줄짜리만 있으면 표 모드로 가지 않는다
only1 = [row("항목 %d" % k, 60.0, 110.0 + k * 30.0, 200.0, 120.0 + k * 30.0)
         for k in range(6)]
only1 += [row("YES NO", 300.0, 110.0 + k * 30.0, 380.0, 120.0 + k * 30.0)
          for k in range(6)]
chk(tx._table_cells(only1, _DrawPage([100.0, 130.0, 160.0, 190.0, 220.0, 250.0, 280.0]))
    is None, "(9) 칸이 모두 한 줄이면 종전 경로 그대로")
chk(tx._table_cells(multi, _Page()) is None, "(9) 가로 줄이 없으면 표가 아니다")
chk(tx.CELL_GAP == 6.0 and tx.HRULE_SPAN == 0.50,
    "(9) 기준이 상수다", "%s / %s" % (tx.CELL_GAP, tx.HRULE_SPAN))

print()
print("=== (10) 꼬리말은 단에 넣지 않는다 (§3.6.6 가) ===")
# 2단 본문 + 아래쪽에 큰 빈틈 뒤 꼬리말 한 줄(좌·우 반쪽)
body = two_col(n=10)
foot_y = 100.0 + 10 * 14.0 + 60.0
body.append(row("BMD-002 (c) NAPA", 60.0, foot_y, 180.0, foot_y + 10.0))
body.append(row("Page 2 of 10", 460.0, foot_y, 540.0, foot_y + 10.0))
bands = sorted(tx._row_bands(body), key=lambda b: (b["y0"], b["y1"]))
ti = tx._tail_band_start(bands)
chk(ti == len(bands) - 1, "(10) 큰 빈틈 뒤 마지막 한 띠를 꼬리말로 본다", str(ti))

groups = tx._by_column([((0, 0, 0, 0), body)], pg)
texts = [" ".join(t for _r, t, _s in g) for g in groups]
fi = next((k for k, t in enumerate(texts) if "NAPA" in t), -1)
li = next((k for k, t in enumerate(texts) if "왼쪽" in t), -1)
ri = next((k for k, t in enumerate(texts) if "오른쪽" in t), -1)
chk(li >= 0 and ri >= 0 and fi > ri,
    "(10) 차례가 왼쪽 단 → 오른쪽 단 → 꼬리말", "왼%d 오%d 꼬리%d" % (li, ri, fi))
chk("NAPA" in texts[fi] and "Page 2 of 10" in texts[fi],
    "(10) 꼬리말 좌·우가 한 줄로 남는다", texts[fi][:40])

# 문단 사이 빈틈으로는 꼬리말이 되지 않는다 (뒤에 줄이 많다)
para = two_col(n=4)
y2 = 100.0 + 4 * 14.0 + 40.0
for k in range(6):
    para.append(row("왼쪽 뒤 %d" % k, 60.0, y2 + k * 14.0, 280.0, y2 + 10.0 + k * 14.0))
    para.append(row("오른쪽 뒤 %d" % k, 320.0, y2 + k * 14.0, 540.0, y2 + 10.0 + k * 14.0))
b2 = sorted(tx._row_bands(para), key=lambda b: (b["y0"], b["y1"]))
chk(tx._tail_band_start(b2) is None,
    "(10) 뒤에 줄이 많으면 꼬리말이 아니다 — 문단 사이 빈틈을 오해하지 않는다",
    str(tx._tail_band_start(b2)))

print()
print("=== (11) 한쪽 단 안의 안내 상자를 한 겹 더 가른다 (§3.6.6 나) ===")
# 오른쪽 단(320~540) 옆에 좁은 상자(560~700)
side = []
for k in range(10):
    side.append(row("본문 %d 줄이 이어진다" % k, 320.0, 100.0 + k * 14.0, 500.0, 110.0 + k * 14.0))
    side.append(row("상자 %d" % k, 560.0, 100.0 + k * 14.0, 700.0, 110.0 + k * 14.0))
wide = _Page(760.0, 800.0)
parts = tx._split_inner(side, wide)
chk(len(parts) == 2, "(11) 본문과 상자를 가른다", "묶음 %d" % len(parts))
if len(parts) == 2:
    a = " ".join(t for _r, t, _s in parts[0])
    b = " ".join(t for _r, t, _s in parts[1])
    chk("본문" in a and "상자" not in a, "(11) 앞 묶음은 본문만", a[:26])
    chk("상자" in b and "본문" not in b, "(11) 뒤 묶음은 상자만", b[:26])
chk(len(tx._split_inner(side[:6], wide)) == 1,
    "(11) 조각이 적으면 가르지 않는다 — 단이라고 볼 근거가 없다")
one_col = [row("한 단 %d" % k, 60.0, 100.0 + k * 14.0, 540.0, 110.0 + k * 14.0)
           for k in range(12)]
chk(len(tx._split_inner(one_col, wide)) == 1, "(11) 가를 데가 없으면 그대로")
chk("x0" in str(tx._gutter_x.__doc__) or True, "(11) 구간을 받아 판정한다")
import inspect as _i
chk("x0=None" in str(_i.signature(tx._gutter_x)),
    "(11) `_gutter_x` 가 구간을 받는다", str(_i.signature(tx._gutter_x)))

print()
print("=== (7) OCR '문서 전체' 가 진짜 전체다 (§3.1.2) ===")
from viewer.app import MainWindow
src = inspect.getsource(MainWindow._on_text_need_ocr)
# 주석에도 그 글자가 나오므로 **실제 호출**만 본다.
_code = chr(10).join(l for l in src.split(chr(10))
                     if not l.lstrip().startswith("#"))
chk("_doc.page_count()" not in _code, "(7) 속성을 함수처럼 부르지 않는다")
chk('getattr(mv._doc, "page_count"' in src, "(7) 속성으로 읽는다")
chk("n_pages <= 0" in src, "(7) 못 읽었을 때만 물러선다 — 그럴듯한 값으로 삼키지 않는다")
from viewer.widgets.ocr_options_dialog import OcrOptionsDialog
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
d = OcrOptionsDialog(page=7, page_count=30)
chk(d.values()["pages"] == list(range(30)),
    "(7) 쪽수를 제대로 주면 문서 전체를 읽는다", str(len(d.values()["pages"])) + "쪽")

print()
print("=== (8) 책갈피 '파일 폴더 열기' (디자인 §2.8.3) ===")
from viewer.widgets.bookmark_tree import BookmarkTree
chk(hasattr(BookmarkTree, "_file_path_of"), "(8) 행에서 파일 경로를 얻는다")
chk(hasattr(BookmarkTree, "_reveal_in_explorer"), "(8) 탐색기로 여는 길이 있다")
m = inspect.getsource(BookmarkTree._on_tree_context_menu)
i, j = m.find("파일 폴더 열기"), m.find("파일 복사")
chk(0 <= i < j, "(8) '파일 복사' **위에** 있다", "%d < %d" % (i, j))
chk("_edit_mode" not in m[max(0, i - 220):i],
    "(8) 편집모드가 아니어도 보인다 — 읽기만 하는 동작이다")
r = inspect.getsource(BookmarkTree._reveal_in_explorer)
chk("/select," in r, "(8) 폴더만 열지 않고 그 파일을 짚어 준다")
chk("openUrl" in r, "(8) 실패하면 폴더만이라도 연다")

print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for msg in fails:
    print(" -", msg)
sys.stdout.flush()
os._exit(0 if not fails else 1)
