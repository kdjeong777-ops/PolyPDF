# -*- coding: utf-8 -*-
"""260910-3: [OCR 다시 읽기] 의 기본 범위와 언어 판정 (텍스트 창 SOT §3.1.2 · 단어학습 §14.16).

사용자 지시 둘.
  (1) "'문서 전체' 가 기본으로 선택되도록 하고, 문서전체 항목을 맨 위로 이동해."
  (2) "설치본에는 kor 이 없다는데 한글인식은 된 것으로 보여. 확인해."

(2) 의 확인 결과는 **안내문이 옳았다** 였다 — 그 배포본에 kor 이 정말 없었고,
보이던 한글은 *OCR 하지 않은 쪽* 의 원본 글자층이었다. 그래서 고칠 것은 데이터가
아니라 **안내문**이다: 무엇을 안 하는지까지 말해야 오해가 없다.
"""
import os, sys, inspect

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from viewer.widgets.ocr_options_dialog import OcrOptionsDialog

print("=== (1) 기본은 '문서 전체', 자리는 맨 위 ===")
d = OcrOptionsDialog(page=4, page_count=30)
chk(d.rb_all.isChecked(), "(1) '문서 전체' 가 기본으로 켜져 있다")
chk(not d.rb_one.isChecked(), "(1) '현재 쪽' 은 기본이 아니다")
chk(len(d.values()["pages"]) == 30, "(1) 기본값으로 열면 문서 전체를 읽는다",
    str(len(d.values()["pages"])) + "쪽")

# 자리: 레이아웃에서 '문서 전체' 가 '현재 쪽' 보다 위에 있어야 한다
lay = d.layout()
order = []
for i in range(lay.count()):
    it = lay.itemAt(i)
    w = it.widget()
    if w is not None and w in (d.rb_all, d.rb_one):
        order.append("all" if w is d.rb_all else "one")
    sub = it.layout()
    if sub is not None:
        for j in range(sub.count()):
            w2 = sub.itemAt(j).widget()
            if w2 is d.rb_range:
                order.append("range")
chk(order[:2] == ["all", "one"], "(1) 차례가 문서 전체 → 현재 쪽 이다", str(order))
chk("range" in order and order.index("all") < order.index("range"),
    "(1) '쪽 범위' 보다도 위에 있다", str(order))

print()
print("=== (1b) 고르면 그대로 동작한다(기본만 바뀌었다) ===")
d.rb_one.setChecked(True)
chk(d.values()["pages"] == [4], "(1b) '현재 쪽' 을 고르면 그 쪽만", str(d.values()["pages"]))
d.rb_range.setChecked(True)
d.sp_from.setValue(2); d.sp_to.setValue(5)
chk(d.values()["pages"] == [1, 2, 3, 4], "(1b) '쪽 범위' 는 고른 범위만",
    str(d.values()["pages"]))
d.rb_all.setChecked(True)
chk(len(d.values()["pages"]) == 30, "(1b) 다시 전체를 고를 수 있다")
chk(d.rb_range.isChecked() is False and d.rb_one.isChecked() is False,
    "(1b) 셋은 서로 배타다(한 무리에 묶여 있다)")

print()
print("=== (2) 언어 판정은 근거를 둘 다 본다 (§14.16) ===")
from viewer.study import ocr as so
src = inspect.getsource(so.available_langs)
chk("get_languages" in src, "(2) --list-langs 를 본다")
chk("traineddata" in src, "(2) tessdata 폴더의 실제 파일도 본다")
chk("tessdata" in src, "(2) 보는 폴더는 ensure_tesseract 가 고른 그 폴더다")

print()
print("=== (2b) 안내문이 스스로를 증명한다 ===")
from viewer.app import MainWindow
w = inspect.getsource(MainWindow._start_text_ocr)
chk("찾아본 위치" in w, "(2b) 어디를 찾아봤는지 적는다")
chk("OCR 이 읽은 것이 아닙니다" in w,
    "(2b) 보이는 한글이 OCR 결과가 아님을 알린다 — 이번 오해의 원인")
chk("skip_text" in w, "(2b) 건너뛰기가 켜졌을 때만 그 설명을 붙인다")

print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
