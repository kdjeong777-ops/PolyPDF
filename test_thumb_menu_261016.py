# -*- coding: utf-8 -*-
"""261016-1: 책갈피창·썸네일 우클릭 메뉴 이름·차례, '스크린샷 붙여넣기' (마스터 §4.7.7·§4.7.11·§4.7.13, 사용자 지시).

A. 책갈피창 파일 행 — 저장 그룹: … 평탄화해서 내보내기 · 변환해서 내보내기(하위 메뉴 없음) · 용량 줄여 내보내기 ·
   개인정보 지우고 별도 저장 / 'OCR로 글자층 생성...' 은 '책갈피 생성' 바로 아래 / 옛 이름 없음
   A5 '변환해서 내보내기...' 를 누르면 변환 창이 형식 없이(창에서 고른다)
B. 썸네일 우클릭(편집 모드, 붙일 것 없음) — 그룹과 차례가 사용자 지시대로, 붙여넣기 셋은 **끈 채로** 보인다
C. 쪽 복사 · 스크린샷 컷 · 클립보드 그림이 있으면 붙여넣기 셋이 켜진다 · 편집 모드가 아니면 보이되 꺼진다
D. '스크린샷 붙여넣기' 를 누르면 스트립의 그림 컷들이 누른 썸네일 아래 새 쪽으로(실제 처리기 — 미저장 끼운 쪽)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu
from PyQt6.QtGui import QImage, QColor

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_menu261016_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


seen, pick = [], {"t": None, "trigger": False}


def fake_exec(self, *a, **k):
    seen.append([("-", True, False) if x.isSeparator() else (x.text(), x.isEnabled(), x.menu() is not None)
                 for x in self.actions()])
    hit = next((x for x in self.actions() if pick["t"] and x.text().startswith(pick["t"])), None)
    if hit is not None and pick["trigger"]:
        hit.trigger()                      # triggered 로 잇는 항목(책갈피창 저장 그룹)
    return hit


def labels(m):
    """연이은 구분선은 하나로, 끝 구분선은 뺀다 — Qt 가 그리는 모양(separatorsCollapsible)."""
    out = []
    for t, _e, _s in m:
        if t == "-" and (not out or out[-1] == "-"):
            continue
        out.append(t)
    while out and out[-1] == "-":
        out.pop()
    return out


root = Path(tempfile.mkdtemp(prefix="menu261016_"))
_orig_exec = QMenu.exec
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", folder / "b.pdf"
    for p_ in (a, b):
        d = fitz.open()
        for i in range(4):
            d.new_page(width=595, height=842).insert_text((72, 400), "%s P%d" % (p_.stem.upper(), i + 1))
        d.set_toc([[1, "첫째", 1], [1, "둘째", 2]])
        d.save(str(p_)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    bt = mw.bookmark_tree
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)
    QMenu.exec = fake_exec

    # A — 책갈피창 파일 행
    anode = next(n for n in bt._iter_file_nodes() if Path(str(n.data(0, bt.DATA_FILE))).name == "a.pdf")
    bt._on_tree_context_menu(bt.tree.visualItemRect(anode).center()); spin(0.3)
    m = seen[-1] if seen else []
    L = labels(m)
    i_fl = L.index("평탄화해서 내보내기...") if "평탄화해서 내보내기..." in L else -1
    chk(i_fl >= 0 and L[i_fl + 1:i_fl + 5] == ["변환해서 내보내기...", "용량 줄여 내보내기...", "개인정보 지우고 별도 저장...", "-"],
        "A1 저장 그룹 끝 — 변환해서 내보내기 · 용량 줄여 내보내기 · 개인정보 지우고 별도 저장", str(L))
    conv = [x for x in m if x[0] == "변환해서 내보내기..."]
    chk(conv and conv[0][2] is False, "A2 '변환해서 내보내기...' 에 하위 메뉴가 없다", str(conv))
    i_bc = L.index("책갈피 생성") if "책갈피 생성" in L else -1
    chk(i_bc >= 0 and L[i_bc + 1] == "OCR로 글자층 생성...", "A3 'OCR로 글자층 생성...' 은 '책갈피 생성' 바로 아래", str(L))
    old = ["변환", "OCR 글자층 넣기...", "PDF 압축...", "가림(개인정보 지우기)..."]
    chk(not any(o in L for o in old), "A4 옛 이름이 남지 않는다", str([o for o in old if o in L]))
    opened = []
    mw.action_convert = lambda files=None, fmt=None, pages=None: opened.append((files, fmt))
    pick["t"], pick["trigger"] = "변환해서 내보내기", True
    bt._on_tree_context_menu(bt.tree.visualItemRect(anode).center()); spin(0.3)
    pick["t"], pick["trigger"] = None, False
    chk(opened and opened[0][0] == [str(a)] and not opened[0][1], "A5 누르면 변환 창이 형식 없이(그 파일)", str(opened))

    # B — 썸네일, 붙일 것 없음
    pt = mw.page_thumbs
    mw._thumb_clip = None
    mw.shot_strip.list.clear()
    QApplication.clipboard().clear()
    pt.list.clearSelection(); pt.list.item(1).setSelected(True)
    r1 = pt.list.visualItemRect(pt.list.item(1)).center()
    pt._on_list_menu(r1); spin(0.1)
    m = seen[-1]
    L = labels(m)
    want = ["인쇄 (1쪽)", "복사 (1쪽)", "붙여넣기", "스크린샷으로 복사 (1쪽)", "스크린샷 붙여넣기", "클립보드 붙여넣기",
            "삭제 (1쪽)", "-",
            "왼쪽 90° 회전 (1쪽)", "오른쪽 90° 회전 (1쪽)", "-",
            "크롭… (1쪽)", "크롭 해제 (1쪽)", "숨김 (1쪽)", "숨김 해제 (1쪽)", "-",
            "책갈피 추가 (p.2)", "하이퍼링크 등록… (p.2)", "-"]
    chk(L[:len(want)] == want, "B1 썸네일 우클릭 — 그룹·차례가 사용자 지시대로", str(L))
    chk(any(t.startswith("선택한 쪽 변환") for t in L[len(want):]), "B2 지시에 없던 '선택한 쪽 변환 ▸' 은 맨 아래 그룹에 남는다", str(L))
    en = {t: e for t, e, _s in m}
    chk(en.get("붙여넣기") is False and en.get("스크린샷 붙여넣기") is False and en.get("클립보드 붙여넣기") is False,
        "B3 붙일 것이 없으면 붙여넣기 셋은 **보이되 꺼져** 있다", str(en))

    # C — 붙일 것이 있으면 켜진다
    mw._thumb_clip = {"src": str(b), "pages": [0, 1]}
    shots = []
    for i, col in enumerate(("red", "green")):
        img = QImage(200, 120, QImage.Format.Format_RGB32); img.fill(QColor(col))
        sp = root / ("shot%d.png" % i); img.save(str(sp)); shots.append(str(sp))
        mw.shot_strip.add_item(str(sp), kind="image", prepend=False)
    clip = QImage(100, 80, QImage.Format.Format_RGB32); clip.fill(QColor("blue"))
    QApplication.clipboard().setImage(clip)
    pt._on_list_menu(r1); spin(0.1)
    en = {t: e for t, e, _s in seen[-1]}
    chk(en.get("붙여넣기 (2쪽) — p.2 뒤") is True and en.get("스크린샷 붙여넣기 (2쪽) — p.2 뒤") is True
        and en.get("클립보드 붙여넣기 — p.2 뒤") is True,
        "C1 쪽 복사·스크린샷 컷·클립보드 그림이 있으면 셋 다 켜진다(자리 = 누른 썸네일 뒤)", str(list(en)[:8]))
    QMenu.exec = _orig_exec
    pt.set_edit_mode(False)
    QMenu.exec = fake_exec
    pt._on_list_menu(r1); spin(0.1)
    en = {t: e for t, e, _s in seen[-1]}
    off = [t for t in en if t.startswith(("붙여넣기", "스크린샷 붙여넣기", "클립보드 붙여넣기"))]
    chk(len(off) == 3 and not any(en[t] for t in off) and all("편집모드" in t for t in off),
        "C2 편집 모드가 아니면 보이되 꺼지고 까닭을 이름에", str(off))
    pt.set_edit_mode(True)

    # D — 스크린샷 붙여넣기 실행(실제 처리기)
    before = len(pt.current_page_plan())
    pick["t"] = "스크린샷 붙여넣기"
    pt._on_list_menu(r1); spin(2.5)
    pick["t"] = None
    plan = pt.current_page_plan()
    chk(len(plan) == before + 2 and plan[0] == ("own", 0) and plan[1] == ("own", 1)
        and plan[2][0] == "ext" and plan[3][0] == "ext" and plan[4] == ("own", 2),
        "D 스트립의 그림 두 장이 누른 썸네일(2쪽) 아래 새 쪽으로", str(plan))
    QMenu.exec = _orig_exec            # 창은 닫지 않는다 — 끼운 쪽(미저장)이 있어 닫기 확인이 뜬다, os._exit 로 끝낸다
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
