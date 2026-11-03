# -*- coding: utf-8 -*-
"""261103-5: 저장된 OCR 낱말로 본문을 끌어 고르면 칠이 띄엄띄엄 났다 (텍스트 창 SOT §3.6.16, 입력 장치 SOT §2.8).

사용자 보고: "_96 파일에서 뷰어 본문을 마우스로 긁을 때 문장이 제대로 안 긁힘".
`StudyStore.get_page_words` 는 낱말을 `ORDER BY y0, x0` 로 준다 — 한 줄의 한글 음절은 위끝이 1~2px 씩 달라 줄 안이 뒤섞인다.
이 검사는 **그 차례로** 낱말을 넣어 주고(앱의 공급자와 같은 꼴), 본문 보기에 **실제 마우스 누름·끌기·놓기**를 보내
칠한 낱말과 고른 글을 센다.
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPointF
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
import modal_guard
guard = modal_guard.install(label=lambda: "본문 끌어 고르기", echo=False)   # 마스터 §14.7.2 의 6
# 사용자 실제 설정 폴더(색인·settings.json)를 쓰지 않는다 — 마스터 §14.7.2 의 3
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_drag_ocr_order_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


DPI = 300
LINES = ["포장의 역할은 도로 위를", "움직이는 모든 교통수단이"]


def ocr_words():
    """Tesseract 처럼 한글을 음절마다 낱말로, 위끝을 음절마다 1~2px 다르게 — 그리고 study.db 처럼 `y0, x0` 차례로."""
    ws, jit = [], [0, 2, 1, 0, 2, 1, 2, 0]
    for li, line in enumerate(LINES):
        x, y = 300.0, 500.0 + li * 120
        for wi, word in enumerate(line.split()):
            for ci, ch in enumerate(word):
                j = jit[(wi + ci) % len(jit)]
                ws.append({"surface": ch, "x0": x, "y0": y + j, "x1": x + 40, "y1": y + 45 + j, "conf": 0.9})
                x += 44
            x += 40
    return sorted(ws, key=lambda w: (w["y0"], w["x0"]))


root = tempfile.mkdtemp(prefix="polypdf_dragocr_")
try:
    src = os.path.join(root, "scan.pdf")
    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    pg.draw_rect(fitz.Rect(20, 20, 40, 40), color=(0, 0, 0), fill=(0, 0, 0))   # 글자층 없는 쪽(스캔 흉내)
    d.save(src)
    d.close()

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1200, 900); mw.show(); app.processEvents()
    mw._load_main(HistoryItem(src, 0, "", "bookmark")); app.processEvents()
    m = mw.main_view
    m.set_ocr_words_provider(lambda path, page: (ocr_words(), DPI))
    m._page_words = []
    app.processEvents()

    z = m._zoom or 1.0
    k = 72.0 / DPI
    vp = m.view.viewport()

    def at(px_x, px_y):
        """쪽 그림 픽셀(300dpi) → 뷰포트 좌표."""
        p = m.view.mapFromScene(QPointF(px_x * k * z, px_y * k * z))
        return p

    first = (300 + 20, 500 + 22)                        # `포`
    last_x = 300 + sum(len(w) * 44 + 40 for w in LINES[1].split()) - 40 - 20
    last = (last_x, 620 + 22)                           # `이`(둘째 줄 끝)
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=at(*first))
    app.processEvents()
    QTest.mouseMove(vp, at(first[0] + 200, first[1] + 60))
    QTest.mouseMove(vp, at(*last))
    app.processEvents()
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=at(*last))
    app.processEvents()

    got = m._sel_text
    want = "\n".join(LINES)
    chk(got == want, "끌어 고른 글이 두 줄 그대로(줄 안 차례 유지)", repr(got))
    n_words = sum(len(l.split()) for l in LINES)
    chk(len(m._sel_items) == n_words, "칠한 낱말 상자 = 두 줄의 낱말 수(%d)" % n_words, str(len(m._sel_items)))
    # 칠한 상자가 겹치지 않고 줄마다 왼→오른으로 이어진다 — 흩어진 음절을 붙인 상자는 다른 낱말 자리까지 덮는다
    mid = 590 * k * z                                    # 두 줄 사이(픽셀 590)
    rs = sorted((it.rect().center().y() > mid, it.rect().x(), it.rect().right()) for it in m._sel_items)
    ok = all(not (a[0] == b[0] and b[1] < a[2] - 0.5) for a, b in zip(rs, rs[1:]))
    chk(ok, "칠한 상자가 서로 겹치지 않는다")

    mw.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("FAIL", len(fails), fails) if fails else print("ALL PASS")
sys.stdout.flush()
os._exit(1 if fails else 0)                  # Qt 소멸 때의 크래시가 판정을 덮지 않게(다른 창 검사와 같이)
