"""260911-1: 도구 차례 — 패널과 메뉴가 같은가 (offscreen).

기준은 디자인 SOT `화면 디자인 작업 계획서.md` §2.9 표와 §2.9.1 이다.
261031-16(사용자 지시·결정): 도구 메뉴는 묶음 다섯 — 생성 | PDF | 변환·번역 | 환경설정·사전 관리 | 등록·설치,
모음 기본값의 도구 묶음도 같은 차례.
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication, QToolButton
from viewer.app import MainWindow

app = QApplication.instance() or QApplication(sys.argv)
# 261025-7: 사용자 실제 설정 폴더(색인·settings.json)를 쓰지 않는다 — 마스터 §14.7.2 의 3
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_tools_menu_order_%d" % os.getpid())
mw = MainWindow()
mw.show()
app.processEvents()

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


# ── '모음' 탭 기본값의 도구 묶음(종전 패널 '도구' 그룹, 261024-1 디자인 SOT §2.9) ─────
from viewer.widgets.ribbon import COLLECTION, cmd_id
_row = mw._ribbon.row(COLLECTION)
btns = [a.iconText() for a in _row.actions() if cmd_id(a)]
# 261014-28: '스크린샷 PDF 저장' 단추는 없다. 261031-16(디자인 SOT §2.9.1): 도구 탭 차례와 같게 — 이미지→PDF 가 병합 앞, 변환 다음 번역
TOOLS = ["OCR", "단어장 생성", "책갈피 생성", "이미지→PDF",
         "PDF병합", "암호화", "변환", "번역"]            # 261025-5: '변환해서 내보내기' → '변환'
N = len(TOOLS)
chk(btns[-N:] == TOOLS, "① 패널 '도구' %d개가 지시한 차례다" % N, str(btns[-N:]))
chk(btns.index("OCR") == len(btns) - N, "① 도구는 보기 뒤에 모여 있다", str(btns))

# ── 도구(&T) 메뉴 첫 구역 ─────────────────────────
menu = None
for act in mw.menuBar().actions():
    if act.text().startswith("도구"):
        menu = act.menu()
chk(menu is not None, "② '도구(&T)' 메뉴가 있다")

items = []
for a in (menu.actions() if menu else []):
    if a.isSeparator():
        items.append(None)
    elif not a.property("ribbonMark"):     # 바깥 글자 표시(RibbonIconMark)는 메뉴 항목이 아니다
        items.append(a.text())
ids = []
for a in (menu.actions() if menu else []):
    if a.isSeparator():
        ids.append(None)
    elif not a.property("ribbonMark"):
        ids.append(cmd_id(a) or a.text())
groups, cur = [], []
for t in ids:
    if t is None:
        groups.append(cur); cur = []
    else:
        cur.append(t)
groups.append(cur)
groups = [g for g in groups if g]
# 261031-16(디자인 SOT §2.9.1, 사용자 지시·결정): 묶음 다섯 — 생성 | PDF | 변환·번역 | 환경설정·사전 관리 | 등록·설치
# 마스터 §14.7.2 의 19: 메뉴 항목은 이름이 아니라 명령 id 목록으로 견준다
GROUPS = [["tools.ocr", "tools.build_study", "tools.bookmarker", "tools.study_and_bookmarks", "tools.autotag", "tools.reindex"],
          ["tools.img2pdf", "tools.merge", "tools.nup", "tools.encrypt", "tools.sign"],
          ["file.export", "tools.translate"],
          ["tools.settings", "tools.dict"],
          ["tools.install"]]
chk(groups == GROUPS, "② 도구 메뉴 묶음 다섯·차례(261031-16)", str(groups))
marks = [a.text() or a.toolTip() for a in menu.actions() if a.property("ribbonMark")]
_row_t = mw._ribbon.row("tools")
mark_txt = [w.text() for w in (_row_t.widgetForAction(a) for a in _row_t.actions() if a.property("ribbonMark")) if w is not None]
chk(mark_txt == ["생성", "PDF"], "② 생성·PDF 묶음은 바깥 왼쪽 글자", str(mark_txt))
short = {cmd_id(a): _row_t.widgetForAction(a).text() for a in _row_t.actions() if cmd_id(a) and _row_t.widgetForAction(a)}
chk(short.get("tools.build_study") == "단어장" and short.get("tools.bookmarker") == "책갈피"
    and short.get("tools.study_and_bookmarks") == "단어장·책갈피" and short.get("tools.img2pdf") == "이미지"
    and short.get("tools.merge") == "병합" and short.get("tools.nup") == "다단",
    "② 도구 탭 단추는 짧은 이름(ribbonShort)", str(short))
chk(mw._cmds["tools.build_study"].iconText() == "단어장 생성" and mw._cmds["tools.merge"].iconText() == "PDF병합",
    "② 모음 단추 이름은 그대로(짧은 이름은 도구 탭에서만)")
subs = {a.text(): [x.text() for x in a.menu().actions()] for a in menu.actions() if a.menu()}
names = {cmd_id(a): a.text() for a in menu.actions() if cmd_id(a)}
chk(names.get("tools.autotag") == "태그" and names.get("tools.reindex") == "인덱스" and names.get("tools.dict") == "사전 관리",
    "② 이름 바꿈 — 태그 · 인덱스 · 사전 관리(261031-16, RENAMED)", str(names))
# 261031-1: 개수(종전 7) 대신 항목 그대로 — '서명 그림...' 을 빼고 '디지털 ID...' → '디지털 ID 관리...'(보안 SOT §3). 개수만 보면
#   항목이 바뀐 까닭을 실패 글이 말하지 못하고, 이름 바꿈 검사(test_sot_crossref RENAMED I3)도 숫자는 못 본다
SIGN_SUB = ["서명...", "그림만 넣기...", "서명 확정...", "서명 편집", "빈 서명 칸 만들기...", "디지털 ID 관리..."]
chk(subs.get("전자서명", []) == SIGN_SUB
    and subs.get("태그", [])[:1] == ["태그 다시 계산"] and len(subs.get("사전 관리", [])) == 10,   # 261019-5: '사용자 뜻 편집' 더함
    "② 전자서명·태그·사전 관리는 하위 메뉴(▸)", str(subs))
sec_titles = [a.text() for a in menu.actions() if a.isSeparator() and a.text()]
chk(sec_titles == [], "② 구역 제목은 없다(261031-16 — 구분선·바깥 글자)", str(sec_titles))
chk("단축키 설정..." not in items, "② 단축키 설정은 환경설정 '스타일' 묶음으로(261025-6 보완)")
# 261025-1(디자인 SOT §2.9.1, 사용자 지시·결정): 세 항목은 '등록·설치 ▸' 하나로 — 명령 id 는 그대로
_inst = next((a for a in menu.actions() if a.menu() is not None and a.text() == "등록·설치"), None)
inst_items = [a.text() for a in _inst.menu().actions()] if _inst is not None else []
chk(inst_items == ["기본 PDF 앱 등록…", "구성요소 설치…", "가상 프린터 설치·제거…"],
    "② 등록·설치 ▸(PDF 앱 등록 · 구성요소 설치 · 가상 프린터)", str(inst_items))
from viewer.widgets.ribbon import cmd_id as _cid
chk([_cid(a) for a in (_inst.menu().actions() if _inst else [])] == ["tools.pdf_handler", "tools.components", "tools.vprinter"]
    and "tools.vprinter" in dict(mw.ribbon_catalog()[0])["도구(&T)"],
    "② 세 명령 id 는 그대로 — 모음 편집 목록에도 남는다(§2.9.4)")
chk(not any(t and ("기본값으로 저장" in t or t.startswith("설정 초기화")) for t in items),
    "② 기본값 저장·설정 초기화는 도구 메뉴에서 뺐다(환경설정 창 맨 아래)")
from viewer.widgets.settings_dialog import SettingsDialog
_dlg = SettingsDialog(mw._prefs, mw, host=mw)
_dlg.show(); app.processEvents()                 # 배치가 잡혀야 위치를 잴 수 있다
chk(_dlg.btn_save_default.text() == "현재 설정을 기본값으로 저장(배포용)…"
    and _dlg.btn_reset_default.text() == "설정 초기화(기본값으로 되돌리기)…"
    and _dlg.btn_save_default.mapTo(_dlg, _dlg.btn_save_default.rect().topLeft()).y()
    < _dlg.btn_reset_default.mapTo(_dlg, _dlg.btn_reset_default.rect().topLeft()).y(),
    "② 환경설정 창 맨 아래 — 기본값 저장(배포용) 아래 설정 초기화")
_dlg.close(); _dlg.deleteLater()
m_file = next(a.menu() for a in mw.menuBar().actions() if a.text().startswith("파일"))
fa = [a for a in m_file.actions() if a.text() == "변환..."]
chk(fa and [a for a in menu.actions() if a.text() == "변환..."] == fa,
    "② '변환...' 은 파일·도구 메뉴에 같은 액션(261025-5 사용자 지시)", str(items))
chk(len(fa) == 1 and fa[0].menu() is None, "② 파일 메뉴 '변환...' — 하위 메뉴 없음",
    str([a.text() for a in m_file.actions()]))
chk(not any(a.text() == "내보내기" for a in m_file.actions()), "② 옛 '내보내기 ▸' 는 없다")
opened = []
mw.action_convert = lambda *a, **k: opened.append(k) or False
fa and fa[0].trigger()
chk(opened == [{}], "② 누르면 변환 창이 바로(형식 없이)", str(opened))

# ── 261014-28(마스터 §11.12): 키가 없으면 도구 메뉴의 API 항목은 숨긴다 ─────
from viewer.i18n import korea_only_visible
chk(mw._act_law is None and mw._act_kcsc is None and mw._act_kipo is None, "⑥ 도구 메뉴에 법령·건설기준·특허 없음(보기 메뉴에만, 261016-3)")
api_acts = [mw._act_tr_files]
mw._gate_api_dependent_ui({})
chk(not any(a.isVisible() for a in api_acts), "⑥ 키가 없으면 도구 메뉴의 번역은 숨긴다",
    str([(a.text(), a.isVisible()) for a in api_acts]))
mw._gate_api_dependent_ui({"law_oc": "x", "kcsc_key": "x", "kipo_signkey": "x", "anthropic_api_key": "x"})
chk(all(a.isVisible() and a.isEnabled() for a in api_acts) == korea_only_visible(), "⑥ 키를 넣으면 보이고 켜진다")
mw._gate_api_dependent_ui({})
va = [mw._view_acts[k] for k in ("law", "kcsc", "kipo")]
chk(not any(a.isVisible() for a in va), "⑥ 보기 메뉴의 법령·건설기준·특허도 키가 없으면 숨긴다")
mw._gate_api_dependent_ui({"law_oc": "x", "kcsc_key": "x", "kipo_signkey": "x"})
chk(all(a.isVisible() and a.isEnabled() for a in va) == korea_only_visible(), "⑥ 키를 넣으면 보기 메뉴 항목도 보인다")

# ── 짝이 실제로 같은 일을 하는가 ────────────────────
all_items = [t for t in items if t]
chk("스크린샷 PDF 저장..." not in items, "③ 도구 메뉴에 '스크린샷 PDF 저장...' 이 없다(261014-28 — 스크린샷 창·Ctrl+S)")
chk(callable(getattr(mw, "action_save_screenshot_pdf", None)), "③ Ctrl+S 의 스크린샷 PDF 저장은 남는다")
for name in ("OCR 로 읽기 (쪽 범위·언어·워터마크)...",
             "암호화 (암호·권한 설정)..."):
    chk(name in all_items, "③ 예전 메뉴에는 없던 항목이 들어왔다: %s" % name)

# 261016-3: 'PDF 꾸밈 저장' 은 뺐다(파일 메뉴 '평탄화해서 내보내기...' 와 같은 함수)
chk("PDF 꾸밈 저장 (선·도형·글·하이퍼링크)..." not in all_items, "④ 'PDF 꾸밈 저장' 은 도구 메뉴에 없다")
chk(any(a.text() == "평탄화해서 내보내기..." for a in m_file.actions()), "④ 같은 기능은 파일 메뉴 '평탄화해서 내보내기...'")

# ── 단축키·권한이 잡는 손잡이이 살아 있는가 ───────────────
chk(getattr(mw, "_sc_act_merge", None) is not None, "⑤ PDF 병합 손잡이(_sc_act_merge) 유지")
chk(getattr(mw, "_act_tr_files", None) is not None, "⑤ 번역 메뉴 손잡이(_act_tr_files) 유지")
# 261024-1(디자인 SOT §2.9): 모음 단추는 메뉴 액션 그 자체 — 따로 둔 패널 단추 손잡이는 없앴다
_ids = {cmd_id(a): a for a in _row.actions() if cmd_id(a)}
chk(_ids.get("tools.merge") is mw._sc_act_merge and _ids.get("tools.translate") is mw._act_tr_files
    and _ids.get("file.export") is mw.act_export, "⑤ 모음 단추 = 메뉴 액션(병합·번역·변환)")
# 도구 탭 세부 줄 = 도구 메뉴 차례 그대로(같은 액션)
_trow = mw._ribbon.row("tools")
chk([a for a in _trow.actions() if cmd_id(a)] == [a for a in menu.actions() if cmd_id(a)],
    "⑦ 도구 탭 세부 줄 = 도구 메뉴 항목·차례")

print()
print("=== ALL PASS ===" if not fails else "=== FAILURE (%d) ===" % len(fails))
for f in fails:
    print(" -", f)
mw.close()
# Qt teardown 크래시(0xC0000409) 회피 — `test_panel_toolbar.py` 와 같은 `os._exit` 관례.
sys.stdout.flush()
os._exit(1 if fails else 0)
