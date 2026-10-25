"""260911-1: 도구 차례 — 패널과 메뉴가 같은가 (offscreen).

기준은 디자인 SOT `화면 디자인 작업 계획서.md` §2.9 표 11~18 과 §2.9.1 이다.
사용자 지시: OCR · 단어장 생성 · 책갈피 생성 · PDF병합 · 이미지→PDF ·
스크린샷 PDF 저장 · 암호화 — 그리고 목록에 없던 `번역` 은 맨 뒤.
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication, QToolButton
from viewer.app import MainWindow

app = QApplication.instance() or QApplication(sys.argv)
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
# 261014-28: '스크린샷 PDF 저장' 단추는 없다. 261016-4(디자인 SOT §2.9, 사용자 지시): '변환해서 내보내기' 는 '암호화' 오른쪽
TOOLS = ["OCR", "단어장 생성", "책갈피 생성", "PDF병합",
         "이미지→PDF", "암호화", "번역", "변환해서 내보내기"]
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
        items.append(None)          # addSection 은 구분선 + 제목으로 들어온다
    else:
        items.append(a.text())
# 첫 구분선 다음부터 다음 구분선 앞까지 = 첫 구역
first = items.index(None)
rest = items[first + 1:]
head = rest[:rest.index(None)] if None in rest else rest
MENU = ["OCR 로 읽기 (쪽 범위·언어·워터마크)...",
        "단어장 생성 (OCR·어휘)...",
        "책갈피 자동 생성...",
        "단어장·책갈피 동시 생성...",          # 261016-3(§2.9.1 예외 둘째): 파생 항목은 원 항목 바로 아래
        "PDF 병합...",
        "다단 생성...",                       # 261021-3(§2.9.1 예외 둘째): 파일 하나 다단 — 병합 아래, 패널 단추 없음
        "이미지 → PDF 변환...",
        "암호화 (암호·권한 설정)...",
        "PDF번역",
        "전자서명", "태그 자동 부여", "인덱스 재구축"]   # 261016-3: 하위 메뉴 둘 + 인덱스 재구축, 도구 구역 안에 이어서
chk(head == MENU, "② 메뉴 첫 구역이 패널과 같은 차례다(§2.9.1 예외 — 변환은 파일 메뉴, 동시 생성은 책갈피 아래)", str(head))
subs = {a.text(): [x.text() for x in a.menu().actions()] for a in menu.actions() if a.menu()}
chk(subs.get("전자서명", [])[:1] == ["서명..."] and len(subs.get("전자서명", [])) == 7
    and subs.get("태그 자동 부여", [])[:1] == ["태그 다시 계산"] and len(subs.get("사전 및 용어집 관리", [])) == 10,   # 261019-5: '사용자 뜻 편집' 더함
    "② 전자서명·태그 자동 부여·사전 및 용어집 관리는 하위 메뉴(▸)", str(subs))
sec_titles = [a.text() for a in menu.actions() if a.isSeparator() and a.text()]
chk(sec_titles == ["🧰 도구", "⚙️ 프로그램 환경설정", "💻 시스템 연동 및 설치"], "② 구역은 셋(검색 및 데이터 구축·그 밖의·전자서명 구역 없음)", str(sec_titles))
env = items[items.index("환경설정..."):] if "환경설정..." in items else []
chk(env[:3] == ["환경설정...", "단축키 설정...", "사전 및 용어집 관리"], "② 환경설정 · 단축키 설정 · 사전 및 용어집 관리 ▸", str(env[:4]))
# 261017-19(디자인 SOT §2.9.1): 마지막 구역 '💻 시스템 연동 및 설치' 의 항목 차례(가상 프린터 SOT §4.6)
_sys_i = next((i for i, a in enumerate(menu.actions()) if a.isSeparator() and a.text() == "💻 시스템 연동 및 설치"), None)
sys_items = [a.text() for a in menu.actions()[_sys_i + 1:] if not a.isSeparator()] if _sys_i is not None else []
# 261025-1(디자인 SOT §2.9.1, 사용자 지시·결정): 세 항목은 '등록·설치 ▸' 하나로 — 명령 id 는 그대로
_inst = next((a for a in menu.actions()[_sys_i + 1:] if a.menu() is not None), None) if _sys_i is not None else None
inst_items = [a.text() for a in _inst.menu().actions()] if _inst is not None else []
chk(sys_items == ["등록·설치"] and inst_items == ["기본 PDF 앱 등록…", "구성요소 설치…", "가상 프린터 설치·제거…"],
    "② '시스템 연동 및 설치' 구역 — 등록·설치 ▸(PDF 앱 등록 · 구성요소 설치 · 가상 프린터)", str((sys_items, inst_items)))
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
chk(not any(t and t.startswith("변환") for t in items), "② 도구 메뉴에 변환 항목이 없다(파일 메뉴에 있으므로)", str(items))
m_file = next(a.menu() for a in mw.menuBar().actions() if a.text().startswith("파일"))
fa = [a for a in m_file.actions() if a.text() == "변환해서 내보내기..."]
chk(len(fa) == 1 and fa[0].menu() is None, "② 파일 메뉴 '변환해서 내보내기...' — 하위 메뉴 없음",
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
