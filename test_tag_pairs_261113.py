# -*- coding: utf-8 -*-
"""해시태그 수정 창 — 이름·위 줄·고른 파일만·한영 쌍 태그 (태그 SOT §8.7·§8.9, 검색 SOT §5.1, 261113-9 사용자 지시·결정).

사용자 지시(2026-11-13): '해시태그 넣기' → '해시태그 수정', 책갈피창에서 고른 파일만, 되돌리기·다시 실행은 꾸밈의 그림 단추,
되돌리기 왼쪽 '해시태그' 글·오른쪽 조금 떼어 [적용]·[해제], 한글이면 영어·영어면 한글 낱말을 추천해 쌍으로 잇고 '#균열' 이 #crack 도 찾게.
사용자 결정: 쌍 표 + 태그 하나만(파일에는 붙인 태그 하나), 검색은 '#태그 거르기만'.
실제 MainWindow·BookmarkTree 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 창 제목·'#' 메뉴 이름 '해시태그 수정', 위 줄 차례 '해시태그' · ↶ · ↷ · (간격 16px 이상) · [적용] · [해제], 그 버튼이 왼쪽 목록 위에
B. `open_tag_apply` — 책갈피창에서 고른 파일이 있으면 그 파일만, 후보 검토로 열면 목록 전체
C. 쌍 표 — 잇기·짝·끊기, 한 태그에 짝 하나, 쓰기는 배경 줄(쓰기 전 다시 읽어도 보인다), 추천은 오프라인(내장 영한 사전)
D. 창 — '태그 추가' 칸에 쓰면 짝 낱말 추천(배경), [잇기] 하면 쌍이 생기고 현재 태그 줄이 '태그 ⇄ 짝'
E. 책갈피창 `#균열` — #crack 만 붙은 파일도 보인다, `#` 없는 '균열' 은 넓히지 않는다
"""
import os, sys, tempfile, shutil, time, csv, re
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_pairs_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "해시태그 수정·한영 쌍", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def pump(cond, timeout=15.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def pdf(p):
    d = fitz.open(); d.new_page(); d.save(p); d.close()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tagpairs_"))
try:
    from viewer import bg_write, tag_pairs as TP
    from viewer.widgets.tag_apply_dialog import TagApplyDialog
    docs = tmp / "docs"; docs.mkdir()
    P = [str(docs / n) for n in ("a.pdf", "b.pdf", "c.pdf")]
    for p in P:
        pdf(p)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.show(); app.processEvents()
    bt = mw.bookmark_tree
    st = bt._tags
    st.set(P[0], ["균열"]); st.set(P[1], ["crack"]); st.set(P[2], ["포장"])

    # A
    dlg = TagApplyDialog(st, P, [], keep=mw.__dict__.setdefault("_thread_keep", []))
    dlg.resize(1100, 700); dlg.show(); app.processEvents()
    chk(dlg.windowTitle() == "해시태그 수정", "A 창 제목 '해시태그 수정'", dlg.windowTitle())
    bt._list_tag_counts = lambda: {"균열": 1}
    bt._rebuild_tag_menu()
    texts = [a.text() for a in bt._tag_menu.actions() if not a.isSeparator()]
    chk("해시태그 수정" in texts and "해시태그 넣기" not in texts, "A '#' 메뉴 이름 '해시태그 수정'", str(texts[-3:]))
    from PyQt6.QtWidgets import QLabel
    lbl = [w for w in dlg.findChildren(QLabel) if w.text() == "해시태그"]
    g = lambda w: w.mapTo(dlg, w.rect().topLeft())               # noqa: E731
    xs = [g(w).x() for w in (lbl[0] if lbl else dlg.btn_undo, dlg.btn_undo, dlg.btn_redo, dlg.btn_apply, dlg.btn_clear)]
    chk(bool(lbl) and xs == sorted(xs) and len(set(g(w).y() for w in (dlg.btn_undo, dlg.btn_apply, dlg.btn_clear))) == 1,
        "A 위 줄 차례 — '해시태그' · ↶ · ↷ · [적용] · [해제]", str(xs))
    chk(dlg.btn_undo.text() == "↶" and dlg.btn_redo.text() == "↷" and "Ctrl+Z" in dlg.btn_undo.toolTip(),
        "A 되돌리기·다시 실행은 꾸밈과 같은 그림 글자 단추(풍선에 단축키)", dlg.btn_undo.text() + dlg.btn_redo.text())
    gap = g(dlg.btn_apply).x() - (g(dlg.btn_redo).x() + dlg.btn_redo.width())
    chk(gap >= 16, "A [적용] 은 되돌리기 묶음에서 조금 떨어져", str(gap))
    chk(g(dlg.btn_apply).y() < g(dlg.lst_tags).y(), "A [적용]·[해제] 는 위 줄로 옮겼다(왼쪽 아래가 아니라)")
    dlg.reject()

    # B
    seen = []
    real_exec = TagApplyDialog.exec
    TagApplyDialog.exec = lambda self_: (seen.append(list(self_._paths)), QDialog.DialogCode.Rejected)[1]
    real_lp = mw._tag_list_paths
    mw._tag_list_paths = lambda: (list(P), [P[1], P[2], P[1]])
    mw.open_tag_apply()
    chk(seen and seen[-1] == [P[1], P[2]], "B 책갈피창에서 고른 파일만(겹치지 않게)", str(seen[-1:]))
    mw.open_tag_apply(candidates=True)
    chk(seen[-1] == P, "B 새 태그 후보 검토로 열면 목록 전체", str(seen[-1:]))
    mw._tag_list_paths = lambda: (list(P), [])
    mw.open_tag_apply()
    chk(seen[-1] == P, "B 고른 파일이 없으면 목록 전체")
    TagApplyDialog.exec = real_exec
    mw._tag_list_paths = real_lp

    # C
    pt = TP.shared()
    chk(pt.link("균열", "crack") and pt.partner("균열") == "crack" and pt.partner("CRACK") == "균열", "C 잇기·짝(대소문자 무시)")
    pt.link("균열", "fissure")
    chk(pt.partner("균열") == "fissure" and pt.partner("crack") is None, "C 한 태그에 짝 하나 — 다시 이으면 바뀐다")
    pt.link("균열", "crack")
    chk(TP.PairTable().partner("균열") == "crack", "C 쓰기 전에 다시 읽어도 보인다(bg_write 줄)")
    chk(bg_write.flush(timeout=10) and '"crack"' in TP.pairs_path().read_text(encoding="utf-8"), "C 디스크에 쌍")
    chk(pt.expand("균열") == ["균열", "crack"] and pt.expand("포장") == ["포장"], "C 거르기 넓히기 — 짝이 있을 때만")
    # 내장 영한 사전에서 한 줄을 골라 추천을 본다(오프라인)
    ref = None
    with open(Path(__file__).resolve().parent / "resources" / "en_ko_dict.csv", encoding="utf-8") as fh:
        for r in csv.reader(fh):
            if len(r) >= 2 and re.fullmatch(r"[a-z]{4,10}", r[0] or ""):
                m = [x.strip() for x in re.split(r"[,;/]", r[1]) if x.strip()]
                if m and re.fullmatch(r"[가-힣]{2,4}", m[0]):
                    ref = (r[0], m[0])
                    break
    chk(ref is not None, "C 준비 — 사전 줄", str(ref))
    if ref:
        en, ko = ref
        s_en, s_ko = TP.suggest(en), TP.suggest(ko)
        chk(ko in s_en and all(TP.is_korean(w) for w in s_en), "C 영어 → 한글 추천", f"{en} → {s_en}")
        chk(en in [w.lower() for w in s_ko] and not any(TP.is_korean(w) for w in s_ko), "C 한글 → 영어 추천", f"{ko} → {s_ko}")

        # D
        dlg = TagApplyDialog(st, P, [P[2]], keep=mw._thread_keep)
        dlg.show(); app.processEvents()
        dlg.ed_find.setText(ko)                         # 261114-2 덧붙임: 찾기 칸(종전 '태그 추가' 칸)
        chk(pump(lambda: en in [w.lower() for w in (getattr(dlg, "pair_words", None) or [])]), "D '태그 추가' 칸에 쓰면 짝 낱말 추천(배경)",
            str(getattr(dlg, "pair_words", None)))
        chk(dlg.cmb_pair.currentText().strip() != "" and dlg.btn_link.isEnabled(), "D 첫 추천이 글 상자에 — [잇기] 켜짐")
        dlg.cmb_pair.setEditText(en)
        QTest.mouseClick(dlg.btn_link, Qt.MouseButton.LeftButton); app.processEvents()
        chk((TP.shared().partner(ko) or "").lower() == en, "D [잇기] — 쌍이 생긴다", str(TP.shared().partner(ko)))
        dlg.ed_find.clear(); app.processEvents()
        lwp = dlg.lst_avail                              # 261114-2 덧붙임: 고른 파일(c.pdf)에 없는 '균열' 은 '붙일 수 있는 태그' 에
        it = [lwp.item(i) for i in range(lwp.count()) if lwp.item(i).data(Qt.ItemDataRole.UserRole) == "균열"]
        chk(it and "⇄ crack" in it[0].text(), "D 태그 줄 '태그 ⇄ 짝'", it[0].text() if it else "")
        if it:
            lwp.clearSelection(); it[0].setSelected(True); app.processEvents()
            chk(dlg.cmb_pair.currentText() == "crack" and dlg.btn_unlink.isEnabled(), "D 줄을 고르면 그 짝이 보이고 [끊기] 켜짐",
                dlg.cmb_pair.currentText())
            before = {p: st.get(p) for p in P}
            QTest.mouseClick(dlg.btn_unlink, Qt.MouseButton.LeftButton); app.processEvents()
            chk(TP.shared().partner("균열") is None and {p: st.get(p) for p in P} == before and not dlg._undo,
                "D [끊기] — 쌍만 지우고 파일 태그·되돌리기 기록은 그대로")
            TP.shared().link("균열", "crack")
        dlg.reject()
    mw.close()

    # E
    from viewer.widgets.bookmark_tree import BookmarkTree
    bt2 = BookmarkTree(); bt2.resize(320, 600); bt2.show(); app.processEvents()
    bt2._tags = st
    bt2.set_tree_view(False)
    bt2.load_folder(str(docs)); pump(lambda: len(list(bt2._iter_file_nodes())) == 3, 5)

    def visible():
        return sorted(os.path.basename(str(it.data(0, bt2.DATA_FILE))) for it in bt2._iter_file_nodes() if not it.isHidden())
    bt2.search_edit.setText("#균열"); pump(lambda: False, 0.4)
    chk(visible() == ["a.pdf", "b.pdf"], "E '#균열' — 짝 #crack 만 붙은 파일도", str(visible()))
    bt2.search_edit.setText("#crack"); pump(lambda: False, 0.4)
    chk(visible() == ["a.pdf", "b.pdf"], "E '#crack' — 반대쪽도", str(visible()))
    bt2.search_edit.setText("균열"); pump(lambda: False, 0.4)
    chk("b.pdf" not in visible(), "E '#' 없는 낱말은 넓히지 않는다(사용자 결정)", str(visible()))
    bt2.search_edit.setText("#포장"); pump(lambda: False, 0.4)
    chk(visible() == ["c.pdf"], "E 짝 없는 태그는 그대로", str(visible()))
    bg_write.flush(timeout=10)
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
