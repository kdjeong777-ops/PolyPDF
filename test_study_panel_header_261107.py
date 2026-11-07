# -*- coding: utf-8 -*-
"""261107-34(사용자 지시) 단어장 창 머리줄 — 단어장 SOT §11.1, 디자인 SOT §2.10 단어장 머리줄·§4.5 `ocr`.

사용자 지시: "단어장의 +버튼 왼쪽에 이 PDF 사전 -> '사전'", "'단어장' 아이콘을 '사전' 왼쪽으로 이동('어장'이라고 보이는 버튼은
검토하니, OCR하는 것이라, 'OCR'로 아이콘을 만들어서 사용", "'출처' 버튼은 '사전'버튼과 기능이 유사하여 삭제".
A. 머리줄 차례: 제목 · [OCR](단어장 생성) · [사전] · [＋] · [✎] · [사용자](261107-34 §11.4) · [Word] · [mp3]
B. [OCR] 은 그림만(글자 없음·26×26·colorIcon='ocr') — 단어장을 만들고 난 뒤에도 글자가 붙지 않는다(종전 '어장' 으로 잘려 보였다)
C. `ocr` 그림 — 밝은·어두운 테마 모두 비어 있지 않고 ▶ 색
D. '출처 ▾' 단추·메뉴가 없다 · [사전] 은 이 PDF 의 사전 창을 연다
수정 전 코드: 차례·글자·출처가 달라 실패.
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QLabel

QStandardPaths.setTestModeEnabled(True)
app = QApplication.instance() or QApplication(sys.argv)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

from viewer.widgets.study_panel import StudyPanel
from viewer.widgets import icons
sp = StudyPanel()
sp.resize(420, 600); sp.show(); app.processEvents()

# ---- A ----
hdr = sp.layout().itemAt(0).layout()
ws = [hdr.itemAt(i).widget() for i in range(hdr.count()) if hdr.itemAt(i).widget() is not None]
want = [None, sp.btn_build, sp.btn_file_dict, sp.btn_add, sp.btn_edit, getattr(sp, "btn_user_terms", None), sp.btn_word, sp.btn_mp3]
chk(len(ws) == len(want) and isinstance(ws[0], QLabel) and ws[1:] == want[1:],
    "A1 머리줄 차례: 제목 · OCR · 사전 · ＋ · ✎ · 사용자 · Word · mp3",
    str([type(w).__name__ + ":" + (getattr(w, "text", lambda: "")() or "") for w in ws]))
chk(sp.btn_file_dict.text() == "사전", "A2 [사전] 이름(종전 '이 PDF 사전')", sp.btn_file_dict.text())
xs = [w.mapTo(sp, w.rect().topLeft()).x() for w in ws[1:]]
chk(xs == sorted(xs), "A3 화면에서도 그 차례로 왼쪽→오른쪽", str(xs))

# ---- B ----
b = sp.btn_build
chk(b.text() == "" and not b.icon().isNull() and b.width() == 26 and b.height() == 26 and b.property("colorIcon") == "ocr",
    "B1 [OCR] 은 그림만·26×26·colorIcon='ocr'", f"{b.text()!r} {b.width()}x{b.height()} {b.property('colorIcon')}")
sp.set_building(True); sp.set_building(False)
chk(b.text() == "" and "단어장" in b.toolTip(), "B2 만들고 난 뒤에도 글자가 붙지 않는다(설명은 툴팁)", repr(b.text()))

# ---- C ----
for dark in (False, True):
    pm = icons.color_icon("ocr", dark=dark, size=16).pixmap(32, 32)
    img = pm.toImage()
    want_c = QColor(icons.ACCENT["play"][dark])
    n_ink = n_near = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 200:
                n_ink += 1
                if abs(c.red() - want_c.red()) + abs(c.green() - want_c.green()) + abs(c.blue() - want_c.blue()) < 60:
                    n_near += 1
    chk(n_ink > 40 and n_near >= 0.8 * n_ink, f"C1 ocr 그림({'어두운' if dark else '밝은'} 테마) — 비어 있지 않고 ▶ 색", f"{n_ink} {n_near}")

# ---- D ----
chk(not hasattr(sp, "btn_src") and not hasattr(sp, "sourceToggled") and not hasattr(sp, "styleChosen"),
    "D1 '출처 ▾' 단추·신호가 없다")
got = []
sp.fileDictRequested.connect(lambda: got.append(1))
sp.btn_file_dict.click()
chk(got == [1], "D2 [사전] 은 이 PDF 의 사전 창을 연다(fileDictRequested)")

print("\nALL PASS" if not fails else f"\nFAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)
