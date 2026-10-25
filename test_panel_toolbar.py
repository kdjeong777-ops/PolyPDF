"""260606-25 패널 툴바 → 261024-1 메뉴 탭(`Ribbon`)·모음 통합 테스트 (offscreen). 디자인 SOT §2.9·§2.9.3·§2.9.4."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")   # 260628-2: cp949 콘솔에서 한글·em-dash 출력이 깨지지 않게
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QToolButton

QStandardPaths.setTestModeEnabled(True)    # 마스터 §14.7.2 — 사용자 설정 폴더를 건드리지 않는다
app = QApplication.instance() or QApplication(sys.argv)

from viewer.app import MainWindow
from viewer.widgets.ribbon import (COLLECTION, DEFAULT_COLLECTION, SEP, TAB_BAR_COLOR, Ribbon,
                                   RibbonCustomizeDialog, cmd_id)

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def mid_x(w, ref):
    return w.mapTo(ref, w.rect().topLeft()).x() + w.width() / 2


# 0) ★ 첫 레이아웃만으로 가운데(§2.9.3, 261024-1 결함) — 이벤트 루프를 돌리지 않는다.
#    종전 코드는 창이 뜬 뒤 `RECENTER_MS` 타이머로 빈 칸 폭을 쟀다 — show() 직후에는 빈 칸 0(왼쪽 정렬)이라 이 검사에 실패한다
#    (261024-1 실측: 첫 재기 전 pad=0, span 5~1187 / 창 1700).
mw0 = MainWindow()
mw0.resize(1920, 900)                       # 261025-5: 모음 기본값이 길어져(열기·인쇄) 1600 에서는 넘친다
mw0.show()                                  # processEvents 없이 곧바로 잰다
rb0 = mw0._ribbon
chk(abs(mid_x(rb0.tabs_box, mw0) - mw0.width() / 2) <= 2, "첫 레이아웃: 탭 묶음이 창 가운데",
    f"mid={mid_x(rb0.tabs_box, mw0)} win={mw0.width()}")
bs0 = rb0.row(COLLECTION).buttons()
l0 = bs0[0].mapTo(mw0, bs0[0].rect().topLeft()).x()
r0 = bs0[-1].mapTo(mw0, bs0[-1].rect().topRight()).x()
chk(abs((l0 + r0) / 2 - mw0.width() / 2) <= 3, "첫 레이아웃: 모음 줄이 창 가운데", f"{l0}~{r0}")
chk(mw0.toolbar_search.isVisible() and mw0.toolbar_search.mapTo(mw0, mw0.toolbar_search.rect().topRight()).x()
    > mw0.width() - 40, "첫 레이아웃: 검색창이 탭 줄 오른쪽 끝에 보인다")
mw0.close()

mw = MainWindow()
mw.resize(1600, 900)
mw.show()
app.processEvents()
rb = mw._ribbon

# 1) 메뉴 자리 = 탭. 메뉴 객체는 화면에 붙지 않은 QMenuBar 가 들고 있다
chk(isinstance(mw.menuWidget(), Ribbon), "창 메뉴 자리 = Ribbon")
chk(mw.menuBar() is not mw.menuWidget() and not mw.menuBar().isVisible(), "menuBar() 는 숨은 메뉴 보관 막대")
chk(mw.menuWidget() is rb, "menuBar() 를 불러도 탭이 바뀌지 않는다")
titles = [rb.tab_button(k).text() for k in rb.keys()]
chk(titles == ["모음(&C)", "파일(&F)", "즐겨찾기(&V)", "보기(&B)", "도구(&T)", "도움말(&H)"], "탭 차례·이름", str(titles))
chk(rb.current_key() == COLLECTION, "기본 탭 = 모음")
chk(mw.toolbar_search.parentWidget() is rb.right_box, "검색창은 탭 줄 오른쪽 칸")

# 2) 모음 기본값 = 종전 패널 18개(§2.9 표) — 숨은 단추(키 없음·번역)도 액션으로는 있다
row = rb.row(COLLECTION)
acts = [a for a in row.actions() if not a.isSeparator() and row.widgetForAction(a)
        and not row.widgetForAction(a).property("ribbonSpacer")]
names = [a.iconText() for a in acts]
expected = ["폴더 열기", "파일 열기", "인쇄",           # 261025-5(사용자 지시): 앞 그룹
            "1단", "2단", "텍스트", "단어장", "검색", "스크린샷", "법령·고시",
            "특허", "건설기준", "발표보기",            # 261025-1: 보기 탭 차례와 같게(디자인 SOT §2.9.5)
            "OCR", "단어장 생성", "책갈피 생성", "PDF병합",
            "이미지→PDF", "암호화", "번역", "변환"]
chk(names == expected, "모음 기본 단추 차례: §2.9 표와 일치", str(names))
chk([cmd_id(a) for a in acts] == [c for c in DEFAULT_COLLECTION if c != SEP], "모음 기본 id = DEFAULT_COLLECTION")
groups = row.groups()
chk(len(groups) == 3, "모음 그룹 셋(열기·인쇄·보기·도구)", str(len(groups)))
chk("스크린샷 PDF 저장" not in names and "전체화면" not in names and "책갈피·단어장 동시 생성" not in names,
    "옛 단추 없음(스크린샷 PDF 저장·전체화면·동시 생성)")
vis = [b.text() for b in row.buttons()]
chk("법령·고시" not in vis and "번역" not in vis, "키 없는 법령·번역 단추는 숨김(§11.12 — 액션 가시성)", str(vis))
chk(acts[0] is mw._cmds["file.open_folder"] and acts[3] is mw._view_acts["single"], "모음 단추 = 메뉴 액션과 같은 객체")

# 3) 내부 상태 QAction 유지
chk(hasattr(mw, "act_toggle_search") and hasattr(mw, "act_toggle_shot"), "act_toggle_search/shot 내부 유지")

# 4) 탭 전환 — 고른 탭만 체크, 세부 줄 바뀜, 밑줄 바 색
rb.select("tools")
chk(rb.tab_button("tools").isChecked() and not rb.tab_button(COLLECTION).isChecked(), "도구 탭 고름")
chk(rb.stack.currentWidget() is rb.row("tools"), "세부 줄 = 도구")
tnames = [a.iconText() for a in rb.row("tools").actions() if not a.isSeparator() and cmd_id(a)]
chk(tnames[:3] == ["OCR", "단어장 생성", "책갈피 생성"], "도구 줄 앞부분 = 모음 도구 차례", str(tnames))
sub = [rb.row("tools").widgetForAction(a) for a in rb.row("tools").actions() if a.menu() is not None]
chk(sub and all(isinstance(w, QToolButton) and w.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
                for w in sub), "하위 메뉴는 ▾ 단추(누르면 펼침)")
chk(TAB_BAR_COLOR in rb.tab_row.styleSheet() and "checked" in rb.tab_row.styleSheet(), "고른 탭 밑줄 바 스타일")
fav = rb.row("fav")
chk(len([a for a in fav.actions() if not a.isSeparator() and cmd_id(a) == ""]) >= 1, "즐겨찾기 줄 = 즐겨찾기 메뉴 항목")

# 5) Alt+글자 → 그 탭(드롭다운 없음)
mw.activateWindow(); app.processEvents()
rb.select(COLLECTION)
QTest.keyClick(mw, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
QTest.qWait(300)                            # 니모닉은 animateClick — 잠시 뒤 눌린다
chk(rb.current_key() == "file", "Alt+F → 파일 탭", rb.current_key())
QTest.keyClick(mw, Qt.Key.Key_T, Qt.KeyboardModifier.AltModifier)
QTest.qWait(300)
chk(rb.current_key() == "tools", "Alt+T → 도구 탭", rb.current_key())

# 6) 메뉴 막대를 뗐어도 메뉴 항목의 단축키가 산다(파일 줄이 안 보일 때도) — Ctrl+R 새로고침
rb.select(COLLECTION); app.processEvents()
hits = []
mw._sc_act_refresh.triggered.connect(lambda *_: hits.append(1))
QTest.keyClick(mw, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier); app.processEvents()
chk(hits == [1], "파일 탭이 안 보여도 Ctrl+R(메뉴 항목 키) 동작", str(hits))
chk(mw._sc_act_save in mw.actions(), "저장 액션이 창에 붙어 있다(Ctrl+S)")

# 7) 모음 사용자 지정 — 설정 값대로, 모르는 id 는 건너뜀, 비면 기본값
mw._prefs["ribbon_collection"] = ["file.save", SEP, "view.text", "bogus.id"]
mw._apply_collection()
ids = [cmd_id(a) or ("|" if a.isSeparator() else None) for a in row.actions()]
ids = [i for i in ids if i]
chk(ids == ["file.save", "|", "view.text"], "사용자 모음 차례(모르는 id 건너뜀)", str(ids))
mw._prefs["ribbon_collection"] = []
mw._apply_collection()
chk([cmd_id(a) for a in row.actions() if cmd_id(a)] == [c for c in DEFAULT_COLLECTION if c != SEP], "빈 값 = 기본값")

# 8) 사용자 지정 창
cat, labels = mw.ribbon_catalog()
chk([t for t, _ in cat] == ["파일(&F)", "즐겨찾기(&V)", "보기(&B)", "도구(&T)", "도움말(&H)"], "명령 고르기 = 탭별(261025-1 즐겨찾기 포함)", str([t for t, _ in cat]))
dlg = RibbonCustomizeDialog(cat, ["view.single"], labels, mw)
chk(dlg.result_ids() == ["view.single"], "창: 지금 모음을 보인다")
top = dlg.tree.topLevelItem(0)                       # 파일
dlg.list.setCurrentRow(0)
dlg.tree.setCurrentItem(top.child(0)); dlg._add()    # 새 창
dlg._add()                                           # 같은 명령은 한 번만
dlg._add_sep()
chk(dlg.result_ids() == ["view.single", "file.new_window", SEP], "창: 추가·중복 막음·구분선", str(dlg.result_ids()))
dlg.list.setCurrentRow(1); dlg._move(-1)
chk(dlg.result_ids()[:2] == ["file.new_window", "view.single"], "창: 위로")
dlg.list.setCurrentRow(2); dlg._remove()
chk(dlg.result_ids() == ["file.new_window", "view.single"], "창: 제거")
dlg.btn_default.click()
chk(dlg.result_ids() == list(DEFAULT_COLLECTION), "창: 기본값으로")
dlg.close()

# 9) 환경설정 — 세부 줄 보이기 · 모음 메뉴 편집 단추 · 결과에 ribbon_collection
from viewer.widgets.settings_dialog import SettingsDialog
mw._prefs["ribbon_collection"] = ["view.text"]
sd = SettingsDialog(mw._prefs, mw, host=mw)
chk(sd.btn_edit_collection.isEnabled(), "설정: 모음 메뉴 편집 단추")
chk(sd.result_prefs().get("ribbon_collection") == ["view.text"], "설정: 모음 값 보존")
sd.close()
mw._prefs["ribbon_collection"] = []
mw._apply_collection()
rb.set_rows_visible(False)
chk(not rb.stack.isVisible(), "세부 줄 숨김")
rb.select("view")
chk(rb.stack.isVisible(), "숨긴 채 탭을 누르면 다시 보인다")
rb.select(COLLECTION)

# 10) 뷰어 모드 동작(종전)
mw._vm_single()
chk(not mw.act_split.isChecked() and not mw.act_toggle_search.isChecked() and not mw.act_toggle_shot.isChecked(), "1단")
mw._vm_split()
chk(mw.act_split.isChecked(), "2단: split on")
mw._vm_search()
chk(not mw.act_split.isChecked() and mw.act_toggle_search.isChecked()
    and mw.search_tabs.currentWidget() is mw.search_area, "검색: 검색 탭")
mw._vm_study()
chk(mw.search_tabs.currentWidget() is mw.study_panel, "단어장: 단어장 탭 선택")
mw._vm_shot()
chk(not mw.act_toggle_search.isChecked() and mw.act_toggle_shot.isChecked(), "스크린샷: shot on")

# 11) 세부 줄 스타일(260606-26) · 테마
mw._style_panel_toolbar(True)
chk("#3e3e42" in row.styleSheet() and "#5a5a60" in row.styleSheet() and row.dark, "다크 스타일 적용(일반·드롭다운 단추 색, 261025-5)")
mw._style_panel_toolbar(False)
chk("#fafafa" in row.styleSheet() and "#e6e6e6" in row.styleSheet() and "#e4e4e4" in row.styleSheet() and not row.dark,
    "라이트 스타일 적용(일반 옅게·드롭다운 진하게·리본 줄 회색, 261025-5)")

# 12) 썸네일 번호 하단 배치 (260606-26)
from viewer.widgets.thumbs_list import PageThumbs
pt = PageThumbs()
chk(pt.NUM_BAND > 0, "썸네일 번호 띠 높이>0")
chk(pt.list.iconSize().height() == pt._thumb_size.height() + pt.NUM_BAND, "아이콘 높이에 번호 띠 포함")

# 13) 테마 전환 반복 무예외 (260606-27)
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
# 260628-2: 종료코드 반환 + Qt teardown 크래시(0xC0000409) 회피 — `test_side_panels.py` 와 같은 `os._exit` 관례.
sys.stdout.flush()
os._exit(0 if not fails else 1)
