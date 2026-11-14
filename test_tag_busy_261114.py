# -*- coding: utf-8 -*-
"""태그 계산 중임을 보인다 · 종류·속성은 하는 대로 바로 (태그 SOT §8.2, 응답성 SOT §4.6, 261114-13 사용자 결정).

사용자 보고(261114-10 덧붙임): 스톱워치 Q&Q-HS43 이 #발표자료 — 고친 판정이 03:18 옛 판정을 덮기 전(재료 없는 큰 폴더의 첫 다시 계산이 수십 분)에 봤다.
사용자 결정: 작업 창에 올리기 · 종류·속성은 하는 대로 바로 바꿈(지금 연·보이는 파일 먼저) · '해시태그 수정' 창·'#' 메뉴에 한 줄 알림.
실제 AutoTagWorker·MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 워커 — 먼저 할 파일(priority)을 맨 앞에서 계산해 바로 내보내고, 1패스 동안 50개마다 종류·속성을 내보낸다, [중단]이면 끝을 알린다(cancelled)
B. 앱 — 계산이 도는 동안 작업 창에 '태그 계산'(진행 글 k/n·남은 시간, [중단] 가능), 끝나면 내려간다
C. 앱 — 옛 자동 종류(발표자료)가 전체 계산이 끝나기 **전에** 새 종류(설명서)로 바뀐다, 주제 태그는 그대로
D. 도는 동안 '#' 메뉴 맨 위·'해시태그 수정' 창에 '태그 계산 중' 한 줄, 끝나면 없다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QLabel
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_busy_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "태그 계산 중", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def pump(cond, timeout=20.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tagbusy_"))


def mk(rel, text="Porous asphalt pavement permeability durability study results "):
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    d = fitz.open()
    for i in range(2):
        d.new_page().insert_text((40, 60), (text * 3) + str(i), fontsize=8)
    d.save(str(p)); d.close()
    return str(p)


try:
    from viewer import auto_tag as AT
    from viewer.workers import AutoTagWorker
    from viewer.indexer import PdfIndex
    db = str(tmp / "index.db")
    PdfIndex(db).close()
    P = [mk("docs/d%03d.pdf" % i) for i in range(120)]
    MAN = mk("docs/11.2 설명서.홈/스탑워치.pdf")      # 폴더 이름 → 설명서
    ALL = P + [MAN]

    # 파일마다 조금 늦게(재료 만들기가 긴 큰 폴더처럼) — 진행 중 상태를 볼 수 있게
    _real = AT.extract_features

    def _slow(*a, **k):
        time.sleep(0.02)
        return _real(*a, **k)
    AT.extract_features = _slow

    # A 워커
    try:
      w = AutoTagWorker(db, ALL, {}, [], {}, 2026, set(), set(), force=True, priority=[MAN])
      chk(w.paths[0] == MAN, "A 먼저 할 파일이 맨 앞", w.paths[0][-20:])
      got, fin = [], []
      w.found.connect(lambda d: got.append(dict(d)))
      w.finished.connect(lambda r, s: fin.append(s))
      w.run()
      chk(got and MAN in got[0] and "설명서" in got[0][MAN], "A 먼저 할 파일의 종류를 곧바로 내보낸다", str(got[:1])[:200])
      n_all = sum(len(g) for g in got)
      chk(len(got) >= 3 and n_all == len(ALL), "A 1패스 동안 묶음으로 모두 내보낸다", "%d 묶음 %d 파일" % (len(got), n_all))
      w2 = AutoTagWorker(db, ALL, {}, [], {}, 2026, set(), set(), force=True)
      fin2 = []
      w2.finished.connect(lambda r, s: fin2.append(s))
      w2.progress.connect(lambda d, t, p: w2.request_cancel() if d == 5 else None)
      w2.run()
      chk(fin2 and fin2[0].get("cancelled"), "A [중단]이면 끝을 알린다(cancelled)", str(fin2)[:120])
    except Exception as e:
        chk(False, "A 워커", repr(e))

    # B·C·D 앱
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True; mw.show(); pump(lambda: False, 0.3)
    mw._db_path = Path(db)
    mw.AUTOTAG_ETA_MIN_S = 0                       # 짧은 검사에서도 남은 시간 글을 본다(앱은 30초 넘을 때만)
    _ix = PdfIndex(db)
    with _ix.conn:
        _ix.conn.execute("DELETE FROM tagfeat")
    _ix.close()
    bt, st = mw.bookmark_tree, mw.bookmark_tree._tags
    bt.all_file_paths = lambda: list(ALL)
    st.set_auto(MAN, ["2013-01-02", "아스팔트", "발표자료"])      # 옛 판정(고치기 전 계산)
    mw._prefs["auto_tag_enabled"] = True
    mw._index_workers = []
    mw._probe_busy = False
    seen = {"job": False, "msg": "", "early": False, "menu": "", "dlg": ""}
    ends = []
    real_fin = mw._on_autotag_finished
    mw._on_autotag_finished = lambda r, s_: (ends.append(s_), real_fin(r, s_))[1]

    def watch():
        jobs = getattr(mw, "_jobs", {}) or {}
        if "autotag" in jobs:
            seen["job"] = True
            m = jobs["autotag"].get("msg") or ""
            if "남은" in m or not seen["msg"]:
                seen["msg"] = m
            seen["stop"] = bool(jobs["autotag"].get("cancel"))
            seen["bar"] = mw.progress.isVisible()
        if not ends and not seen["early"] and "설명서" in st.get_auto(MAN):
            seen["early"] = True
            seen["topic"] = "아스팔트" in st.get_auto(MAN) and "발표자료" not in st.get_auto(MAN)
        if not ends and not seen["menu"] and seen["job"]:
            bt._rebuild_tag_menu()
            acts = bt._tag_menu.actions()
            seen["menu"] = acts[0].text() if acts else ""
            from viewer.widgets.tag_apply_dialog import TagApplyDialog
            dlg = TagApplyDialog(st, [MAN], [MAN], mw, keep=mw.__dict__.setdefault("_thread_keep", []))
            lab = dlg.findChild(QLabel, "tag_busy")
            seen["dlg"] = lab.text() if lab is not None and not lab.isHidden() else ""
            dlg.close(); dlg.deleteLater()
        return bool(ends)

    mw._start_autotag_scan(force=True)
    chk(pump(watch, 120), "B 전체 계산이 끝난다")
    chk(seen["job"] and seen.get("stop") and seen.get("bar"), "B 도는 동안 작업 창에 '태그 계산'([중단] 가능·진행 막대)", str(seen)[:200])
    chk("/" in seen["msg"] and ("남은" in seen["msg"] or "remaining" in seen["msg"].lower()), "B 진행 글 k/n·남은 시간", seen["msg"])
    chk("autotag" not in (getattr(mw, "_jobs", {}) or {}), "B 끝나면 작업 창에서 내려간다")
    chk(seen["early"], "C 옛 종류(발표자료)가 전체 계산이 끝나기 전에 설명서로 바뀐다", str(st.get(MAN)))
    chk(seen.get("topic"), "C 그때 주제 태그는 그대로·옛 종류는 빠진다(주제는 전체 계산 몫)", str(seen.get("topic")))
    chk(seen["menu"].startswith("태그 계산 중"), "D '#' 메뉴 맨 위에 '태그 계산 중' 한 줄", repr(seen["menu"]))
    chk(seen["dlg"].startswith("태그 계산 중"), "D '해시태그 수정' 창에 '태그 계산 중' 한 줄", repr(seen["dlg"]))
    bt._rebuild_tag_menu()
    acts = bt._tag_menu.actions()
    chk(not (acts and acts[0].text().startswith("태그 계산 중")), "D 끝나면 '#' 메뉴에 그 줄이 없다")
    chk(not mw.autotag_busy_text(), "D 끝나면 알림 글이 없다")
    t = mw.__dict__.get("_tagscan_thread")
    if t is not None:
        t.join(10)
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
