# -*- coding: utf-8 -*-
"""PDF 쪽 크롭 창 — 박스 안쪽을 끌면 크기 그대로 통째로 옮기기 (마스터 §4.7.15, 261106-9 사용자 지시 'PDF 에도').

실제 `CropDialog` 에 실제 마우스 이벤트(QTest), 오프스크린. 실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3).
A. 박스 안쪽 위 커서 = 이동 모양, 끌면 네 여백이 함께 옮겨지고 크기(위+아래·왼+오른)는 그대로 — % 칸·스타일 값도 따라온다
B. 쪽 밖으로는 나가지 않는다(가장자리에서 멈춤)
C. 변 끌기·적용 쪽·스타일 결과(`result_plan`)는 종전대로 — 옮긴 여백이 그 스타일 값으로 나간다
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_crop_box_move_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def drag(w, a, b, steps=6):
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for k in range(1, steps + 1):
        QTest.mouseMove(w, QPoint(a.x() + (b.x() - a.x()) * k // steps, a.y() + (b.y() - a.y()) * k // steps))
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    app.processEvents()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_crop_box_move_"))
try:
    import fitz
    d = fitz.open()
    for i in range(3):
        d.new_page(width=595, height=842).insert_text((72, 72 + i * 20), "page %d" % (i + 1))
    pdf = tmp / "doc.pdf"
    d.save(str(pdf)); d.close()

    from viewer.widgets.crop_dialog import CropDialog
    dlg = CropDialog(str(pdf), current_page=0, parent=None)
    dlg.show()
    for _ in range(30):
        app.processEvents()
    for k, v in enumerate((20.0, 20.0, 20.0, 20.0)):
        dlg.spins[k].setValue(v)
    app.processEvents()
    cv = dlg.canvas
    r = cv._img_rect()
    chk(not r.isNull(), "준비 — 미리보기 그림이 있다")
    c = cv._crop_rect(r)
    mid = QPoint(int(c.center().x()), int(c.center().y()))

    # A
    QTest.mouseMove(cv, mid); app.processEvents()
    chk(cv.cursor().shape() == Qt.CursorShape.SizeAllCursor, "A 박스 안쪽 위 커서 = 이동 모양")
    drag(cv, mid, QPoint(mid.x() + int(r.width() * 0.10), mid.y() - int(r.height() * 0.05)))
    m = [round(sp.value(), 1) for sp in dlg.spins]
    chk(abs(m[0] - 15) <= 0.6 and abs(m[1] - 25) <= 0.6 and abs(m[2] - 30) <= 0.6 and abs(m[3] - 10) <= 0.6,
        "A 안쪽 끌기 = 크기 그대로 옮김(오른쪽 +10%·위 −5%) — % 칸이 따라온다", str(m))
    chk(abs(m[0] + m[1] - 40) < 0.2 and abs(m[2] + m[3] - 40) < 0.2, "A 박스 크기는 그대로", str(m))
    st = dlg._style()
    chk([round(v, 1) for v in st["margins"]] == m, "A 스타일 값(적용될 여백)도 옮긴 값", str(st["margins"]))

    # B
    c = cv._crop_rect(r)
    mid = QPoint(int(c.center().x()), int(c.center().y()))
    drag(cv, mid, QPoint(mid.x() - int(r.width() * 0.8), mid.y() + int(r.height() * 0.8)))
    m = [round(sp.value(), 1) for sp in dlg.spins]
    chk(m[2] == 0.0 and m[1] == 0.0 and abs(m[3] - 40) < 0.2 and abs(m[0] - 40) < 0.2, "B 쪽 밖으로 나가지 않는다(왼쪽·아래 가장자리에서 멈춤)", str(m))

    # C
    c = cv._crop_rect(r)
    top = QPoint(int(c.center().x()), int(c.top()))
    drag(cv, top, QPoint(int(c.center().x()), int(c.top() + r.height() * 0.05)))
    m2 = [round(sp.value(), 1) for sp in dlg.spins]
    chk(abs(m2[0] - 45) <= 0.6 and m2[1] == 0.0, "C 변 끌기는 종전대로(위 변만 → 크기가 바뀐다)", str(m2))
    plan = dlg.result_plan()
    chk(not plan["reset"] and plan["pages"] and any([round(v, 1) for v in s_["margins"]] == m2 for s_ in plan["styles"]),
        "C 결과(result_plan)에 옮기고 고친 여백이 그대로", str([s_["margins"] for s_ in plan["styles"]]))
    dlg.reject()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
