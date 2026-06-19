# -*- coding: utf-8 -*-
"""260606-16: 병합창 우측 ▲▼ 이동·삭제 위치·'스크린샷 리스트 추가' 명칭."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication, QPushButton
app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.merge_dialog import MergeFilesDialog

d = MergeFilesDialog([r"C:/x/a.pdf", r"C:/x/b.pdf", r"C:/x/c.pdf"], None, [r"C:/s/1.png"])
d.left.selectAll(); d._move_selected()
names = lambda: [d.right.item(i).data(d._DATA)["name"] for i in range(d.right.count())]
check("우측 3개", d.right.count() == 3, f"{names()}")
# 마지막(c) 선택 → 위로 2번
d.right.item(2).setSelected(True)
d._move_right(-1)
check("c 위로 1칸", names() == ["a", "c", "b"], f"{names()}")
d._move_right(-1)
check("c 위로 2칸", names() == ["c", "a", "b"], f"{names()}")
# 맨 위에서 위로 → 변화 없음
d._move_right(-1)
check("맨 위에서 위로 무변화", names() == ["c", "a", "b"])
# 다중 선택 이동
d.right.clearSelection()
d.right.item(1).setSelected(True); d.right.item(2).setSelected(True)  # a,b
d._move_right(-1)
check("a,b 블록 위로", names() == ["a", "b", "c"], f"{names()}")
# 아래로
d.right.clearSelection(); d.right.item(0).setSelected(True)
d._move_right(+1)
check("a 아래로", names() == ["b", "a", "c"], f"{names()}")

# 버튼 명칭
btns = [b.text() for b in d.findChildren(QPushButton)]
check("'스크린샷 리스트 추가' 버튼 존재", "스크린샷 리스트 추가" in btns, f"{btns}")
check("'스크린샷 추가'(구명칭) 없음", "스크린샷 추가" not in btns)
check("▲▼ 이동 버튼 존재", "▲" in btns and "▼" in btns)
check("삭제 버튼 존재", "삭제" in btns)

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
