# -*- coding: utf-8 -*-
"""260913-5: 다단(병합·인쇄·이미지→PDF) 저장도 글꼴은 **쓴 글자만** 담는다 (마스터 SOT §4.5.10).

`build_twoup` 은 Word 가 없을 때 표지·목차·간지를 `_kr_text`(fontfile=맑은 고딕)로 만들고,
쪽번호 글꼴을 고르면 `_draw_footer` 가 그 글꼴 파일을 넣는다 → 글꼴 전체가 들어가 수 MB.

  ① 저장 크기가 부분집합 없는 저장보다 훨씬 작다 (표지+목차+간지 / 쪽번호 글꼴)
  ② 모든 쪽의 렌더 픽셀·텍스트 추출·검색·책갈피가 같다
  ③ `subset_fonts` 가 실패해도 저장된다
  ④ `pdf_font` 두 함수 — 실패 삼키기, 부분집합 표시가 붙은 같은 이름만 비켜 가기
"""
import os, sys, tempfile, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


import test_fixtures as _fx
from viewer import twoup, pdf_font

# ④ 단위 — 글꼴이 없어도 도는 부분
class _BoomDoc:
    def subset_fonts(self):
        raise RuntimeError("fontTools 없음 모사")


chk(pdf_font.subset_fonts_safely(_BoomDoc()) is False, "④ subset_fonts_safely 는 예외를 삼킨다")


class _Page:
    def __init__(self, fonts):
        self._f = fonts

    def get_fonts(self):
        return [(i + 10, "ttf", "Type0", bf, nm, "Identity-H", 0) for i, (nm, bf) in enumerate(self._f)]


chk(pdf_font.fresh_font_name(_Page([]), "krfont") == "krfont", "④ 이름이 없으면 그대로")
chk(pdf_font.fresh_font_name(_Page([("krfont", "Malgun Gothic Regular")]), "krfont") == "krfont",
    "④ 같은 이름이라도 전체 글꼴이면 재사용(같은 저장 안)")
chk(pdf_font.fresh_font_name(_Page([("krfont", "ABCDEF+Malgun Gothic Regular")]), "krfont") == "krfont2",
    "④ 부분집합이 된 같은 이름은 비켜 간다")
chk(pdf_font.fresh_font_name(_Page([("krfont", "ABCDEF+Malgun"), ("krfont2", "GHIJKL+Malgun")]),
                             "krfont") == "krfont3", "④ 여러 번 저장한 쪽은 다음 번호로")
chk(pdf_font.fresh_font_name(_Page([("krfont", "ABCDEF+Malgun"), ("krfont2", "Malgun Gothic")]),
                             "krfont") == "krfont2", "④ 비켜 간 이름이 아직 전체면 그것을 재사용")

if not _fx.KRFONT:
    print("SKIP - 한글 글꼴(malgun/gulim) 없음 — 글꼴 내장 크기 검사 불가")
    print("ALL PASS" if not fails else f"FAIL {len(fails)}: {fails}")
    sys.stdout.flush(); os._exit(0 if not fails else 1)

root = Path(tempfile.mkdtemp(prefix="polypdf_twoup_subset_"))
# Word 자동화는 느리고(수십 초) 기계마다 다르다 — 불어나는 쪽인 fitz 폴백을 검사한다
twoup._docx_to_pdf = lambda *a, **k: False
ITEMS = [{"type": "pdf", "path": _fx.text_pdf(), "name": "텍스트 문서"},
         {"type": "pdf", "path": _fx.scanned_pdf(), "name": "스캔 문서"}]


def build(name, settings, subset_impl=None):
    orig = fitz.Document.subset_fonts
    if subset_impl is not None:
        fitz.Document.subset_fonts = subset_impl
    try:
        out = str(root / name)
        twoup.build_twoup(ITEMS, settings, out)
    finally:
        fitz.Document.subset_fonts = orig
    return out


def snapshot(path):
    d = fitz.open(path)
    try:
        return ([hashlib.md5(p.get_pixmap(dpi=60).samples).hexdigest() for p in d],
                [p.get_text() for p in d],
                [len(p.search_for("문서")) for p in d],
                d.get_toc(simple=True))
    finally:
        d.close()


def _noop(self, *a, **k):
    return None


def _boom(self, *a, **k):
    raise RuntimeError("subset 실패 모사")


CASES = {
    "표지+목차+간지": {"nup": 2, "make_cover": True, "make_toc": True, "make_divider": True,
                   "cover": {"title": "병합 보고서", "subtitle": "부분집합 검사"}},
    "쪽번호 글꼴": {"nup": 2, "make_cover": False, "make_toc": False, "footer_font": "맑은 고딕"},
}
for label, st in CASES.items():
    full = build(f"{label}_full.pdf", st, _noop)
    real = build(f"{label}_real.pdf", st)
    sz_full, sz_real = os.path.getsize(full), os.path.getsize(real)
    chk(sz_real < sz_full / 5 and sz_full - sz_real > 3_000_000,
        f"① {label}: 글꼴 전체가 안 들어간다", f"({sz_full:,} → {sz_real:,} B)")
    a, b = snapshot(full), snapshot(real)
    chk(a[0] == b[0], f"② {label}: 모든 쪽 렌더 픽셀 동일", f"({len(b[0])}쪽)")
    chk(a[1] == b[1], f"② {label}: 텍스트 추출 동일")
    chk(a[2] == b[2], f"② {label}: 검색 결과 동일", f"(적중 {sum(b[2])})")
    chk(a[3] == b[3] and len(b[3]) >= 2, f"② {label}: 책갈피 동일")

chk("병합 보고서" in snapshot(str(root / "표지+목차+간지_real.pdf"))[1][0],
    "② 표지 글(한글)이 부분집합 뒤에도 추출된다")

p = build("boom.pdf", CASES["쪽번호 글꼴"], _boom)
chk(os.path.exists(p) and fitz.open(p).page_count > 0, "③ subset_fonts 가 실패해도 저장된다")

src_code = Path(__file__).with_name("viewer").joinpath("twoup.py").read_text("utf-8")
chk(src_code.index("subset_fonts_safely(final)") < src_code.index("final.save(out_path"),
    "① 저장 **직전**에 부분집합을 만든다")

print("ALL PASS" if not fails else f"FAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
