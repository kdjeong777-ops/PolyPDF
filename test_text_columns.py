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
