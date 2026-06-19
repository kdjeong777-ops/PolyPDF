# -*- coding: utf-8 -*-
"""260611-29: 2단 축소 배치 — 임포지션·쪽번호·책갈피 재매핑·목차/표지(fitz 폴백)."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

import viewer.twoup as twoup
twoup._docx_to_pdf = lambda d, p: False     # Word 비활성 → fitz 폴백 강제

tmp = Path(tempfile.mkdtemp(prefix="polypdf_2uptest_"))
# 세로 PDF 2개(각 3쪽), 가로 PDF 1개(2쪽)
def make(name, w, h, n):
    d = fitz.open()
    for i in range(n):
        pg = d.new_page(width=w, height=h)
        pg.insert_text((40, 80), f"{name} p{i+1}")
    d.save(str(tmp / name)); d.close()
make("A.pdf", 595, 842, 3)     # 세로
make("B.pdf", 595, 842, 3)     # 세로
make("L.pdf", 842, 595, 2)     # 가로

items = [{"type": "pdf", "path": str(tmp / "A.pdf"), "name": "A"},
         {"type": "pdf", "path": str(tmp / "B.pdf"), "name": "B"},
         {"type": "pdf", "path": str(tmp / "L.pdf"), "name": "L"}]
settings = {"enabled": True, "make_cover": True, "make_toc": True,
            "cover": {"title": "제목", "subtitle": "부제", "company": "회사", "name": "성명"}}
out = str(tmp / "merged_2up.pdf")
twoup.build_twoup(items, settings, out, gen_bookmarks_fn=None)

chk(os.path.exists(out), "2단 병합 출력 생성")
d = fitz.open(out)
# 연속 채움: 8쪽(A3+B3+L2) → 2-up → 4시트, + 표지1 + 목차1 = 6
chk(d.page_count == 6, "페이지 수 = 표지1+목차1+내용4(연속)", f"{d.page_count}")

# 내용 첫 시트(인덱스2): A0,A1(세로) → 가로 시트
sheet0 = d[2].rect
chk(sheet0.width > sheet0.height, "세로 원본 → 가로 2단 시트(좌우)")
# 마지막 시트(인덱스5): L0,L1(가로) → 세로 시트
sheetL = d[5].rect
chk(sheetL.height > sheetL.width, "가로 원본 → 세로 2단 시트(상하)")

toc = d.get_toc(simple=True)
names = [t for (_l, t, _p) in toc]
chk("A" in names and "B" in names and "L" in names, "파일 단위 책갈피 생성", str(names))
# A 시작 시트=1 → 앞장2 + 1 = 3 ; B 첫쪽 전역 인덱스3 → 시트2 → 앞장2 + 2 = 4
a_entry = next((p for (l, t, p) in toc if t == "A"), None)
chk(a_entry == 3, "A 책갈피 = 앞장2 + 시트1 = 3", str(a_entry))
b_entry = next((p for (l, t, p) in toc if t == "B"), None)
chk(b_entry == 4, "B 책갈피 = 앞장2 + 시트2 = 4(연속)", str(b_entry))
d.close()

# 쪽번호 텍스트(내용 첫 시트에 '1')
d2 = fitz.open(out)
txt = d2[2].get_text()
chk("1" in txt, "내용 첫 시트 하단 쪽번호 '1'")
d2.close()

# 혼합 방향 파일 — 짝(시트)별로 방향 결정 (260611-30)
tmp2 = Path(tempfile.mkdtemp(prefix="polypdf_2upmix_"))
dm = fitz.open()
dm.new_page(width=595, height=842)   # 세로
dm.new_page(width=595, height=842)   # 세로
dm.new_page(width=842, height=595)   # 가로
dm.new_page(width=842, height=595)   # 가로
dm.save(str(tmp2 / "M.pdf")); dm.close()
out2 = str(tmp2 / "mix.pdf")
twoup.build_twoup([{"type": "pdf", "path": str(tmp2 / "M.pdf"), "name": "M"}],
                  {"make_cover": False, "make_toc": False}, out2)
dm2 = fitz.open(out2)
# 시트0(세로 짝)=가로 시트, 시트1(가로 짝)=세로 시트
chk(dm2[0].rect.width > dm2[0].rect.height, "세로 짝 → 가로 시트(좌우)")
chk(dm2[1].rect.height > dm2[1].rect.width, "가로 짝 → 세로 시트(상하)")
dm2.close()

# 진행 콜백 + 취소 (260611-32)
calls = []
def prog(done, total, label):
    calls.append((done, total, label))
    return True
out3 = str(tmp2 / "prog.pdf")
twoup.build_twoup([{"type": "pdf", "path": str(tmp2 / "M.pdf"), "name": "M"}],
                  {"make_cover": True, "make_toc": True}, out3, progress=prog)
chk(len(calls) >= 3 and calls[-1][0] <= calls[-1][1], "진행 콜백 호출(시트+표지+목차)", f"n={len(calls)}")

# 취소 → MergeCancelled, 출력 미생성
from viewer.twoup import MergeCancelled
out4 = str(tmp2 / "cancel.pdf")
def prog_cancel(done, total, label):
    return False    # 즉시 취소
cancelled = False
try:
    twoup.build_twoup([{"type": "pdf", "path": str(tmp2 / "M.pdf"), "name": "M"}],
                      {"make_cover": True}, out4, progress=prog_cancel)
except MergeCancelled:
    cancelled = True
chk(cancelled and not os.path.exists(out4), "취소 시 MergeCancelled + 출력 미생성")

# 260611-36: N-up·용지·크롭 격자
from viewer.twoup import _grid_layout, merge_twoup_settings, _crop_clip
pr_port = fitz.Rect(0, 0, 595, 842)   # 세로 원본
s6 = merge_twoup_settings({"nup": 6, "page_size": "A4"})
ow6, oh6, b6 = _grid_layout(pr_port, s6)
chk(len(b6) == 6 and oh6 > ow6, "6-up: 6칸·세로 A4")
chk(abs(ow6 - 595.28) < 1 and abs(oh6 - 841.89) < 1, "6-up 용지 = 세로 A4")
s2 = merge_twoup_settings({"nup": 2, "page_size": "A4"})
ow2, oh2, b2 = _grid_layout(pr_port, s2)
chk(len(b2) == 2 and ow2 > oh2, "2-up 세로원본 → 가로 A4 2칸")
sL = merge_twoup_settings({"nup": 6, "page_size": "Letter"})
owL, ohL, _bL = _grid_layout(pr_port, sL)
chk(abs(owL - 612) < 1 and abs(ohL - 792) < 1, "용지 Letter 반영")
clip = _crop_clip(fitz.Rect(0, 0, 100, 200),
                  merge_twoup_settings({"crop_top": 10, "crop_bottom": 10,
                                        "crop_left": 5, "crop_right": 5}))
chk(abs(clip.width - 90) < 1e-6 and abs(clip.height - 160) < 1e-6, "크롭 clip(좌우5%·상하10%)")

# 6-up 종단 빌드: 7쪽 세로 문서 → ceil(7/6)=2 시트
tmp6 = Path(tempfile.mkdtemp(prefix="polypdf_6up_"))
d6 = fitz.open()
for i in range(7):
    d6.new_page(width=595, height=842).insert_text((40, 80), f"p{i}")
d6.save(str(tmp6 / "S.pdf")); d6.close()
out6 = str(tmp6 / "six.pdf")
twoup.build_twoup([{"type": "pdf", "path": str(tmp6 / "S.pdf"), "name": "S"}],
                  {"nup": 6, "make_cover": False, "make_toc": False}, out6)
dd6 = fitz.open(out6)
chk(dd6.page_count == 2 and dd6[0].rect.height > dd6[0].rect.width,
    "6-up 빌드: 2시트·세로", f"{dd6.page_count}")
dd6.close()

# 260611-39: 제본 여백(gutter) — 단면 좌측 / 양면 홀수 좌·짝수 우
prP = fitz.Rect(0, 0, 595, 842)
sg = merge_twoup_settings({"nup": 2, "gutter": 30, "duplex": False,
                           "margin_left": 10, "margin_right": 10})
owg, ohg, bg = _grid_layout(prP, sg, 1)
chk(abs(bg[0].x0 - 40) < 1, "단면 제본 여백: 좌측 +gutter", f"{bg[0].x0:.1f}")
sd = merge_twoup_settings({"nup": 2, "gutter": 30, "duplex": True,
                           "margin_left": 10, "margin_right": 10})
_o1, _h1, b_odd = _grid_layout(prP, sd, 1)
ow_e, _h2, b_even = _grid_layout(prP, sd, 2)
chk(abs(b_odd[0].x0 - 40) < 1, "양면 홀수 시트: 좌측 제본")
chk(abs(b_even[-1].x1 - (ow_e - 40)) < 1, "양면 짝수 시트: 우측 제본")

# 연속 채움 vs doc_break (1쪽 + 3쪽)
tmpc = Path(tempfile.mkdtemp(prefix="polypdf_cont_"))
fitz.open().new_page(width=595, height=842)  # placeholder
dx = fitz.open(); dx.new_page(width=595, height=842); dx.save(str(tmpc / "X.pdf")); dx.close()
dy = fitz.open()
for i in range(3):
    dy.new_page(width=595, height=842)
dy.save(str(tmpc / "Y.pdf")); dy.close()
items2 = [{"type": "pdf", "path": str(tmpc / "X.pdf"), "name": "X"},
          {"type": "pdf", "path": str(tmpc / "Y.pdf"), "name": "Y"}]
outC = str(tmpc / "cont.pdf")
twoup.build_twoup(items2, {"nup": 2, "make_cover": False, "make_toc": False}, outC)
ndc = fitz.open(outC); chk(ndc.page_count == 2, "연속 채움: 1쪽+3쪽 → 2시트", str(ndc.page_count)); ndc.close()
outD = str(tmpc / "brk.pdf")
twoup.build_twoup(items2, {"nup": 2, "make_cover": False, "make_toc": False, "doc_break": True}, outD)
ndd = fitz.open(outD); chk(ndd.page_count == 3, "doc_break: 문서마다 새 장 → 3시트", str(ndd.page_count)); ndd.close()

# 260611-43: 8-up(2열×4행)
s8 = merge_twoup_settings({"nup": 8, "page_size": "A4"})
ow8, oh8, b8 = _grid_layout(prP, s8)
chk(len(b8) == 8 and oh8 > ow8, "8-up: 8칸·세로 A4", f"{len(b8)}")
cols8 = sum(1 for b in b8 if abs(b.y0 - b8[0].y0) < 1)
chk(cols8 == 2 and len(b8) // cols8 == 4, "8-up = 2열×4행", f"{cols8}열")

# 선(외곽/내부) 그리기 — 빌드 무오류 + drawing 존재
tmpL2 = Path(tempfile.mkdtemp(prefix="polypdf_line_"))
dl = fitz.open()
for i in range(6):
    dl.new_page(width=595, height=842)
dl.save(str(tmpL2 / "S.pdf")); dl.close()
outln = str(tmpL2 / "lines.pdf")
twoup.build_twoup([{"type": "pdf", "path": str(tmpL2 / "S.pdf"), "name": "S"}],
                  {"nup": 6, "make_cover": False, "make_toc": False,
                   "border_outer": True, "border_h": True, "border_v": True,
                   "line_color": "#000000", "line_width": 1}, outln)
dln = fitz.open(outln)
draw_n = len(dln[0].get_drawings())
chk(draw_n >= 3, "외곽+내부선 그려짐(drawings)", f"drawings={draw_n}")
dln.close()

# 260611-44: 여백 색(시트 배경) + 쪽번호 블록
tmpBG = Path(tempfile.mkdtemp(prefix="polypdf_bg_"))
dbg = fitz.open()
for i in range(2):
    dbg.new_page(width=595, height=842)
dbg.save(str(tmpBG / "S.pdf")); dbg.close()
outbg = str(tmpBG / "bg.pdf")
twoup.build_twoup([{"type": "pdf", "path": str(tmpBG / "S.pdf"), "name": "S"}],
                  {"nup": 2, "make_cover": False, "make_toc": False,
                   "margin_bg_on": True, "margin_bg": "#ffeecc",
                   "footer_block": True, "footer_block_shape": "round",
                   "footer_block_color": "#000000", "footer_block_alpha": 60,
                   "footer_bold": True}, outbg)
dbg2 = fitz.open(outbg)
pg0 = dbg2[0]
# 시트 배경 채움 + 쪽번호 블록 → 채워진 사각형이 2개 이상
fills = [d for d in pg0.get_drawings() if d.get("fill") is not None]
chk(len(fills) >= 2, "여백 배경 + 쪽번호 블록(채움 도형)", f"fills={len(fills)}")
# 모서리(여백) 픽셀이 배경색(#ffeecc≈255,238,204)인지
pix = pg0.get_pixmap()
px = pix.pixel(3, 3)
chk(abs(px[0] - 255) < 12 and abs(px[1] - 238) < 12 and abs(px[2] - 204) < 12,
    "여백 픽셀 = 지정 배경색", str(px))
dbg2.close()

# 폰트 파일 해석(있으면) — 무오류 보장
from viewer.twoup import _win_font_file
ff_arial = _win_font_file("Arial", False)
chk(ff_arial is None or ff_arial.lower().endswith((".ttf", ".ttc", ".otf")),
    "글꼴 파일 해석(Arial)", str(ff_arial))

# 260611-46: 채움 방식 — cover/stretch는 셀에 꽉 차고, contain은 한 축에 여백
from viewer.twoup import _cover_clip, _place_page
# 정사각 셀에 세로(좁은) 원본 → cover면 셀 가득(여백 0), contain이면 좌우 여백
box = fitz.Rect(0, 0, 200, 200)
clipP = fitz.Rect(0, 0, 100, 200)            # 세로 원본(0.5)
cc = _cover_clip(clipP, box)                  # 정사각 셀 → 상하 잘라 정사각
chk(abs(cc.width / cc.height - 1.0) < 1e-3 and cc.width <= clipP.width + 1e-6,
    "cover clip = 셀 비율(정사각)·원본 안", f"{cc.width:.0f}x{cc.height:.0f}")

tmpF = Path(tempfile.mkdtemp(prefix="polypdf_fit_"))
df = fitz.open(); df.new_page(width=300, height=842)   # 매우 세로로 긴 원본
df.save(str(tmpF / "S.pdf")); df.close()
# stretch/cover는 셀을 거의 꽉 채우고 contain은 한 축에 큰 여백(픽셀 커버리지로 검증)
def _cell_coverage(mode):
    src = fitz.open(); sp = src.new_page(width=800, height=200)  # 매우 와이드
    sp.draw_rect(sp.rect, color=None, fill=(1, 1, 0))            # 전체 노랑
    o = fitz.open(); pg = o.new_page(width=300, height=300)
    s = merge_twoup_settings({"nup": 1, "fit_mode": mode})
    _, _, bx = _grid_layout(sp.rect, s)
    _place_page(pg, src, 0, bx[0], s)
    pix = pg.get_pixmap(clip=bx[0]); yellow = 0; n = 0
    for yy in range(0, pix.height, 4):
        for xx in range(0, pix.width, 4):
            n += 1; r, g, b = pix.pixel(xx, yy)[:3]
            if r > 200 and g > 200 and b < 80: yellow += 1
    src.close(); o.close()
    return yellow / max(1, n)
cov_c = _cell_coverage("contain"); cov_s = _cell_coverage("stretch"); cov_v = _cell_coverage("cover")
chk(cov_s > 0.9 and cov_v > 0.9 and cov_c < 0.7,
    "꽉 채움/늘이기=셀 꽉 참, 맞춤=여백", f"contain={cov_c:.2f} cover={cov_v:.2f} stretch={cov_s:.2f}")
# contain/cover/stretch 경로 무오류 + 출력 생성
for mode in ("contain", "cover", "stretch"):
    of = str(tmpF / f"{mode}.pdf")
    twoup.build_twoup([{"type": "pdf", "path": str(tmpF / "S.pdf"), "name": "S"}],
                      {"nup": 2, "make_cover": False, "make_toc": False, "fit_mode": mode}, of)
    chk(os.path.exists(of) and fitz.open(of).page_count >= 1, f"채움 방식 '{mode}' 빌드")

# 260611-48: 양면 + 새 문서 홀수 시작 — 문서 경계에 빈 시트 삽입
tmpOdd = Path(tempfile.mkdtemp(prefix="polypdf_odd_"))
for nm in ("D1.pdf", "D2.pdf"):
    dd = fitz.open(); dd.new_page(width=595, height=842)   # 각 1쪽
    dd.save(str(tmpOdd / nm)); dd.close()
itemsO = [{"type": "pdf", "path": str(tmpOdd / "D1.pdf"), "name": "D1"},
          {"type": "pdf", "path": str(tmpOdd / "D2.pdf"), "name": "D2"}]
base = {"nup": 2, "duplex": True, "doc_break": True, "make_cover": False, "make_toc": False}
o_even = str(tmpOdd / "even.pdf")
twoup.build_twoup(itemsO, dict(base, doc_start_odd=False), o_even)
de = fitz.open(o_even); chk(de.page_count == 2, "doc_break만: 2시트(D2=2쪽,짝수)", str(de.page_count)); de.close()
o_odd = str(tmpOdd / "odd.pdf")
twoup.build_twoup(itemsO, dict(base, doc_start_odd=True), o_odd)
do = fitz.open(o_odd)
chk(do.page_count == 3, "홀수 시작: 빈 시트 삽입 → 3시트(D2=3쪽,홀수)", str(do.page_count))
toc_o = do.get_toc(simple=True)
d2p = next((p for (l, t, p) in toc_o if t == "D2"), None)
chk(d2p == 3 and d2p % 2 == 1, "D2 책갈피 = 홀수 페이지(3)", str(d2p))
do.close()

# 표지(앞장)가 있어도 각 문서가 홀수 페이지에서 시작 (이전 버그: 앞장 오프셋 무시)
o_cov = str(tmpOdd / "odd_cover.pdf")
twoup.build_twoup(itemsO, dict(base, doc_start_odd=True, make_cover=True),
                  o_cov, gen_bookmarks_fn=None)
dc = fitz.open(o_cov)
toc_c = dc.get_toc(simple=True)
d1c = next((p for (l, t, p) in toc_c if t == "D1"), None)
d2c = next((p for (l, t, p) in toc_c if t == "D2"), None)
chk(d1c is not None and d1c % 2 == 1 and d2c is not None and d2c % 2 == 1,
    "표지 있어도 D1·D2 모두 홀수 페이지", f"D1={d1c} D2={d2c}")
dc.close()

# 260611-48: 여백 색 켜짐 + 투명/빈 원본 → 문서 영역엔 흰 종이(여백색 비침 방지)
tmpTr = Path(tempfile.mkdtemp(prefix="polypdf_tr_"))
dt = fitz.open(); dt.new_page(width=595, height=842)       # 내용 없는(투명) 원본
dt.save(str(tmpTr / "T.pdf")); dt.close()
o_tr = str(tmpTr / "tr.pdf")
twoup.build_twoup([{"type": "pdf", "path": str(tmpTr / "T.pdf"), "name": "T"}],
                  {"nup": 2, "make_cover": False, "make_toc": False, "fit_mode": "contain",
                   "margin_bg_on": True, "margin_bg": "#00ff00"}, o_tr)
dtr = fitz.open(o_tr); pgt = dtr[0]; pxt = pgt.get_pixmap()
cx, cy = pxt.width // 4, pxt.height // 2      # 좌측 셀(문서) 중앙 (2-up은 한가운데가 간격)
cpx = pxt.pixel(cx, cy)
chk(cpx[0] > 200 and cpx[1] > 200 and cpx[2] > 200,
    "문서 영역 = 흰 종이(여백색 안 비침)", str(cpx))
edge = pxt.pixel(2, pxt.height // 2)         # 좌측 여백
chk(edge[1] > 200 and edge[0] < 80,
    "여백 영역 = 지정 배경색(녹색)", str(edge))
dtr.close()

# 260611-50: 대량 항목 미리보기 — 캐시 cap 초과 시 use-after-close 크래시 없이 전 시트 렌더
from viewer.twoup import compose_preview, clear_preview_cache
from viewer import twoup as _tw
tmpBig = Path(tempfile.mkdtemp(prefix="polypdf_big_"))
big_items = []
for n in range(40):                       # cap(12)보다 훨씬 많은 파일
    db = fitz.open()
    for i in range(3):
        db.new_page(width=595, height=842).insert_text((40, 80), f"d{n}p{i}")
    fp = str(tmpBig / f"B{n}.pdf"); db.save(fp); db.close()
    big_items.append({"type": "pdf", "path": fp, "name": f"B{n}"})
clear_preview_cache()
ok_big = True; tot0 = None
bs = {"nup": 2, "make_cover": False, "make_toc": False, "make_divider": False}
try:
    _png, _ow, _oh, _cells, tot0 = compose_preview(big_items, bs, 0)
    for si in range(tot0):                # 전 페이지 순회(역방향도)
        compose_preview(big_items, bs, si)
    for si in range(tot0 - 1, -1, -1):
        compose_preview(big_items, dict(bs, nup=6, fit_mode="cover"), si)
except Exception as e:
    ok_big = False
chk(ok_big and tot0 == 60, "대량(40파일·120쪽) 전 시트 렌더 무크래시", f"sheets={tot0}")
chk(len(_tw._PREVIEW_CACHE) <= _tw._PREVIEW_CAP and len(_tw._PREVIEW_PINNED) == 0,
    "캐시 cap 유지 + 렌더 후 pin 해제", f"cache={len(_tw._PREVIEW_CACHE)} pin={len(_tw._PREVIEW_PINNED)}")
clear_preview_cache()

# 260611-51: 번호 체계(표지 없음·목차 로마자·본문 아라비아) + 간지
from viewer.twoup import _roman, write_sample_templates
chk(_roman(1) == "i" and _roman(2) == "ii" and _roman(4) == "iv" and _roman(9) == "ix",
    "로마자 변환", f"{_roman(1)},{_roman(4)},{_roman(9)}")

tmpN = Path(tempfile.mkdtemp(prefix="polypdf_num_"))
for nm in ("문서A.pdf", "문서B.pdf"):
    dn = fitz.open()
    for i in range(2):
        dn.new_page(width=595, height=842)
    dn.save(str(tmpN / nm)); dn.close()
itemsN = [{"type": "pdf", "path": str(tmpN / "문서A.pdf"), "name": "문서A"},
          {"type": "pdf", "path": str(tmpN / "문서B.pdf"), "name": "문서B"}]
outN = str(tmpN / "num.pdf")
twoup.build_twoup(itemsN, {"nup": 2, "make_cover": True, "make_toc": True,
                           "make_divider": True}, outN)
dN = fitz.open(outN)
# 구조: 표지1 + 목차1 + (간지+내용)×2.  간지 있으니 per-file.
# 표지(0): 번호 없음 → 'i'·'1' 등 쪽번호 텍스트 없어야(제목 외)
cover_txt = dN[0].get_text()
toc_txt = dN[1].get_text()
chk("i" in toc_txt.split(), "목차에 로마자 'i'", repr([t for t in toc_txt.split() if t in ('i','ii')]))
# 간지(2): 파일명 있고 쪽번호 숨김 / 내용(3): 아라비아 숨김 카운트(간지=1 → 내용='2')
div_txt = dN[2].get_text()
body_txt = dN[3].get_text()
chk("문서A" in div_txt, "간지에 파일명", repr(div_txt[:20]))
chk("2" in body_txt.split(), "간지 카운트 후 본문 = '2'", repr([t for t in body_txt.split() if t.isdigit()]))
dN.close()

# 간지 + 양면 홀수시작: 간지 홀수 + 간지 뒤 빈페이지 → 본문 홀수
outNo = str(tmpN / "num_odd.pdf")
twoup.build_twoup(itemsN, {"nup": 2, "make_cover": False, "make_toc": False,
                           "make_divider": True, "duplex": True, "doc_break": True,
                           "doc_start_odd": True}, outNo)
dNo = fitz.open(outNo)
toc_no = dNo.get_toc(simple=True)
# 파일 책갈피 = 간지(홀수 페이지)
starts = [p for (l, t, p) in toc_no if l == 1]
chk(all(p % 2 == 1 for p in starts) and len(starts) == 2, "간지 시작 모두 홀수 페이지", str(starts))
dNo.close()

# 샘플 양식 다운로드
tmpS = Path(tempfile.mkdtemp(prefix="polypdf_smpl_"))
made = write_sample_templates(str(tmpS))
chk(len(made) == 3 and all(os.path.exists(m) and m.endswith(".docx") for m in made),
    "표지·목차·간지 샘플 docx 생성", f"{len(made)}개")

# 미리보기에 표지·목차·간지 포함(총 페이지가 본문보다 큼)
from viewer.twoup import compose_preview, clear_preview_cache
clear_preview_cache()
_p, _w, _h, _c, tot_prev = compose_preview(itemsN, {"nup": 2, "make_cover": True,
                                                    "make_toc": True, "make_divider": True}, 0)
chk(tot_prev == 6, "미리보기 = 표지1+목차1+(간지+내용)×2 = 6쪽", str(tot_prev))
clear_preview_cache()

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
