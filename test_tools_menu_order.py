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


# ── 패널 툴바 '도구' 그룹 ───────────────────────────
btns = []
for a in mw._panel_toolbar.actions():
    w = mw._panel_toolbar.widgetForAction(a)
    if isinstance(w, QToolButton):
        btns.append(w.text())
# 261014-28(디자인 SOT §2.9, 사용자 지시): '변환하여 내보내기' 는 '이미지→PDF' 오른쪽, '스크린샷 PDF 저장' 단추는 없다
TOOLS = ["OCR", "단어장 생성", "책갈피 생성", "PDF병합",
         "이미지→PDF", "변환하여 내보내기", "암호화", "번역"]
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
        "PDF 병합...",
        "이미지 → PDF 변환...",
        "암호화 (암호·권한 설정)...",
        "PDF번역"]
chk(head == MENU, "② 메뉴 첫 구역이 패널과 같은 차례다(§2.9.1 예외 — 변환은 파일 메뉴)", str(head))
chk(not any(t and t.startswith("변환") for t in items), "② 도구 메뉴에 변환 항목이 없다(파일 메뉴에 있으므로)", str(items))
m_file = next(a.menu() for a in mw.menuBar().actions() if a.text().startswith("파일"))
fa = [a for a in m_file.actions() if a.text() == "변환하여 내보내기..."]
chk(len(fa) == 1 and fa[0].menu() is None, "② 파일 메뉴 '변환하여 내보내기...' — 하위 메뉴 없음",
    str([a.text() for a in m_file.actions()]))
chk(not any(a.text() == "내보내기" for a in m_file.actions()), "② 옛 '내보내기 ▸' 는 없다")
opened = []
mw.action_convert = lambda *a, **k: opened.append(k) or False
fa and fa[0].trigger()
chk(opened == [{}], "② 누르면 변환 창이 바로(형식 없이)", str(opened))

# ── 261014-28(마스터 §11.12): 키가 없으면 도구 메뉴의 API 항목은 숨긴다 ─────
from viewer.i18n import korea_only_visible
api_acts = [mw._act_law, mw._act_kcsc, mw._act_kipo, mw._act_tr_files]
mw._gate_api_dependent_ui({})
chk(not any(a.isVisible() for a in api_acts), "⑥ 키가 없으면 도구 메뉴의 법령·건설기준·특허·번역은 숨긴다",
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

# 예전 구역 제목은 사라졌고, 남은 두 항목은 한 구역으로
titles = [a.text() for a in (menu.actions() if menu else []) if a.isSeparator() and a.text()]
chk(not any("번역 (Claude)" in t for t in titles), "④ 예전 '번역 (Claude)' 구역은 없었다", str(titles))
chk("단어장·책갈피 동시 생성..." in all_items
    and "PDF 꾸밈 저장 (선·도형·글·하이퍼링크)..." in all_items,
    "④ 남은 두 항목은 그대로 있다")

# ── 단축키·권한이 잡는 손잡이이 살아 있는가 ───────────────
chk(getattr(mw, "_sc_act_merge", None) is not None, "⑤ PDF 병합 손잡이(_sc_act_merge) 유지")
chk(getattr(mw, "_act_tr_files", None) is not None, "⑤ 번역 메뉴 손잡이(_act_tr_files) 유지")
chk(getattr(mw, "_btn_merge", None) is not None and getattr(mw, "_btn_tr", None) is not None
    and getattr(mw, "_btn_img2pdf", None) is not None
    and getattr(mw, "_btn_convert", None) is not None, "⑤ 패널 버튼 손잡이 4개 유지")

print()
print("=== ALL PASS ===" if not fails else "=== FAILURE (%d) ===" % len(fails))
for f in fails:
    print(" -", f)
mw.close()
# Qt teardown 크래시(0xC0000409) 회피 — `test_panel_toolbar.py` 와 같은 `os._exit` 관례.
sys.stdout.flush()
os._exit(1 if fails else 0)
