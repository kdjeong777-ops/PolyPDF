# -*- coding: utf-8 -*-
"""260910-4: 줄 잇기 정밀화와 스크린샷 칸 높이
(텍스트 창 SOT §3.7.6·§3.7.7 · 화면 디자인 SOT §2.8.2).

사용자 보고 둘.
  (1) "스크린샷창이 위에 떠 있어. 아래에 맞추고, 위의 텍스트창 높이가 결정되도록."
  (2) "'~구성했습니다. 이 그룹은 / 균형~' 과 '~함량 시험 포 / 함~' 은 붙여야 맞는데
      줄이 나뉘었다. 제목 줄과 그렇지 않은 줄 구분을 더 정밀하게."

(2) 는 **서로 다른 조건**에서 막혀 있었다 — 앞엣것은 ④(오른쪽이 덜 참), 뒤엣것은
⑦(`함)` 을 목록 표시로 봄). 둘을 따로 고쳤으므로 따로 검사한다.
"""
import os, sys, glob
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from viewer import text_extract2 as tx

print("=== (1) 목록 표시 판정 — 아무 한글이나 받지 않는다 (§3.7.6 나) ===")
for t in ("가) 첫째", "나) 둘째", "하) 마지막", "1. 하나", "(1) 하나", "- 항목", "① 하나"):
    chk(tx._starts_list(t), "(1) 진짜 목록은 그대로 목록이다", repr(t))
for t in ("함)을 평가하는", "포)를", "것)이다", "험)에서"):
    chk(not tx._starts_list(t), "(1) 낱말 꼬리는 목록이 아니다", repr(t))
chk(tx.KO_LIST_ORDER == "가나다라마바사아자차카타파하",
    "(1) 가나다 차례가 상수로 있다")

print()
print("=== (2) 닫히지 않은 괄호는 이어지는 글이다 (§3.7.6 나) ===")
chk(tx._unclosed_paren("배합 시험(다양한 입도 및 아스팔트 함량 시험 포"),
    "(2) 열린 괄호를 알아본다")
chk(not tx._unclosed_paren("배합 시험(다양한 입도) 평가"), "(2) 닫힌 괄호는 아니다")
chk(not tx._unclosed_paren("보통 문장이다"), "(2) 괄호가 없으면 아니다")

print()
print("=== (3) 첫 어절 폭은 그 줄 스스로에게서 잰다 (§3.7.6 가) ===")
w = tx._first_word_width({"text": "균형 혼합물 설계", "rect": (0, 0, 80, 10)})
chk(9.0 < w < 21.0, "(3) 한글 두 글자 어절 폭이 그럴듯하다", "%.1f pt" % w)
chk(tx._first_word_width({"text": "", "rect": (0, 0, 80, 10)}) == 0.0,
    "(3) 빈 줄은 0")
chk(tx._first_word_width({"text": "가나", "rect": None}) == 0.0,
    "(3) 사각형이 없으면 0")
chk(tx.JOIN_GAP_MAX == 0.40, "(3) 빈칸 한도가 상수로 있다", str(tx.JOIN_GAP_MAX))

print()
print("=== (4) 빈칸 넣기는 '왜 넘어갔는지' 로 (§3.7.7) ===")
chk(tx._join_sep("이 그룹은", "균형 혼합물", True) == " ",
    "(4) 어절이 안 들어가 넘어갔으면 빈칸")
chk(tx._join_sep("의무사", "용대상", False) == "",
    "(4) 줄이 꽉 차 넘어갔으면 붙임(낱말 가운데일 수 있다)")
chk(tx._join_sep("performance-", "based spec", False) == "-drop",
    "(4) 영문 분철은 그대로 뗀다")
chk(tx._join_sep("ends with space ", "next", False) == " ",
    "(4) 원문이 빈칸으로 끝나면 빈칸")
chk(tx._join_sep("the same", "application.", False) == " ",
    "(4) 영문끼리는 늘 빈칸")

print()
print("=== (5) 신고된 두 곳 — 실측한 좌표를 그대로 세운다 ===")
# 실측(`아스팔트 혼합물의 균형 잡힌 배합 설계로 나아가기.pdf` 1쪽). 업무 문서를 직접
# 열지 않고 **잰 값으로 재현**한다 — 그 파일이 없는 기계에서도 같은 답이 나와야 한다.


def row(text, x0, y0, x1, y1, style="body", kind="text", size=10.0):
    return {"text": text, "rect": (x0, y0, x1, y1), "style": style,
            "kind": kind, "size": size}


# (가) ④ — 오른쪽이 11.4pt 모자랐지만 뒷줄 첫 어절 `균형` 은 그보다 넓다
caseA = [
    row("2015년 9월, FHWA 혼합물 및 건설 전문가 태스크 그룹은 균형 혼합물 설계 태스크 포스를 구성했습니다. 이 그룹은",
        28.5, 545.9, 556.0, 557.1),
    row('균형 혼합물 설계(BMD)를 "혼합물의 노화, 교통량, 기후 및 포장 구조 내 위치를 고려하여 다양한 손상 모드를 다루는 적절',
        28.5, 560.9, 567.3, 572.1),
    row("두 가지 이상의 역학적 시험을 통합하여 혼합물이 일반적인 손상에 얼마나 잘 저항하는지 평가합니다. 태스크 포스는 BMD 사용에",
        28.5, 590.9, 558.0, 602.1),
]
outA = tx.join_sentences(caseA)
chk(len(outA) < len(caseA), "(5가) 11.4pt 모자란 줄도 이어진다", "%d -> %d" % (len(caseA), len(outA)))
chk("이 그룹은 균형 혼합물 설계(BMD)" in outA[0]["text"],
    "(5가) 빈칸 하나로 이어진다(붙여 쓰지 않는다)", repr(outA[0]["text"][95:130]))

# (나) ⑦ — `함)` 을 목록 표시로 보던 곳. 앞줄에 `시험(` 이 열려 있다
caseB = [
    row("3. 성능 기반 설계. 이 접근 방식은 체적 배합 설계를 생략하고 성능 시험을 통해 배합 시험(다양한 입도 및 아스팔트 함량 시험 포",
        37.4, 730.9, 561.0, 742.1),
    row("함)을 평가하는 것부터 시작합니다. 아스팔트 바인더 및 골재 특성에 대한 최소 요구 사항을 설정할 수 있습니다. 기존의 체적",
        48.5, 745.9, 567.4, 757.1),
]
outB = tx.join_sentences(caseB)
chk(len(outB) == 1, "(5나) `함)` 을 목록으로 보지 않는다", str(len(outB)))
chk("아스팔트 함량 시험 포함)을 평가하는" in outB[0]["text"],
    "(5나) `포` + `함)` 이 `포함)` 이 된다", repr(outB[0]["text"][-60:]))

# (다) 이어서는 안 되는 것 — 링크 목록(크게 남는 줄)
links = [
    row("아스팔트 혼합물의 균형 잡힌 배합 설계로 나아가기 (balanced-mix.html)", 28.5, 100.0, 313.0, 111.2),
    row("GSB 값이 맞습니까? (gsb.html)", 28.5, 115.0, 163.7, 126.2),
    row("아스팔트 필름 두께에 대한 오해 해소 (film-thickness.html)", 28.5, 130.0, 567.4, 141.2),
]
outL = tx.join_sentences(links)
chk(len(outL) == 3, "(5다) 크게 남는 목록 줄은 이어지지 않는다", str(len(outL)))

# (라) 표·그림 제목은 첫머리로 막는다
cap = [row("표 1 잔골재의 품질", 60.0, 100.0, 250.0, 110.0),
       row("항목이 이어진다.", 60.0, 112.0, 300.0, 122.0)]
chk(len(tx.join_sentences(cap)) == 2, "(5라) 표 제목은 다음 줄과 이어지지 않는다")
chk(tx._is_caption("그림 2 흐름도") and tx._is_caption("Table 1 Results"),
    "(5라) 그림·Table 제목도 알아본다")
chk(not tx._is_caption("표시된 값") and not tx._is_caption("그림자가 진다"),
    "(5라) 비슷하게 생긴 낱말은 제목이 아니다")

print()
print("=== (6) 스크린샷 칸은 내용 높이까지만 (디자인 §2.8.2) ===")
from PyQt6.QtWidgets import QApplication, QSplitter, QTextEdit
from PyQt6.QtCore import Qt
app = QApplication.instance() or QApplication([])
from viewer.widgets.strip import MiniStrip
st = MiniStrip("스크린샷", max_items=30)
st.set_expand(False)
cap = st.maximumHeight()
chk(0 < cap < 400, "(6) 접힘 모드에 최대 높이가 걸린다", "%d px" % cap)
chk(abs(cap - st.sizeHint().height()) <= 8,
    "(6) 그 한도가 내용 높이다", "%d vs %d" % (cap, st.sizeHint().height()))
sp = QSplitter(Qt.Orientation.Vertical)
top = QTextEdit()
sp.addWidget(top); sp.addWidget(st)
sp.setStretchFactor(0, 1); sp.setStretchFactor(1, 0)
sp.resize(500, 1000)
sp.show()
app.processEvents()
chk(st.height() <= cap, "(6) 창이 커도 그 높이를 넘지 않는다", "%d px" % st.height())
chk(top.height() > 600, "(6) 남는 높이는 위 칸이 가져간다", "%d px" % top.height())
st.set_expand(True)
chk(st.maximumHeight() > 10000, "(6) 펼침 모드에서는 한도를 푼다")
st.set_expand(False)
chk(st.maximumHeight() == cap, "(6) 다시 접으면 한도가 돌아온다")

print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
