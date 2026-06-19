# -*- coding: utf-8 -*-
"""260611-12: 메인 썸네일 — 종횡비별 셀 높이(세로 길면 크게/가로 길면 작게)·중앙정렬 폭."""
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

tmp = Path(tempfile.mkdtemp(prefix="polypdf_thumb_"))
d = fitz.open()
d.new_page(width=400, height=600).insert_text((40, 80), "portrait")   # 0: 세로
d.new_page(width=700, height=300).insert_text((40, 80), "landscape")  # 1: 가로
d.new_page(width=400, height=600).insert_text((40, 80), "portrait2")  # 2: 세로
d.save(str(tmp / "T.pdf")); d.close()

app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.thumbs_list import PageThumbs
pt = PageThumbs(); pt.resize(150, 700); pt.show(); app.processEvents()

# 1) _card_h_for: 세로 > 가로
ch_p = pt._card_h_for(400, 600)
ch_l = pt._card_h_for(700, 300)
chk(ch_p > ch_l, "세로 카드 높이 > 가로 카드 높이", f"세로={ch_p} 가로={ch_l}")

pt.load_document(str(tmp / "T.pdf"))
app.processEvents()
pt._render_visible(); app.processEvents()

# 2) 렌더 후 항목 셀 높이: 세로 페이지 > 가로 페이지(간격 적정)
h0 = pt.list.item(0).sizeHint().height()
h1 = pt.list.item(1).sizeHint().height()
h2 = pt.list.item(2).sizeHint().height()
chk(h0 > h1 and h2 > h1, "세로쪽 셀 > 가로쪽 셀(가로 페이지 빈 간격 제거)",
    f"세로={h0} 가로={h1} 세로2={h2}")
# 가로 셀 높이는 가로 카드높이+여백과 거의 같아야(과한 빈공간 없음)
chk(abs(h1 - (ch_l + pt.ITEM_MARGIN)) <= 4, "가로 셀이 실제 카드 높이에 밀착",
    f"가로셀={h1} 기대≈{ch_l + pt.ITEM_MARGIN}")

# 3) 균일크기 끔(항목별 높이 허용)
chk(pt.list.uniformItemSizes() is False, "uniformItemSizes 꺼짐")

# 4) 중앙정렬 폭: 아이콘 폭 = 뷰포트 폭(스크롤바 제외)
chk(pt.list.iconSize().width() == pt.list.viewport().width(),
    "아이콘 폭 = 뷰포트 폭(스크롤바 고려 중앙정렬)",
    f"icon={pt.list.iconSize().width()} vp={pt.list.viewport().width()}")

# 5) 렌더 타이머 빨라짐
chk(pt._render_timer.interval() <= 20, "렌더 타이머 ≤20ms(빠른 표시)")

pt.close()
print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
