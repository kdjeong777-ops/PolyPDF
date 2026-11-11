# -*- coding: utf-8 -*-
"""사진 기본 정보 태그(meta) 지키기 · 새 태그 후보 쓰기를 메인에서 빼기 (태그 SOT §8.1·§5.7·§6.1-⑥, 응답성 SOT §4.8 — 261111-26·-28).

261111-26 (SOT 점검 D·D', 사용자 답 '둘 다 막기'):
A. '#' 메뉴 '자동 부여 취소 ▸' 에 사진 기본 정보 태그(지역·장비·날짜·스크린샷)가 없다 — 실제 메뉴를 만들어 본다.
   다른 부분(kind 등)에도 같은 태그가 있으면 그 부분만 회수하고, 기본 정보로 붙은 파일은 그대로.
B. 정보를 지운 사본(공유용 — 위치만·정보 모두, PDF 가림)은 기본 정보 태그를 넘기지 않는다 — 직접 붙인 태그·다른
   자동 태그는 그대로 따라간다(261111-10). 보통 사본(복사·다른 이름으로 저장)과 사진 평탄화 사본(261111-26 덧붙임, 사용자 답 '평탄화는 따라가게')은 종전대로 모두 따라간다.
261111-28 (SOT 점검 결함 1):
C. '해시태그 넣기' 창 [무시]·후보 [적용]과 후보 적립(`merge_candidates`)이 `tag_candidates.json` 을 메인에서 쓰지 않는다
   — 백신이 바꿔 끼우기를 2초 붙드는 상황을 흉내 내 메인 정지를 잰다(기준 1초, 응답성 SOT §5).
"""
import os, sys, tempfile, shutil, time, inspect
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_meta_guard_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "기본 정보 태그·후보 쓰기", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tagmeta_"))
try:
    from viewer.app import MainWindow
    from viewer import bg_write
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.show(); app.processEvents()
    bt = mw.bookmark_tree
    st = bt._tags

    # A '자동 부여 취소' 메뉴
    p1, p2, p3 = (str(tmp / n) for n in ("p1.jpg", "p2.jpg", "p3.jpg"))
    for p in (p1, p2, p3):
        Path(p).write_bytes(b"x")
    st.set_auto_part(p1, "meta", ["2026-11-05", "고양시", "Galaxy S24", "스크린샷"])
    st.set_auto_part(p2, "kind", ["영수증", "스크린샷"])     # '스크린샷' 이 다른 부분에도 있다
    st.set_auto_part(p3, "kind", ["영수증"])
    bt._list_tag_counts = lambda: {"영수증": 2}            # 목록 줄 개수는 이 검사와 무관 — 풀다운 본문이 만들어지게만
    bt._rebuild_tag_menu()
    sub = [a.menu() for a in bt._tag_menu.actions() if a.menu() is not None and a.text() == "자동 부여 취소"]
    names = [a.text().lstrip("·#") for a in sub[0].actions()] if sub else []
    chk(names and "영수증" in names, "A 준비 — 다른 자동 태그는 메뉴에 있다", str(names))
    chk(not {"고양시", "Galaxy S24", "2026-11-05"} & set(names), "A 사진 기본 정보 태그는 '자동 부여 취소' 에 없다", str(names))
    chk("스크린샷" in names, "A 다른 부분에도 붙은 태그는 남는다(그 부분만 회수)", str(names))
    act = [a for a in sub[0].actions() if a.text().lstrip("·#") == "스크린샷"] if sub else []
    if act:
        act[0].trigger(); app.processEvents()
    chk("스크린샷" in st.get_auto(p1) and "스크린샷" not in st.get_auto(p2),
        "A 회수해도 기본 정보로 붙은 파일은 그대로, 다른 부분만 빠진다", f"{st.get_auto(p1)} {st.get_auto(p2)}")

    # B 정보를 지운 사본
    src = str(tmp / "s.jpg"); Path(src).write_bytes(b"x")
    st.set(src, ["가족"])
    st.set_auto_part(src, "meta", ["2026-11-05", "고양시"])
    st.set_auto_part(src, "kind", ["영수증"])
    flat, share = str(tmp / "s_flat.jpg"), str(tmp / "share" / "s.jpg")
    Path(flat).write_bytes(b"x"); Path(share).parent.mkdir(); Path(share).write_bytes(b"x")
    mw._photo_flattened(src, flat, "")
    chk(st.get_manual(flat) == ["가족"] and st.get_auto_part(flat, "meta") == ["2026-11-05", "고양시"] and "영수증" in st.get_auto(flat),
        "B 사진 평탄화 사본은 기본 정보까지 따라간다(261111-26 덧붙임, 사용자 답 '평탄화는 따라가게')", str(st.record(flat)))
    mw._photo_shared([(src, share)], [])
    chk(st.get_manual(share) == ["가족"] and st.get_auto(share) == ["영수증"] and not st.get_auto_part(share, "meta"),
        "B 공유용 사본 — 기본 정보 태그는 넘기지 않는다", str(st.record(share)))
    cp = str(tmp / "s (2).jpg"); Path(cp).write_bytes(b"x")
    mw._on_files_copied([[src, cp]])
    chk(st.get_auto_part(cp, "meta") == ["2026-11-05", "고양시"], "B 보통 사본(복사)은 기본 정보까지 종전대로", str(st.record(cp)))
    from viewer import redact_controller
    rsrc = inspect.getsource(redact_controller)
    chk("_carry_tags([(path, out)], drop_meta=True)" in rsrc, "B PDF 가림 사본도 기본 정보를 넘기지 않는다(같은 인자)")

    # C 새 태그 후보 쓰기 — 메인 정지 실측
    from viewer import tag_store as TS
    from viewer.widgets.tag_apply_dialog import TagApplyDialog
    cpath = TS._candidates_path()
    TS.save_candidates({"cand": {"보수": {"n": 2, "files": [p1]}, "포장": {"n": 1, "files": [p1]}}, "rejected": []})
    bg_write.flush()
    real_replace = os.replace

    def slow_replace(a, b, *k, **kw):                     # 백신이 바꿔 끼우기를 붙든다(실측 21.4초 — 여기선 2초)
        if str(b).endswith("tag_candidates.json"):
            time.sleep(2.0)
        return real_replace(a, b, *k, **kw)
    os.replace = slow_replace
    try:
        dlg = TagApplyDialog(st, [p1, p2, p3], [], show_candidates=True)
        dlg.show(); app.processEvents()
        it = [dlg.lst_cand.item(i) for i in range(dlg.lst_cand.count()) if dlg.lst_cand.item(i).data(Qt.ItemDataRole.UserRole) == "포장"]
        chk(bool(it), "C 준비 — 후보 '포장' 이 보인다")
        if it:
            it[0].setSelected(True); app.processEvents()
        t0 = time.perf_counter(); dlg._dismiss(); dt = time.perf_counter() - t0
        chk(dt < 1.0, "C [무시] 가 메인에서 파일을 쓰지 않는다(정지 < 1초)", "%.2fs" % dt)
        chk("포장" in TS.load_candidates()["rejected"], "C 쓰기 전에 다시 읽어도 무시한 것이 보인다")
        for i in range(dlg.lst_cand.count()):
            dlg.lst_cand.item(i).setSelected(dlg.lst_cand.item(i).data(Qt.ItemDataRole.UserRole) == "보수")
        app.processEvents()
        dlg.lst_files.selectAll(); app.processEvents()
        t0 = time.perf_counter(); dlg.apply_tags(True); dt = time.perf_counter() - t0
        chk(dt < 1.0, "C 후보 [적용] 이 메인에서 파일을 쓰지 않는다(정지 < 1초)", "%.2fs" % dt)
        dlg.reject()
        t0 = time.perf_counter(); TS.merge_candidates({"새말": {"n": 1, "files": [p2]}}); dt = time.perf_counter() - t0
        chk(dt < 1.0, "C 후보 적립(merge_candidates)도 메인에서 쓰지 않는다", "%.2fs" % dt)
    finally:
        chk(bg_write.flush(timeout=20), "C 배경 쓰기가 끝난다")
        os.replace = real_replace
    d = __import__("json").loads(cpath.read_text(encoding="utf-8"))
    chk("보수" not in d["cand"] and "포장" in d["rejected"] and "새말" in d["cand"], "C 디스크에 마지막 내용이 남는다", str(d))
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
