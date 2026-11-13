# -*- coding: utf-8 -*-
"""해시태그 수정 창 — 태그 고르면 오른쪽 거르기(있음/없음)·기간 거르기·새 태그 후보 ↔ 현재 태그 (태그 SOT §8.7, 261111 사용자 지시·결정).

사용자 원문: "리스트의 체크가 해제된 상태에서 선택할 경우 우측에 해당 해시테그가 없는 리스트를 보여주고, 체크된 상태에는 해당 해시테그가 있는
리스트를 보여줌 · 날짜나 기간을 필터링할 수 있도록 함 · 새태그 후보를 선택시 우측 화면에서 해당 리스트를 보여주고, 해당리스트를 선택. 새태그 후보
작업시 현재 태그 리스트의 활성화 해제. 그 반대도 적용 · 다중선택 가능". 사용자 결정: 거르기 상자·콤보 + 직접 기간·근거 파일만 자동 선택.
A. 태그 줄 체크 = 있는 것, 해제 = 없는 것 — 여러 줄은 모두 만족, 고른 줄 없으면 전체, 숨은 칸은 적용 대상이 아니다
B. 기간 — 사진은 사진 정보 색인의 촬영일(없으면 파일 날짜), PDF 는 파일 날짜 · 최근 7일·직접 기간
D. 새 태그 후보 개수·목록은 지금 책갈피창 목록 기준(261111-20 덧붙임)
C. 새 태그 후보를 고르면 근거 파일만 보이고 모두 고른 채로, 현재 태그는 고름이 풀리고 흐려진다 — 반대도
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QDate
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_apply_filter_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond, timeout=10.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tagfilter_"))
try:
    from viewer.tag_store import TagStore, save_candidates
    from viewer import photo_index
    from viewer.widgets.tag_apply_dialog import TagApplyDialog
    A, B, C, P = (str(tmp / n) for n in ("a.pdf", "b.pdf", "c.pdf", "p.jpg"))
    for f in (A, B, C, P):
        Path(f).write_bytes(b"x")
    now = time.time()
    os.utime(A, (now - 3 * 86400, now - 3 * 86400))
    os.utime(B, (now - 40 * 86400, now - 40 * 86400))
    con = photo_index.connect()
    photo_index.upsert(con, os.path.normcase(P), P, photo_index.norm_folder(tmp), "p.jpg", ".jpg", 1, 1, {"taken": "2020:01:02 10:00:00"}, [])
    con.commit(); con.close()
    st = TagStore(tmp / "tags.json")
    st.set(A, ["가족"]); st.set(B, ["가족", "여행"])
    X = str(tmp / "other" / "x.pdf")                       # 다른 폴더(지금 목록 밖)
    save_candidates({"cand": {"보수": {"n": 57, "files": [B, C, X]}, "외부": {"n": 9, "files": [X]}}, "rejected": []})
    dlg = TagApplyDialog(st, [A, B, C, P], [], show_candidates=True)
    dlg.resize(1100, 700); dlg.show()
    lw = dlg.lst_files
    vis = lambda: sorted(os.path.basename(lw.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(lw.count()) if not lw.isRowHidden(i))

    def pick(*tags, has=None):
        dlg.lst_tags.clearSelection()
        for i in range(dlg.lst_tags.count()):
            it = dlg.lst_tags.item(i)
            t = it.data(Qt.ItemDataRole.UserRole)
            if has and t in has:
                it.setCheckState(Qt.CheckState.Checked if has[t] else Qt.CheckState.Unchecked)
            if t in tags:
                it.setSelected(True)
        app.processEvents()

    # A
    chk(vis() == ["a.pdf", "b.pdf", "c.pdf", "p.jpg"], "A 고른 태그가 없으면 전체", str(vis()))
    pick("여행")
    chk(vis() == ["b.pdf"], "A 체크된 태그를 고르면 그 태그가 있는 파일만", str(vis()))
    pick("여행", has={"여행": False})
    chk(vis() == ["a.pdf", "c.pdf", "p.jpg"], "A 체크를 풀면 그 태그가 없는 파일만", str(vis()))
    pick("가족", "여행", has={"가족": True, "여행": False})
    chk(vis() == ["a.pdf"], "A 여러 줄을 고르면 조건을 모두 만족하는 파일만", str(vis()))
    lw.selectAll(); app.processEvents()
    chk([os.path.basename(p) for p in dlg.selected_paths()] == ["a.pdf"], "A 숨은 칸은 적용 대상이 아니다", str(dlg.selected_paths()))
    dlg.lst_tags.clearSelection(); app.processEvents()
    chk(len(vis()) == 4, "A 고름을 풀면 다시 전체")

    # B 기간
    chk(pump(lambda: dlg.cmb_period.isEnabled(), 10), "B 날짜를 읽으면 기간 칸이 켜진다")
    dlg.cmb_period.setCurrentIndex(dlg.cmb_period.findData("7")); app.processEvents()
    chk(vis() == ["a.pdf", "c.pdf"], "B 최근 7일 — PDF 는 파일 날짜, 사진은 촬영일(2020)이라 빠진다", str(vis()))
    dlg.cmb_period.setCurrentIndex(dlg.cmb_period.findData("custom")); app.processEvents()
    chk(dlg.d_from.isVisible() and dlg.d_to.isVisible(), "B '직접' 이면 시작·끝 날짜 칸")
    dlg.d_from.setDate(QDate(2020, 1, 1)); dlg.d_to.setDate(QDate(2020, 1, 31)); app.processEvents()
    chk(vis() == ["p.jpg"], "B 직접 기간 — 사진 촬영일로", str(vis()))
    pick("가족")
    chk(vis() == [], "B 태그 거르기와 기간을 함께", str(vis()))
    dlg.cmb_period.setCurrentIndex(dlg.cmb_period.findData("all")); app.processEvents()
    chk(vis() == ["a.pdf", "b.pdf"], "B 전체로 돌리면 태그 거르기만", str(vis()))

    # D 261111-20 덧붙임 — 후보는 지금 목록 기준(근거 파일 중 목록에 있는 것만 센다, 없으면 늘어놓지 않는다)
    ctext = {dlg.lst_cand.item(i).data(Qt.ItemDataRole.UserRole): dlg.lst_cand.item(i).text() for i in range(dlg.lst_cand.count())}
    chk(ctext == {"보수": "#보수  (2건)"}, "D 후보 개수 = 근거 파일 중 지금 목록에 있는 수, 목록에 없는 후보는 없다", str(ctext))
    from viewer import tag_store as TS
    chk(getattr(TS, "CAND_FILES_MAX", 8) >= 100, "D 후보 근거 파일 기록이 8개에 막히지 않는다", str(getattr(TS, "CAND_FILES_MAX", 8)))

    # C 후보 ↔ 현재 태그
    dlg.lst_cand.item(0).setSelected(True); app.processEvents()
    sel = sorted(os.path.basename(p) for p in dlg.selected_paths())
    chk(vis() == ["b.pdf", "c.pdf"] and sel == ["b.pdf", "c.pdf"], "C 후보를 고르면 근거 파일만 보이고 모두 고른 채로", f"{vis()} {sel}")
    chk(not dlg.lst_tags.selectedItems() and dlg.lst_tags.styleSheet() != "" and dlg.lst_cand.styleSheet() == "",
        "C 현재 태그는 고름이 풀리고 흐려진다")
    chk(dlg.chosen_tags() == ["보수"], "C 적용 대상 태그는 후보만", str(dlg.chosen_tags()))
    pick("여행", has={"여행": True})
    chk(not dlg.lst_cand.selectedItems() and dlg.lst_cand.styleSheet() != "" and dlg.lst_tags.styleSheet() == "" and vis() == ["b.pdf"],
        "C 반대로 현재 태그를 고르면 후보가 풀리고 흐려진다", str(vis()))
    dlg.reject()
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
