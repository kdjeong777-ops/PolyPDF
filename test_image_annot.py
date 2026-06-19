# -*- coding: utf-8 -*-
"""260611-15: 본문 삽입 이미지(주석) — 추가/이동/투명도/모양/삭제/영속/페이지격리."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtCore import QPoint

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_img_"))
d = fitz.open()
for i in range(2):
    d.new_page(width=400, height=600).insert_text((40, 80), f"p{i}")
d.save(str(tmp / "T.pdf")); d.close()
(tmp / "bookmarks.json").write_text(
    json.dumps({"version": 1, "bookmarks": [{"title": "T", "file": "T.pdf", "children": []}]}),
    encoding="utf-8")

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(1100, 800); mw.show(); app.processEvents()
mw.open_folder(tmp); app.processEvents()
files = mw.bookmark_tree.ordered_pdf_files()
mw._on_bookmark_activated(files[0], 0); app.processEvents()
mv = mw._mv[0]
mv.set_image_edit(True); app.processEvents()
pr = mv._page_view_rect()

def make_pix(c="#ff0000"):
    pm = QPixmap(80, 40); pm.fill(QColor(c)); return pm

# 1) 추가(붙여넣기와 동일 경로) → 객체 1개, 선택됨
mv.add_image_from_pixmap(make_pix("#ff0000"))
chk(len(mv._img_objects) == 1 and mv._img_selected == 0, "이미지 추가+선택")
r0 = list(mv._img_objects[0]["rect"])

# 2) 이동(방향키 nudge)
mv._img_nudge(10, 6)
r1 = mv._img_objects[0]["rect"]
chk(r1[0] > r0[0] and r1[1] > r0[1], "방향키 이동(위치 변경)", f"{r0}->{r1}")

# 3) 투명도(Ctrl+상=불투명/하=투명)
mv._img_objects[0]["alpha"] = 80
mv._img_opacity(+5); chk(mv._img_objects[0]["alpha"] == 85, "불투명도↑")
mv._img_opacity(-15); chk(mv._img_objects[0]["alpha"] == 70, "투명도↑(불투명도↓)")

# 4) 모양 변경(사각형→원형)
mv.set_image_shape("circle")
chk(mv._img_objects[0]["shape"] == "circle", "모양=원형 적용")

# 5) 마우스 hit-test/이동
cx = pr.left() + int((r1[0] + r1[2]/2) * pr.width())
cy = pr.top() + int((r1[1] + r1[3]/2) * pr.height())
idx, handle = mv._img_hit(QPoint(cx, cy), pr)
chk(idx == 0 and handle == "move", "중앙 클릭=이동 핸들", f"idx={idx} h={handle}")
# 코너 핸들
from PyQt6.QtCore import QRectF
rect = mv._draw_overlay._img_rect_view(mv._img_objects[0], pr)
tl = rect.topLeft()
idx2, h2 = mv._img_hit(QPoint(int(tl.x()), int(tl.y())), pr)
chk(idx2 == 0 and h2 == "tl", "좌상단=리사이즈 핸들", f"h={h2}")

# 6) 영속(page_meta 저장/로드)
mw._on_bookmark_activated(files[0], 0)   # 같은 파일 재로드(go_to_page 경유)
app.processEvents()
# 페이지 0 재로드 시 이미지 1개 복원
imgs = mw._images_for(str(files[0]), 0)
chk(len(imgs) == 1 and imgs[0].get("shape") == "circle" and "data" in imgs[0],
    "page_meta 저장·로드(모양·데이터 보존)", f"n={len(imgs)}")

# 7) 페이지 격리 — 1쪽엔 없음
mv.go_to_page(1); app.processEvents()
chk(len(mv._img_objects) == 0, "다른 페이지엔 이미지 없음(페이지별)")
mv.go_to_page(0); app.processEvents()
chk(len(mv._img_objects) == 1, "0쪽 복귀 시 이미지 복원")

# 8) 삭제
mv._img_selected = 0
mv._img_delete_selected()
chk(len(mv._img_objects) == 0 and mv._img_selected == -1, "선택 이미지 삭제")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
