# -*- coding: utf-8 -*-
"""260611-37: Phase 2 — 미리보기 compose·드래그 값 변환·N-up 인쇄 구성."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

app = QApplication.instance() or QApplication(sys.argv)

NB = {"make_cover": False, "make_toc": False, "make_divider": False}   # 본문만(앞장 제외)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_p2_"))
d = fitz.open()
for i in range(8):
    d.new_page(width=595, height=842).insert_text((250, 420), f"P{i+1}", fontsize=40)
d.save(str(tmp / "src.pdf")); d.close()

# 1) compose_preview — 6-up: png + 6칸 + 전체 시트 수(8쪽→ceil(8/6)=2)
import viewer.twoup as tw
png, ow, oh, cells, total = tw.compose_preview(str(tmp / "src.pdf"),
                                               dict(NB, nup=6, page_size="A4"), 0)
chk(png and len(png) > 100 and len(cells) == 6 and oh > ow, "미리보기 합성(6-up, 6칸, 세로)",
    f"cells={len(cells)} {round(ow)}x{round(oh)}")
chk(total == 2, "전체 시트 수(8쪽 6-up → 2)", str(total))
# 시트 1(인덱스 1) 렌더 — 나머지 2쪽
png_b, _o, _o2, _c, total_b = tw.compose_preview(str(tmp / "src.pdf"), dict(NB, nup=6), 1)
chk(png_b and total_b == 2, "두 번째 시트 렌더(페이지 넘김)")
# 2-up
png2, ow2, oh2, cells2, total2 = tw.compose_preview(str(tmp / "src.pdf"), dict(NB, nup=2), 0)
chk(len(cells2) == 2 and ow2 > oh2 and total2 == 4, "미리보기 합성(2-up, 가로, 8쪽→4시트)")

# 2) 미리보기 드래그 값 변환(_val_from_pt)
from viewer.widgets.merge_preview import MergePreviewDialog
dlg = MergePreviewDialog(dict(NB, nup=6, page_size="A4", margin_left=28), str(tmp / "src.pdf"))
cv = dlg.widget.canvas
cv.set_image(png, ow, oh, cells, dlg.widget.vals)
# margin_left 를 페이지 pt 50 으로
chk(round(cv._val_from_pt("margin_left", 50)) == 50, "여백 드래그 → pt 값 변환")
# crop_top: 첫 칸 위에서 10% 지점
cx0, cy0, cx1, cy1 = cells[0]; ch = cy1 - cy0
v = cv._val_from_pt("crop_top", cy0 + 0.1 * ch)
chk(abs(v - 10) < 0.5, "크롭 드래그 → % 값 변환(10%)", f"{v:.1f}")
dlg.widget.vals["margin_left"] = 40
chk(dlg.get_values()["margin_left"] == 40, "미리보기 값 반환")
# 페이지(시트) 넘김
chk(dlg.widget._total == 2, "미리보기 전체 시트 수")
dlg.widget._next_sheet()
chk(dlg.widget._sheet == 1, "다음 시트로 넘김")
dlg.widget._prev_sheet()
chk(dlg.widget._sheet == 0, "이전 시트로 넘김")

# 3) 다단 인쇄 구성(_build_nup_pdf) — 임시 N-up PDF 경로 반환
from viewer.app import MainWindow
mw = MainWindow()
out_nup = mw._build_nup_pdf(str(tmp / "src.pdf"), list(range(8)),
                            {"nup": 6, "make_cover": False, "make_toc": False})
chk(out_nup and Path(out_nup).exists(), "다단 인쇄용 PDF 생성")
nd = fitz.open(out_nup)
# 8쪽 → 6-up → ceil(8/6)=2 시트 (표지 없음, 목차는 settings대로 — 여기선 True라 1장 추가 가능)
chk(nd.page_count >= 2, "N-up 인쇄 PDF 시트 구성", str(nd.page_count))
nd.close()

# 4) 연속 채움 미리보기(1쪽 X + 3쪽 Y → 2시트, 셀 가득) + 가이드 선택 (260611-39)
dx = fitz.open(); dx.new_page(width=595, height=842); dx.save(str(tmp / "X.pdf")); dx.close()
dy = fitz.open()
for i in range(3):
    dy.new_page(width=595, height=842)
dy.save(str(tmp / "Y.pdf")); dy.close()
itemsXY = [{"type": "pdf", "path": str(tmp / "X.pdf"), "name": "X"},
           {"type": "pdf", "path": str(tmp / "Y.pdf"), "name": "Y"}]
_p, _ow, _oh, _c, totalXY = tw.compose_preview(itemsXY, dict(NB, nup=2), 0)
chk(totalXY == 2, "연속 채움 미리보기: 1쪽+3쪽 → 2시트", str(totalXY))
# 가이드 선택: 여백만 → margin 가이드만
dlg.widget.canvas.set_show("margin")
gids = [k for (k, o, c) in dlg.widget.canvas._guides()]
chk(all(k in ("margin_left","margin_right","margin_top","margin_bottom","gap","gap_v") for k in gids) and gids, "여백·간격만 표시", str(gids))
dlg.widget.canvas.set_show("crop")
gids2 = [k for (k, o, c) in dlg.widget.canvas._guides()]
chk(all(k.startswith("crop") for k in gids2), "크롭만 표시 → 크롭 가이드만", str(gids2))

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
