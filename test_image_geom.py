# -*- coding: utf-8 -*-
"""260611-18: 개체 비율고정/Shift해제·변 리사이즈·회전+90도 스냅·rot 영속·저장 메타훅."""
import os, sys, json, tempfile, math
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

tmp = Path(tempfile.mkdtemp(prefix="polypdf_geom_"))
d = fitz.open(); d.new_page(width=400, height=600).insert_text((40, 80), "p")
d.save(str(tmp / "T.pdf")); d.close()
(tmp / "bookmarks.json").write_text(
    json.dumps({"version": 1, "bookmarks": [{"title": "T", "file": "T.pdf", "children": []}]}),
    encoding="utf-8")

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(1100, 800); mw.show(); app.processEvents()
mw.open_folder(tmp); app.processEvents()
mw._on_bookmark_activated(mw.bookmark_tree.ordered_pdf_files()[0], 0); app.processEvents()
mv = mw._mv[0]
mv.set_draw_mode(True); app.processEvents()
pr = mv._page_view_rect()

def fresh_image():
    mv._img_objects = []
    p = QPixmap(80, 40); p.fill(QColor('#0066cc'))
    mv.add_image_from_pixmap(p)
    mv._img_selected = 0
    return mv._img_objects[0]

def aspect_px(obj):
    _, _, hw, hh, _ = mv._img_geom(obj, pr)
    return hw / max(1e-6, hh)

def hp(obj, name):
    return mv._img_handle_points(obj, pr)[name]

# 1) 모서리 드래그 = 비율 고정
o = fresh_image(); a0 = aspect_px(o)
br = hp(o, "br")
mv._img_mouse_press(QPoint(int(br.x()), int(br.y())), pr)
chk(mv._img_drag == "br", "br 핸들 잡힘", mv._img_drag or "")
mv._img_mouse_move(QPoint(int(br.x()) + 120, int(br.y()) + 30), pr, shift=False)
a1 = aspect_px(o)
chk(abs(a1 - a0) / a0 < 0.04, "모서리 드래그 → 비율 고정 유지", f"{a0:.3f}->{a1:.3f}")
mv._img_mouse_release()

# 2) Shift + 모서리 = 비율 해제
o = fresh_image(); a0 = aspect_px(o)
br = hp(o, "br")
mv._img_mouse_press(QPoint(int(br.x()), int(br.y())), pr)
mv._img_mouse_move(QPoint(int(br.x()) + 120, int(br.y()) + 10), pr, shift=True)
a1 = aspect_px(o)
chk(abs(a1 - a0) / a0 > 0.1, "Shift+모서리 → 비율 해제(자유)", f"{a0:.3f}->{a1:.3f}")
mv._img_mouse_release()

# 3) 변(오른쪽) 핸들 = 한 방향만(높이 불변)
o = fresh_image()
fh0 = o["rect"][3]; fw0 = o["rect"][2]
rmid = hp(o, "r")
mv._img_mouse_press(QPoint(int(rmid.x()), int(rmid.y())), pr)
chk(mv._img_drag == "r", "오른쪽 변 핸들 잡힘", mv._img_drag or "")
mv._img_mouse_move(QPoint(int(rmid.x()) + 80, int(rmid.y()) + 40), pr, shift=False)
chk(abs(o["rect"][3] - fh0) < 1e-4, "변 리사이즈 → 높이 불변", f"{fh0:.4f}->{o['rect'][3]:.4f}")
chk(o["rect"][2] > fw0 + 1e-3, "변 리사이즈 → 폭만 증가", f"{fw0:.4f}->{o['rect'][2]:.4f}")
mv._img_mouse_release()

# 4) 회전 핸들 + 90도 자석
o = fresh_image()
cx = pr.left() + (o["rect"][0] + o["rect"][2] / 2) * pr.width()
cy = pr.top() + (o["rect"][1] + o["rect"][3] / 2) * pr.height()
rp = hp(o, "rot")
mv._img_mouse_press(QPoint(int(rp.x()), int(rp.y())), pr)
chk(mv._img_drag == "rot", "회전 핸들 잡힘", mv._img_drag or "")
# 오른쪽으로(중심 기준 각 0 → +90) → 90도 인근 스냅
mv._img_mouse_move(QPoint(int(cx) + 150, int(cy) + 5), pr, shift=False)
chk(abs(o["rot"] - 90.0) < 0.01, "오른쪽 → 90도 자석 스냅", f"rot={o['rot']:.2f}")
# 대각(45도 인근, 90/0에서 먼) → 스냅 안 됨
mv._img_mouse_move(QPoint(int(cx) + 120, int(cy) - 120), pr, shift=False)
chk(40 < o["rot"] < 50, "대각 → 45도 부근(스냅 없음)", f"rot={o['rot']:.2f}")
mv._img_mouse_release()

# 5) rot 영속(save out 에 rot 포함)
captured = {}
mv._img_setter = lambda f, p, out: captured.update({"out": out})
o["rot"] = 33.0
mv._save_page_images()
chk(captured.get("out") and abs(captured["out"][0].get("rot", 0) - 33.0) < 0.1,
    "저장 시 rot 직렬화", str(captured.get("out", [{}])[0].get("rot")))

# 6) A4: 책갈피 변경 없이 개체만 있어도 '저장' 이 메타 커밋(메타훅 호출)
called = {"commit": 0}
mw._edit_dirty = True
mw.bookmark_tree.set_meta_hooks(lambda: True, lambda: called.__setitem__("commit", called["commit"] + 1))
mw.bookmark_tree.btn_edit.blockSignals(True)
mw.bookmark_tree._edit_mode = True
mw.bookmark_tree.btn_edit.blockSignals(False)
mw.bookmark_tree._op_save()
chk(called["commit"] == 1, "개체만 변경 + 저장 → 메타 커밋 호출(변경없음 창 대신)", str(called))

# 7) A5: 썸네일 이미지 베이킹 — 리졸버 연결 + 합성 무오류
from PyQt6.QtGui import QPainter
chk(mw.page_thumbs._img_resolver is not None, "썸네일 이미지 리졸버 연결됨")
canvas = QPixmap(120, 180); canvas.fill(QColor("white"))
pnt = QPainter(canvas)
mw.page_thumbs._img_resolver = lambda p0: [{"data": mv._img_objects[0]["data"],
    "rect": [0.1, 0.1, 0.5, 0.3], "shape": "round", "alpha": 80, "rot": 20.0}]
mw.page_thumbs._paint_thumb_images(pnt, 0, 120, 180)
pnt.end()
chk(True, "썸네일 개체 베이킹 합성 무오류")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
