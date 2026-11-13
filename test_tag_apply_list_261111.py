# -*- coding: utf-8 -*-
"""해시태그 수정 창 태그 목록·창 크기 (태그 SOT §8.7·§8.1, 261111-16·-17 사용자 지시·결정).

사용자 원문: "사진의 경우 사진찍을때의 위치, 찍은장비, 일시 등 기본정보를 이용한 태그는 수정/삭제하지 못하도록 리스트에서 삭제 ·
태그 리스트는 이름순서, 등록순서로 정렬 · 태그 리스트 위에 검색창 추가 · 창을 전체화면 보기 가능하도록 수정".
사용자 결정: 태그 편집 창에서도 막기 · 정렬 기본 이름순·전환·기억 · 검색은 담은 태그만(후보도)·없으면 바로 추가 · 최대화 + 크기 기억.
A. 사진 기본 정보 태그(meta 부분)는 목록에 없다 — 사진 종류·PDF 자동·직접 태그는 있다, [해제] 가 기본 정보 태그를 거절하지 않는다
B. 정렬 — 기본 이름순, 등록순(처음 붙은 차례)
C. 검색창 — 두 목록 모두 담은 태그만(대소문자 무시)·후보도 거름·없으면 [추가] 로 곧바로 붙임(261114-2 덧붙임)
D. 태그 편집 창 — 사진 기본 정보 태그는 ✕·📌 없이 잠김
E. 최대화 단추·크기·최대화·정렬을 기억(실제 MainWindow.open_tag_apply)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_apply_list_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "해시태그 넣기 목록", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tagapplylist_"))
try:
    from viewer.tag_store import TagStore, save_candidates
    from viewer.widgets.tag_apply_dialog import TagApplyDialog
    st = TagStore(tmp / "tags.json")
    P, Q = str(tmp / "p.jpg"), str(tmp / "a.pdf")
    st.set(Q, ["배수성"]); st.set_auto(Q, ["보고서"])                     # 먼저 등록된 파일
    st.set_auto_part(P, "meta", ["2026-11-05", "고양시", "iPhone13Pro"])
    st.set_auto_part(P, "kind", ["영수증"])
    st.set(P, ["가족"])
    save_candidates({"cand": {"보수": {"n": 2, "files": [Q]}, "아스팔트": {"n": 1, "files": [Q]}}, "rejected": []})   # 근거 파일이 목록에 있어야 늘어놓는다(261111-20 덧붙임)
    dlg = TagApplyDialog(st, [P, Q], [P, Q])
    names = lambda: [dlg.lst_tags.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dlg.lst_tags.count())]
    avail = lambda kind=None: [dlg.lst_avail.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dlg.lst_avail.count())
                               if dlg.lst_avail.item(i).data(Qt.ItemDataRole.UserRole)
                               and (kind is None or dlg.lst_avail.item(i).data(Qt.ItemDataRole.UserRole + 1) == kind)]
    chk(sorted(names()) == sorted(["가족", "영수증", "배수성", "보고서"]), "A 사진 기본 정보 태그(촬영일·지역·장비)는 붙은 태그에 없다", str(names()))
    chk(not {"고양시", "iPhone13Pro", "2026-11-05"} & set(avail()), "A 붙일 수 있는 태그에도 없다(261114-2 덧붙임)", str(avail()))
    chk(names() == sorted(names(), key=str.lower), "B 기본 이름순", str(names()))
    dlg.cmb_sort.setCurrentIndex(1)
    chk(names()[:2] == ["배수성", "보고서"], "B 등록순 — 먼저 붙은 태그 먼저", str(names()))
    dlg.ed_find.setText("보")
    chk(names() == ["보고서"] and avail("cand") == ["보수"], "C 검색 — 두 목록 모두 담은 태그만(후보도)", f"{names()} {avail('cand')}")
    chk(dlg.btn_find_add.isEnabled(), "C 같은 이름이 없으면 [추가] 켜짐")
    dlg.ed_find.setText("보고서")
    chk(not dlg.btn_find_add.isEnabled(), "C 같은 이름이 있으면 [추가] 꺼짐")
    dlg.ed_find.setText("새것"); dlg._find_add()
    chk("새것" in names() and "새것" in st.get_manual(P) and "새것" in st.get_manual(Q),
        "C 찾는 글자로 바로 고른 파일에 붙인다(261114-2 덧붙임)", str(names()))
    dlg.ed_find.setText("")
    st.set(P, ["가족", "고양시"])                                            # 같은 이름을 직접도 붙였다
    dlg._fill_tags()
    chk("고양시" in names(), "A 같은 이름을 직접 붙였으면 목록에 있다")
    dlg.lst_files.clearSelection(); dlg.lst_files.item(0).setSelected(True)
    dlg.lst_tags.clearSelection()
    for i in range(dlg.lst_tags.count()):
        if dlg.lst_tags.item(i).data(Qt.ItemDataRole.UserRole) == "고양시":
            dlg.lst_tags.item(i).setSelected(True)
    dlg.btn_clear.click()
    chk("고양시" not in st.get_manual(P) and "고양시" in st.get_auto(P) and "고양시" not in st.get_rejected(P),
        "A [해제] 는 직접 태그만 떼고 기본 정보 태그는 거절하지 않는다", f"{st.get(P)} {st.get_rejected(P)}")
    dlg.reject()

    # D 태그 편집 창
    from viewer.widgets.tag_edit_dialog import TagEditDialog
    te = TagEditDialog("p", ["가족"], [], auto_tags=st.get_auto(P), locked_tags=st.get_auto_part(P, "meta"))
    chk("고양시" not in te._rej_btns and "고양시" not in te._pin_btns and "영수증" in te._rej_btns,
        "D 태그 편집 창 — 기본 정보 태그는 ✕·📌 없음, 사진 종류는 그대로", str(list(te._rej_btns)))
    te.reject()

    # E 창 크기·최대화·정렬 기억 — 실제 MainWindow.open_tag_apply
    from viewer.app import MainWindow
    from viewer.widgets import tag_apply_dialog as TAD
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.show(); app.processEvents()
    seen = []

    def fake_exec(self_):
        seen.append(self_)
        chk(bool(self_.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint), "E 최대화 단추") if len(seen) == 1 else None
        if len(seen) == 1:
            self_.show(); self_.resize(1000, 640); self_.cmb_sort.setCurrentIndex(1); app.processEvents()   # 261114-2 덧붙임: 두 목록이라 최소 너비가 900 보다 넓다
            self_.showMaximized(); app.processEvents()
        else:
            self_.show(); app.processEvents(); app.processEvents()
        self_.done(0)
        return 0
    TAD.TagApplyDialog.exec = fake_exec
    mw.open_tag_apply()
    stv = (mw._prefs or {}).get("tag_apply_window") or {}
    chk(stv.get("max") is True and stv.get("sort") == "reg" and stv.get("w") == 1000 and stv.get("h") == 640,
        "E 닫을 때 크기·최대화·정렬을 설정에 기억", str(stv))
    mw.open_tag_apply()
    d2 = seen[-1]
    chk(d2.cmb_sort.currentData() == "reg" and d2.isMaximized(), "E 다시 열면 정렬·최대화 그대로", f"{d2.cmb_sort.currentData()} {d2.isMaximized()}")
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
