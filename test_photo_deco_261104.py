# -*- coding: utf-8 -*-
"""사진 꾸밈 좌표 돌리기 — 종류마다 (사진 보기 SOT 4.19, `viewer/photo_deco.py`, 261104-3).

A. 모든 종류(선·도형 rect·round·원·글상자·지시선·하이라이트 점·삽입 그림)를 90·180·270 으로 돌렸다 되돌리면 원래 값(왕복)
B. 상자 개체는 화면 픽셀 크기가 그대로이고 개체 `rot` 에 회전이 더해진다
C. 원은 중심을 옮기고 반지름 픽셀이 그대로
D. 하이라이트 띠는 180 이면 띠 그대로 뒤집고, 90 이면 가운데 선 두 점으로 바뀐다(두께 픽셀 그대로)
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from viewer import photo_deco as pd

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def near(a, b, tol=1e-6):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(near(a[k], b[k], tol) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(near(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


W, H = 800.0, 400.0
strokes = [
    {"points": [[0.1, 0.2], [0.6, 0.3], [0.9, 0.8]], "pen": 0, "width": 3},
    {"shape": "rect", "rect": [0.1, 0.1, 0.3, 0.4], "rot": 0, "width": 2},
    {"shape": "round", "rect": [0.5, 0.5, 0.9, 0.7], "rot": 15.0, "width": 2},
    {"shape": "circle", "cx": 0.4, "cy": 0.5, "r": 0.1, "rect": [0.3, 0.3, 0.5, 0.7], "width": 2},
    {"text_box": True, "rect": [0.2, 0.6, 0.6, 0.8], "rot": 0, "text": "가나", "size_pt": 12},
    {"leader": True, "rect": [0.6, 0.1, 0.9, 0.2], "rot": 0, "box_anchor": [0.6, 0.15], "anchor": [0.3, 0.5],
     "hl_rects": [[0.25, 0.45, 0.35, 0.55]], "tip": "arrow"},
    {"hl": True, "points": [[0.2, 0.5], [0.7, 0.5]], "h": 0.04},
]
images = [{"data": "", "rect": [0.1, 0.2, 0.25, 0.5], "shape": "rect", "alpha": 100, "rot": 0}]

# A
for rot in (90, 180, 270):
    w1, h1 = (H, W) if rot in (90, 270) else (W, H)
    there = pd.rotate_strokes(strokes, rot, W, H)
    back = pd.rotate_strokes(there, pd.inverse(rot), w1, h1)
    for k, (a, b) in enumerate(zip(strokes, back)):
        b2 = dict(b)
        if "rot" in a:
            b2["rot"] = round(float(b2["rot"]) % 360.0, 2)
        chk(near(a, b2, 1e-6), "A 꾸밈 %d 왕복 %d°" % (k, rot), "%s → %s" % (a, b2))
    ib = pd.rotate_images(pd.rotate_images(images, rot, W, H), pd.inverse(rot), w1, h1)
    chk(near(images[0]["rect"], ib[0]["rect"], 1e-4) and round(ib[0]["rot"]) % 360 == 0, "A 삽입 그림 왕복 %d°" % rot, str(ib[0]))

# B
r = pd.rotate_stroke(strokes[1], 90, W, H)
x0, y0, x1, y1 = r["rect"]
chk(abs((x1 - x0) * H - 0.2 * W) < 1e-6 and abs((y1 - y0) * W - 0.3 * H) < 1e-6, "B 상자 픽셀 크기 그대로(160×120)")
chk(r["rot"] == 90.0, "B 개체 rot 에 90 더함")
cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
chk(abs(cx - (1 - 0.25)) < 1e-6 and abs(cy - 0.2) < 1e-6, "B 중심 (0.2,0.25) → (0.75,0.2)", str((cx, cy)))

# C
c = pd.rotate_stroke(strokes[3], 90, W, H)
chk(abs(c["cx"] - 0.5) < 1e-6 and abs(c["cy"] - 0.4) < 1e-6 and abs(c["r"] * H - 0.1 * W) < 1e-6,
    "C 원 중심 (0.4,0.5) → (0.5,0.4), 반지름 80px 그대로", str((c["cx"], c["cy"], c["r"])))

# D
band = {"hl": True, "bands": [[0.2, 0.7, 0.5, 0.04]], "h": 0.04, "points": [[0.2, 0.5], [0.7, 0.5]]}
d180 = pd.rotate_stroke(band, 180, W, H)
chk(near(d180["bands"], [[0.3, 0.8, 0.5, 0.04]]), "D 180° 띠는 띠 그대로 뒤집힌다", str(d180.get("bands")))
d90 = pd.rotate_stroke(band, 90, W, H)
chk("bands" not in d90 and near(d90["points"], [[0.5, 0.2], [0.5, 0.7]]) and abs(d90["h"] * W - 0.04 * H) < 1e-6,
    "D 90° 띠는 가운데 선 두 점, 두께 픽셀 그대로", str(d90))

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
