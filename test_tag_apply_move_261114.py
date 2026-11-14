# -*- coding: utf-8 -*-
"""'해시태그 수정' 두 목록 이동식 — 붙일 수 있는 태그 ↔ 붙은 태그 (태그 SOT §8.7·§5.3.2, 디자인 SOT, 261114-2 덧붙임).

사용자 지시: "사람이 고치기 어려운게 기존 '설명서'라는 등록된 명칭이 보이지 않아. 그리고, 해제하고, 등록하는 과정의 ux가 편리하지 않아.
좌측은 등록가능한거, 우측은 등록된거 와 같은 스타일이 좋은데". 사용자 결정: 가로 두 목록·종류+모든 태그+후보·붙은 쪽에 ◐ n/m·썸네일 위 콤보.
실제 MainWindow·TagApplyDialog 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 배치 — [붙일 수 있는 태그] [→ ←] [붙은 태그] | 썸네일, 문서 종류 7개·속성 6개는 늘 보이고(✓·◐ — 261114-2 덧붙임 2) 기존 태그는 고른 파일에 있으면 오른쪽에만
H. 속성 붙이기 — 날짜는 파일마다 그 파일 날짜, 한글·영어·스캔문서·텍스트문서는 짝 중 하나만
B. 붙은 태그 줄 — `n/m`·`◐ n/m`·자동으로만이면 `·#`
C. 문서 종류 '설명서' 를 [→] — PDF 종류가 설명서 하나로(자동 발표자료는 거절)
D. 기존 태그 두 번 누르기 = 붙이기, 붙은 줄 두 번 누르기 = 떼기, 끌어 놓기도
E. ◐ 줄을 [→] 하면 나머지 파일에도, [←] 는 모두에서 떼고 자동 태그는 거절
F. 찾기 칸에 없는 이름 → [추가] 로 곧바로 붙인다
G. 썸네일 위 태그 거르기 콤보(있음·없음)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPointF, QMimeData
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QDropEvent
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_move_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "해시태그 수정 두 목록", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def pump(sec=0.15):
    t = time.monotonic()
    while time.monotonic() - t < sec:
        app.processEvents(); time.sleep(0.01)


def rows(lw):
    return {lw.item(i).data(Qt.ItemDataRole.UserRole): lw.item(i).text() for i in range(lw.count()) if lw.item(i).data(Qt.ItemDataRole.UserRole)}


def pick(lw, tag):
    lw.clearSelection()
    for i in range(lw.count()):
        if lw.item(i).data(Qt.ItemDataRole.UserRole) == tag:
            lw.item(i).setSelected(True)
            lw.setCurrentItem(lw.item(i))
            return lw.item(i)
    return None


def dbl(lw, it):
    r = lw.visualItemRect(it)
    QTest.mouseClick(lw.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
    QTest.mouseDClick(lw.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
    pump()


class _Drop(QDropEvent):
    def __init__(self, src, pos):
        super().__init__(QPointF(pos), Qt.DropAction.CopyAction, QMimeData(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self._src = src

    def source(self):
        return self._src


tmp = tempfile.mkdtemp(prefix="polypdf_tagmove_")
try:
    P = []
    for n in ("보조배터리.pdf", "b.pdf", "c.pdf"):
        p = os.path.join(tmp, n); d = fitz.open(); d.new_page(); d.save(p); d.close(); P.append(p)
    from viewer.app import MainWindow
    from viewer.widgets.tag_apply_dialog import TagApplyDialog
    from viewer.auto_tag import FORMAT_VOCAB
    mw = MainWindow(); mw._skip_save_on_close = True; mw.show(); pump(0.3)
    st = mw.bookmark_tree._tags
    st.set_auto(P[0], ["발표자료", "스캔문서"]); st.set(P[1], ["균열"]); st.set_auto(P[1], ["발표자료"]); st.set(P[2], ["포장"])
    dlg = TagApplyDialog(st, P, [P[0], P[1]], keep=mw.__dict__.setdefault("_thread_keep", []))
    dlg.resize(1300, 700); dlg.show(); pump(0.3)
    la, lt = dlg.lst_avail, dlg.lst_tags

    # A
    g = lambda w: w.mapTo(dlg, w.rect().topLeft()).x()            # noqa: E731
    chk(g(la) < g(dlg.btn_to) < g(lt) < g(dlg.lst_files) and dlg.btn_from.y() > dlg.btn_to.y(), "A 배치 [붙일 수 있는] [→ ←] [붙은] | 썸네일",
        str([g(la), g(dlg.btn_to), g(lt), g(dlg.lst_files)]))
    heads = [la.item(i).text() for i in range(la.count()) if not la.item(i).data(Qt.ItemDataRole.UserRole)]
    av = rows(la)
    from viewer.auto_tag import PDF_ATTR_ITEMS
    chk(heads[:3] == ["문서 종류", "자동 해시태그 속성", "기존 태그"] and all(f in av for f in FORMAT_VOCAB) and all(a in av for a in PDF_ATTR_ITEMS),
        "A 문서 종류 7개·자동 해시태그 속성 6개는 늘 보인다(261114-2 덧붙임 2)·기존 태그 묶음", str(heads) + str(list(av)))
    chk(av.get("발표자료", "").endswith("✓") and av.get("스캔문서", "").endswith("◐") and not av.get("제품설명서", "").endswith(("✓", "◐")),
        "A 13 항목 — 고른 파일 모두에 있으면 ✓, 일부만이면 ◐", str({k: av.get(k) for k in ("발표자료", "스캔문서", "제품설명서")}))
    chk("포장" in av and "균열" not in av, "A 기존 태그는 고른 파일에 있으면 오른쪽에만, 다른 파일의 태그는 왼쪽에", str(list(av)))

    # B
    at = rows(lt)
    chk(at.get("발표자료", "").endswith("2/2") and at.get("발표자료", "").startswith("·#") and "◐ 1/2" in at.get("균열", "")
        and at.get("균열", "").startswith("#") and "◐ 1/2" in at.get("스캔문서", ""), "B 붙은 태그 줄 n/m·◐·'·#'", str(at))
    chk("고른 파일 2개" in dlg.g_attached.title(), "B 머리 '붙은 태그 — 고른 파일 2개'", dlg.g_attached.title())

    # C
    pick(la, "제품설명서"); pump()
    QTest.mouseClick(dlg.btn_to, Qt.MouseButton.LeftButton); pump()
    chk(st.get_manual(P[0]) == ["제품설명서"] and "발표자료" in st.get_rejected(P[0]) and "제품설명서" in st.get_manual(P[1])
        and "발표자료" not in st.get(P[1]), "C 문서 종류 [→] — 종류가 설명서 하나로", f"{st.record(P[0])} {st.record(P[1])}")
    chk("제품설명서" in rows(lt) and rows(la).get("제품설명서", "").endswith("✓"), "C 옮긴 뒤 목록 — 설명서는 오른쪽에, 왼쪽 줄은 ✓")

    # D
    it = pick(la, "포장")
    dbl(la, it)
    chk("포장" in st.get_manual(P[0]) and "포장" in st.get_manual(P[1]), "D 두 번 누르기 = 붙이기", f"{st.get(P[0])} {st.get(P[1])}")
    it = pick(lt, "포장")
    dbl(lt, it)
    chk("포장" not in st.get(P[0]) and "포장" not in st.get(P[1]) and st.get_manual(P[2]) == ["포장"], "D 붙은 줄 두 번 누르기 = 떼기(고른 파일만)")
    pick(la, "포장"); pump()
    lt.dropEvent(_Drop(la, lt.viewport().rect().center())); pump()
    chk("포장" in st.get_manual(P[0]) and "포장" in st.get_manual(P[1]), "D 왼쪽 줄을 오른쪽으로 끌어 놓기 = 붙이기")
    pick(lt, "포장"); pump()
    la.dropEvent(_Drop(lt, la.viewport().rect().center())); pump()
    chk("포장" not in st.get(P[0]), "D 오른쪽 줄을 왼쪽으로 끌어 놓기 = 떼기")

    # E
    pick(lt, "균열"); pump()
    chk(dlg.btn_to.isEnabled(), "E ◐ 줄을 고르면 [→] 켜짐")
    QTest.mouseClick(dlg.btn_to, Qt.MouseButton.LeftButton); pump()
    chk("균열" in st.get_manual(P[0]) and rows(lt).get("균열", "").endswith("2/2"), "E ◐ 줄 [→] — 나머지 파일에도", str(rows(lt).get("균열")))
    pick(lt, "스캔문서"); pump()
    QTest.mouseClick(dlg.btn_from, Qt.MouseButton.LeftButton); pump()
    chk("스캔문서" not in st.get(P[0]) and "스캔문서" in st.get_rejected(P[0]), "E [←] — 자동 태그는 거절")
    dlg.undo(); pump()
    chk("스캔문서" in st.get_auto(P[0]), "E 되돌리기")

    # F
    QTest.keyClicks(dlg.ed_find, "newtag"); pump()
    chk(dlg.btn_find_add.isEnabled(), "F 없는 이름 — [추가] 켜짐")
    QTest.mouseClick(dlg.btn_find_add, Qt.MouseButton.LeftButton); pump()
    chk("newtag" in st.get_manual(P[0]) and "newtag" in st.get_manual(P[1]) and "newtag" not in st.get(P[2]), "F [추가] 로 곧바로 고른 파일에 붙인다")

    # H 속성 붙이기(261114-2 덧붙임 2)
    dlg.cmb_tagf.setCurrentIndex(0); dlg.cmb_has.setCurrentIndex(0); pump()
    dlg.lst_files.clearSelection()
    for k in range(dlg.lst_files.count()):
        dlg.lst_files.item(k).setSelected(dlg.lst_files.item(k).data(Qt.ItemDataRole.UserRole) in (P[0], P[1]))
    pump()
    want = {p: dlg._file_date(p) for p in (P[0], P[1])}
    pick(la, "날짜"); pump(); QTest.mouseClick(dlg.btn_to, Qt.MouseButton.LeftButton); pump()
    chk(all(want[p] and want[p] in st.get_manual(p) for p in (P[0], P[1])), "H 날짜 — 고른 파일마다 그 파일 날짜(기간 거르기와 같은 날짜)", str(want))
    pick(la, "한글"); pump(); QTest.mouseClick(dlg.btn_to, Qt.MouseButton.LeftButton); pump()
    pick(la, "영어"); pump(); QTest.mouseClick(dlg.btn_to, Qt.MouseButton.LeftButton); pump()
    chk("영어" in st.get_manual(P[0]) and "한글" not in st.get(P[0]), "H 한글·영어는 짝 중 하나만", str(st.get(P[0])))
    pick(la, "텍스트문서"); pump(); QTest.mouseClick(dlg.btn_to, Qt.MouseButton.LeftButton); pump()
    chk("텍스트문서" in st.get_manual(P[0]) and "스캔문서" not in st.get(P[0]) and "스캔문서" in st.get_rejected(P[0]),
        "H 스캔문서·텍스트문서도 하나만 — 자동 스캔문서는 거절", str(st.record(P[0])))
    chk(rows(la).get("텍스트문서", "").endswith("✓"), "H 붙인 속성 줄은 ✓ 로 남는다")

    # G
    i = dlg.cmb_tagf.findData("newtag")
    dlg.cmb_tagf.setCurrentIndex(i); pump()
    vis = [dlg.lst_files.item(k).data(Qt.ItemDataRole.UserRole) for k in range(dlg.lst_files.count()) if not dlg.lst_files.isRowHidden(k)]
    chk(i > 0 and vis == [P[0], P[1]], "G 태그 콤보 '있음' — 그 태그가 있는 파일만", str(vis))
    dlg.cmb_has.setCurrentIndex(1); pump()
    vis = [dlg.lst_files.item(k).data(Qt.ItemDataRole.UserRole) for k in range(dlg.lst_files.count()) if not dlg.lst_files.isRowHidden(k)]
    chk(vis == [P[2]], "G '없음' — 없는 파일만", str(vis))
    dlg.reject()
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
