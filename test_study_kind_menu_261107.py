# -*- coding: utf-8 -*-
"""261107-38(사용자 지시) 단어장 창 '종류 ▾' — 단어장 SOT §11, 디자인 SOT §2.10 단어장 머리줄.

사용자 지시: "종류(접기 버튼 전까지의 내용)를 '종류' 이름으로 드롭다운 버튼으로 만들고, 클릭하여 체크 또는 체크해제 하도록 해. 지금 너무 길어"
A. 둘째 줄 맨 앞은 '종류' 메뉴 단추 하나(InstantPopup) — 종류·표시 체크 아홉은 줄에 없고, [접기] 가 같은 첫 줄에 온다
B. 메뉴: 머리 글자 '종류' 아래 초급·중급·고급·전문용어, 구분선, '표시' 아래 한글뜻·영어뜻·예시·참고문헌·그림
C. 열린 메뉴 안 체크를 실제로 누르면 값이 바뀌고(목록 거르기·levelsChanged) 메뉴는 열린 채
D. 단추 글자 — 하나라도 꺼지면 '종류 n/9'·툴팁에 꺼진 이름, 모두 켜면 '종류', 설정을 넣어도(신호 막고) 맞춰진다
수정 전 코드: 단추·메뉴가 없어 실패.
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, Qt, QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QCheckBox, QToolButton, QWidgetAction

QStandardPaths.setTestModeEnabled(True)
app = QApplication.instance() or QApplication(sys.argv)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

from viewer.widgets.study_panel import StudyPanel
sp = StudyPanel()
sp.resize(420, 600); sp.show(); app.processEvents()
btn = getattr(sp, "btn_kind", None)
LEVELS = ["초급", "중급", "고급", "전문용어"]
SHOWS = ["한글뜻", "영어뜻", "예시", "참고문헌", "그림"]

# ---- A ----
ctrl = sp._ctrl_widget
row_checks = [c.text() for c in ctrl.findChildren(QCheckBox) if c.isVisible()]
chk(isinstance(btn, QToolButton) and btn.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup and btn.menu() is not None,
    "A1 '종류' 메뉴 단추(InstantPopup)", repr(btn))
chk(not (set(row_checks) & set(LEVELS + SHOWS)), "A2 종류·표시 체크 아홉은 둘째 줄에 없다", str(row_checks))
lay = ctrl.layout()
first = [lay.itemAt(i).widget() for i in range(lay.count())][:2]
chk(btn is not None and first[0] is btn, "A3 둘째 줄 맨 앞이 '종류' 단추",
    str([type(w).__name__ + ":" + (getattr(w, "text", lambda: "")() or "") for w in first]))
chk(btn is not None and abs(sp.btn_expand.mapTo(sp, QPoint(0, 0)).y() - btn.mapTo(sp, QPoint(0, 0)).y()) < 4,
    "A4 [접기] 가 '종류' 와 같은 첫 줄(420 폭) — 종전에는 두 줄로 넘쳤다")
chk(not any(isinstance(w, QLabel) and w.text() in ("종류", "표시") for w in ctrl.findChildren(QLabel) if w.isVisible()),
    "A5 줄에 '종류'·'표시' 글자 칸이 따로 없다")
if btn is None:
    print(f"\nFAIL {len(fails)}: {fails}"); sys.stdout.flush(); os._exit(1)

# ---- B ----
m = btn.menu()
acts = m.actions()
chk([type(a).__name__ if isinstance(a, QWidgetAction) else ("sep" if a.isSeparator() else "act") for a in acts]
    == ["QWidgetAction", "sep", "QWidgetAction"], "B1 메뉴 = 종류 판 · 구분선 · 표시 판",
    str([a.isSeparator() for a in acts]))
def page(a):
    w = a.defaultWidget()
    heads = [l.text() for l in w.findChildren(QLabel)]
    return heads, [c.text() for c in w.findChildren(QCheckBox)], w.findChildren(QCheckBox)
h1, c1, cbs1 = page(acts[0]); h2, c2, cbs2 = page(acts[2])
chk(h1 == ["<b>종류</b>"] and c1 == LEVELS, "B2 종류 판: 굵은 머리 글자 · 초급·중급·고급·전문용어", f"{h1} {c1}")
chk(h2 == ["<b>표시</b>"] and c2 == SHOWS, "B3 표시 판: 굵은 머리 글자 · 한글뜻·영어뜻·예시·참고문헌·그림", f"{h2} {c2}")
chk(cbs1 == [sp._chk[lv] for lv in LEVELS] and cbs2 == [sp.chk_ko, sp.chk_en, sp.chk_ex, sp.chk_ref, sp.chk_img],
    "B4 메뉴의 체크가 곧 패널 값(같은 칸)")

# ---- C ----
m.popup(btn.mapToGlobal(QPoint(0, btn.height()))); QTest.qWait(150)
chk(m.isVisible(), "C0 메뉴가 열린다")
win = m.windowHandle()
def click_in_menu(w, x):
    """메뉴 창으로 실제 누름(팝업 길 그대로) — w 안 왼쪽에서 x px, 세로 가운데."""
    p = w.mapTo(m, QPoint(x, w.height() // 2))
    QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p); QTest.qWait(100)
got = []
sp.levelsChanged.connect(lambda: got.append(1))
rows = [{"lemma": "a", "level": "고급"}, {"lemma": "b", "level": "중급"}]
cb = sp._chk["고급"]
was = cb.isChecked()
click_in_menu(cb, 24)                                  # 글자 '고급' 위
chk(cb.isChecked() != was and got, "C1 메뉴 안 '고급' 을 누르면 바뀌고 levelsChanged", f"{was}->{cb.isChecked()} {got}")
chk([r["lemma"] for r in sp.filter_rows(rows)] == ["b"], "C2 목록 거르기도 따라간다", str(sp.filter_rows(rows)))
chk(m.isVisible(), "C3 체크해도 메뉴는 열린 채")
click_in_menu(sp.chk_ref, 24)
chk(not sp.chk_ref.isChecked() and m.isVisible(), "C4 표시 판 '참고문헌' 도 연달아 — 메뉴 열린 채")
click_in_menu(sp._chk["중급"], sp._chk["중급"].width() - 4)   # 글자 오른쪽 빈 곳
chk(m.isVisible() and sp._chk["중급"].isChecked(), "C5 체크 칸 옆 빈 곳을 눌러도 메뉴가 닫히지 않는다(종전 Qt 기본은 닫힘)")
head = acts[0].defaultWidget().findChildren(QLabel)[0]
click_in_menu(head, 6)
chk(m.isVisible(), "C6 머리 글자 '종류' 를 눌러도 닫히지 않는다")
m.hide(); app.processEvents()

# ---- D ----
chk(btn.text() == "종류 6/9" and "초급" in btn.toolTip() and "고급" in btn.toolTip() and "참고문헌" in btn.toolTip(),
    "D1 꺼진 셋(초급·고급·참고문헌) → '종류 6/9', 툴팁에 이름", f"{btn.text()!r} {btn.toolTip()!r}")
for c in sp._kind_checks():
    c.setChecked(True)
chk(btn.text() == "종류" and "꺼짐" not in btn.toolTip(), "D2 모두 켜면 '종류'", repr(btn.text()))
sp.apply_settings({"levels": {"초급": False, "중급": True, "고급": True, "전문용어": True}})
chk(btn.text() == "종류 8/9", "D3 설정을 넣어도(신호 막고) 단추 글자가 맞춰진다", repr(btn.text()))
s = sp.get_settings()
chk(s["levels"] == {"초급": False, "중급": True, "고급": True, "전문용어": True} and s["show_ref"] is True,
    "D4 기억 값 꼴은 그대로(levels·show_*)", str(s["levels"]))
sp2 = StudyPanel()
chk(sp2.btn_kind.text() == "종류 8/9", "D5 처음(기본 초급 꺼짐)은 '종류 8/9'", repr(sp2.btn_kind.text()))

print("\nALL PASS" if not fails else f"\nFAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)
