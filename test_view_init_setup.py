# -*- coding: utf-8 -*-
"""260910-6: 1회성 설정은 `__init__` 에 (마스터 SOT §19.1.3).

스크롤바 정책 2줄·포커스 정책·`_image_mode` 초기화가 `mouseMoveEvent` 의 **맨 끝**에
있어 **마우스가 움직일 때마다** 실행되고 있었다. 고치기 전에 실제 영향을 재 봤다.

  · 스크롤바 정책은 바뀌지 않았다 — load_document/load_image 가 같은 값을 넣는다
  · `_image_mode` 는 실제로 덮어써졌다 — load_image 의 True 가 첫 이동에 False
  · 갓 만든 뷰에는 `_image_mode` 속성이 아예 없었다

이 검사는 그 셋이 되돌아오지 않게 한다. 특히 **모드별 정책을 마우스 이동이 되돌리지
않는다**는 것을 손으로 다른 값을 넣어 확인한다 — 지금 값이 우연히 같아 증상이 없는
상태라, 그것만 보면 회귀를 놓친다.
"""
import os, sys, inspect, tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from PyQt6.QtWidgets import QApplication, QGraphicsScene
from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent, QImage, QColor
app = QApplication.instance() or QApplication([])

from viewer.widgets.main_view import _PdfGraphicsView, MainView


def move(view, x=30.0, y=30.0):
    """진짜 QMouseEvent 를 viewport 에 보낸다(버튼 없음 = 호버 경로)."""
    ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
                     Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    app.sendEvent(view.viewport(), ev)


def make_view():
    v = _PdfGraphicsView()
    v.setScene(QGraphicsScene(0, 0, 400, 3000))
    v.resize(400, 400)
    v.show()
    app.processEvents()
    return v


print("=== (1) 생성 시점에 이미 갖춰져 있다 ===")
v = make_view()
chk(hasattr(v, "_image_mode"), "(1) `_image_mode` 가 생성 직후 존재한다",
    repr(getattr(v, "_image_mode", "<없음>")))
chk(getattr(v, "_image_mode", None) is False, "(1) 초기값은 False")
chk(v.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
    "(1) 세로 스크롤바 정책이 생성 직후 AlwaysOff (v1.6.8 F1)",
    v.verticalScrollBarPolicy().name)
chk(v.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded,
    "(1) 가로 스크롤바 정책이 생성 직후 AsNeeded",
    v.horizontalScrollBarPolicy().name)
chk(v.focusPolicy() == Qt.FocusPolicy.StrongFocus,
    "(1) 포커스 정책이 생성 직후 StrongFocus", v.focusPolicy().name)

print()
print("=== (2) mouseMoveEvent 는 1회성 설정을 하지 않는다 (본문 검사) ===")
srcm = inspect.getsource(_PdfGraphicsView.mouseMoveEvent)
chk("ScrollBarPolicy" not in srcm,
    "(2) mouseMoveEvent 본문에 스크롤바 정책 설정이 없다")
chk("setFocusPolicy" not in srcm,
    "(2) mouseMoveEvent 본문에 포커스 정책 설정이 없다")
chk("_image_mode" not in srcm,
    "(2) mouseMoveEvent 본문이 `_image_mode` 를 건드리지 않는다")

print()
print("=== (3) 모드별 정책을 마우스 이동이 되돌리지 않는다 (되돌리던 결함) ===")
v.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
move(v)
app.processEvents()
chk(v.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
    "(3) 손으로 넣은 AlwaysOn 이 마우스 이동 뒤에도 남아 있다",
    v.verticalScrollBarPolicy().name)

print()
print("=== (4) 이미지 모드 상태값이 마우스 이동에 살아남는다 ===")
png = os.path.join(tempfile.gettempdir(), "_t_view_init_shot.png")
img = QImage(800, 2400, QImage.Format.Format_RGB32)
img.fill(QColor("white"))
img.save(png)

m = MainView()
m.resize(500, 400)
m.show()
app.processEvents()
m.load_image(png)
app.processEvents()
chk(m.view._image_mode is True, "(4) load_image 직후 _image_mode 가 True")
before = (m.view.verticalScrollBarPolicy(), m.view.horizontalScrollBarPolicy())
for _ in range(5):
    move(m.view, 30.0 + _, 30.0)
app.processEvents()
chk(m.view._image_mode is True,
    "(4) 마우스를 움직여도 _image_mode 가 True 로 남는다",
    repr(m.view._image_mode))
after = (m.view.verticalScrollBarPolicy(), m.view.horizontalScrollBarPolicy())
chk(before == after, "(4) 이미지 모드 스크롤바 정책이 마우스 이동에 변하지 않는다",
    before[0].name + "/" + before[1].name + " -> " + after[0].name + "/" + after[1].name)

print()
print("=== (5) PDF 모드도 같다 ===")
from test_fixtures import text_pdf
m2 = MainView()
m2.resize(500, 400)
m2.show()
app.processEvents()
m2.load_document(text_pdf(), 0)
app.processEvents()
chk(m2.view._image_mode is False, "(5) load_document 직후 _image_mode 가 False")
b2 = (m2.view.verticalScrollBarPolicy(), m2.view.horizontalScrollBarPolicy())
for _ in range(5):
    move(m2.view, 30.0 + _, 30.0)
app.processEvents()
a2 = (m2.view.verticalScrollBarPolicy(), m2.view.horizontalScrollBarPolicy())
chk(b2 == a2, "(5) PDF 모드 스크롤바 정책이 마우스 이동에 변하지 않는다",
    b2[0].name + "/" + b2[1].name)

print()
print("=== (6) 260910-5 의 경계 상태값은 그대로 __init__ 에 있다 (§19.1) ===")
v2 = make_view()
chk(v2._edge_dir == 0 and v2._edge_ms == 0.0 and v2._edge_sum == 0,
    "(6) _edge_dir/_edge_ms/_edge_sum 이 생성 직후 초기화돼 있다")

print()
if fails:
    print("실패", len(fails), "건:", *fails, sep=chr(10) + "  - ")
    sys.exit(1)
print("전부 통과")
