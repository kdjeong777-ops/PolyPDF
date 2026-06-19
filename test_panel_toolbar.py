"""260606-25: 패널 툴바 재설계 통합 테스트 (offscreen)."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication, QToolButton
from viewer.app import MainWindow

app = QApplication.instance() or QApplication(sys.argv)
mw = MainWindow()
mw.show()
app.processEvents()

fails = []

def chk(cond, msg):
    print(("PASS" if cond else "FAIL"), "-", msg)
    if not cond:
        fails.append(msg)

# 1) 패널 툴바 기본 보이기
chk(mw._panel_toolbar.isVisible(), "패널 툴바 기본 보이기")

# 2) 옛 토글 버튼이 툴바에 없음 (QAction 객체는 내부 상태로 유지)
acts = mw._panel_toolbar.actions()
btn_texts = []
for a in acts:
    w = mw._panel_toolbar.widgetForAction(a)
    if isinstance(w, QToolButton):
        btn_texts.append(w.text())
print("버튼 목록:", btn_texts)
expected = ["1단", "2단", "검색", "단어장", "스크린샷", "전체화면",
            "PDF병합", "책갈피·단어장 동시 생성", "책갈피 생성",
            "단어장 생성", "암호화", "스크린샷 PDF 저장"]
for e in expected:
    chk(e in btn_texts, f"버튼 존재: {e}")
chk("🔎 검색·단어" not in btn_texts, "옛 검색 토글 버튼 제거됨")
chk("🖼 스크린샷" not in btn_texts, "옛 스크린샷 토글 버튼 제거됨")

# 3) 내부 상태 QAction 유지
chk(hasattr(mw, "act_toggle_search") and hasattr(mw, "act_toggle_shot"),
    "act_toggle_search/shot 내부 유지")

# 4) 뷰어 모드 동작
mw._vm_single()
chk(not mw.act_split.isChecked(), "1단: split off")
chk(not mw.act_toggle_search.isChecked(), "1단: search off")
chk(not mw.act_toggle_shot.isChecked(), "1단: shot off")

mw._vm_split()
chk(mw.act_split.isChecked(), "2단: split on")

mw._vm_search()
chk(not mw.act_split.isChecked(), "검색: split off")
chk(mw.act_toggle_search.isChecked(), "검색: search on")
chk(mw.search_tabs.currentWidget() is mw.search_area, "검색: 검색 탭 선택")

mw._vm_study()
chk(mw.act_toggle_search.isChecked(), "단어장: search on")
chk(mw.search_tabs.currentWidget() is mw.study_panel, "단어장: 단어장 탭 선택")

mw._vm_shot()
chk(not mw.act_split.isChecked(), "스크린샷: split off")
chk(not mw.act_toggle_search.isChecked(), "스크린샷: search off")
chk(mw.act_toggle_shot.isChecked(), "스크린샷: shot on")

# 5) 패널 버튼 스타일/가운데 정렬 (260606-26)
chk(len(getattr(mw, "_panel_btns", [])) == 12, "패널 버튼 12개 등록(암호화 포함)")
mw._style_panel_toolbar(True)
chk("#48" in mw._panel_btns[0].styleSheet(), "다크 스타일 적용(옅은 회색)")
mw._style_panel_toolbar(False)
chk("#e2e2e2" in mw._panel_btns[0].styleSheet(), "라이트 스타일 적용(짙은 회색 배경)")
chk(mw._panel_btns[0].property("panelBtn") is True, "panelBtn 속성")

# 6) 썸네일 번호 하단 배치 (260606-26)
from viewer.widgets.thumbs_list import PageThumbs
pt = PageThumbs()
chk(pt.NUM_BAND > 0, "썸네일 번호 띠 높이>0")
chk(pt.list.iconSize().height() == pt._thumb_size.height() + pt.NUM_BAND,
    "아이콘 높이에 번호 띠 포함")

# 7) 좌측 정렬 - Expanding 스페이서가 없어야 함 (260606-27)
from PyQt6.QtWidgets import QWidget as _QW, QSizePolicy as _SP
expanding = 0
for a in mw._panel_toolbar.actions():
    w = mw._panel_toolbar.widgetForAction(a)
    if isinstance(w, _QW) and w.sizePolicy().horizontalPolicy() == _SP.Policy.Expanding:
        expanding += 1
chk(expanding == 0, "좌측 정렬 - Expanding 스페이서 제거됨")

# 8) 테마 전환 직후 전 위젯 update 호출 - 예외 없이 토글 (260606-27)
try:
    mw.apply_theme("dark"); app.processEvents()
    mw.apply_theme("light"); app.processEvents()
    mw.apply_theme("dark"); app.processEvents()
    chk(True, "테마 다크↔라이트 반복 전환 무예외")
except Exception as e:
    chk(False, f"테마 전환 예외: {e}")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
mw.close()
