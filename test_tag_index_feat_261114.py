# -*- coding: utf-8 -*-
"""색인 때 태그 재료 · 입력이 같으면 건너뛰기 · 색인 중 50개마다 종류·속성 (태그 SOT §8.2, 응답성 SOT 감사표, 261114-4 사용자 지시·결정).

사용자 지시: "인덱싱을 위해 파일을 열 때 판단하여 해시태그 적용을 함께하는 것이 좋을지 검토해 … 인댁싱 중에 어느정도 진행되면 해시태그를
적용하는 것을 검토해. 속도나 안정성을 감안해야해". 사용자 결정: 색인 때 재료 뽑기 · 50개마다 종류·속성부터.
실제 PdfIndex·AutoTagWorker·MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 색인하면 `tagfeat` 재료가 생기고, 파일이 바뀌면 낡은 것으로(None), 색인에서 빼면 지워진다
B. 재료로 되살린 특징 = 새로 뽑은 특징과 같은 판정(종류·속성·키워드)
C. 태그 계산은 재료가 있으면 파일을 다시 읽지 않는다(extract_features 0번), 없으면 만들어 적어 둔다
D. 입력 서명이 같으면 통째로 건너뛴다 — 저장소 기록이 다르거나 force 면 계산
E. 앱 — 색인 진행 50개마다 종류·속성만 붙고 주제 태그는 그대로, 전체 계산이 끝나면 서명을 적어 다음 계산은 건너뛴다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_index_feat_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "색인 태그 재료", echo=False)
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
        time.sleep(0.01)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_idxfeat_"))


def mk(name, n=3, text="Porous asphalt pavement permeability durability study results ", created="D:20240315"):
    p = tmp / "docs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((40, 60), (text * 4) + str(i), fontsize=8)
    d.set_metadata({"creationDate": created})
    d.save(str(p)); d.close()
    return str(p)


try:
    from viewer.indexer import PdfIndex
    from viewer import auto_tag as AT
    from viewer.workers import AutoTagWorker, run_in_thread
    db = str(tmp / "index.db")
    P = [mk("doc%d.pdf" % i) for i in range(4)]
    ix = PdfIndex(db)
    for p in P:
        ix.index_file(Path(p))

    # A
    got = ix.tagfeat(P[0])
    chk(got is not None and got[0].get("v") == AT.FEAT_VER and got[1], "A 색인하면 재료(+지문)가 생긴다", str(got and list(got[0])))
    os.utime(P[3], (time.time() + 5, time.time() + 5))
    chk(ix.tagfeat(P[3]) is None, "A 파일이 바뀌면 낡은 재료는 쓰지 않는다")
    ix.remove_file(Path(P[2]))
    chk(ix.conn.execute("SELECT COUNT(*) FROM tagfeat WHERE key LIKE ?", ("%doc2.pdf",)).fetchone()[0] == 0, "A 색인에서 빼면 재료도 지운다")
    ix.index_file(Path(P[2]))

    # B
    texts = ix.page_texts(P[0])
    fresh = AT.extract_features(P[0], page_texts=texts)
    back = AT.features_from_dict(P[0], AT.features_to_dict(fresh))
    kw = lambda f: [w["word"] for w in AT.suggest_keywords(f, {"porous": 1}, 3)]      # noqa: E731
    chk(AT.classify_format(back, {}) == AT.classify_format(fresh, {}) and AT.pdf_attr_tags(back, {}) == AT.pdf_attr_tags(fresh, {})
        and kw(back) == kw(fresh), "B 재료로 되살린 특징 = 새로 뽑은 특징(종류·속성·키워드)", f"{kw(back)} {kw(fresh)}")
    ix.close()

    # C
    calls = []
    real_ef = AT.extract_features
    AT.extract_features = lambda *a, **k: (calls.append(a[0]), real_ef(*a, **k))[1]
    keep = []

    def run(w):
        done = {}
        w.finished.connect(lambda r, s: done.update(r=r, s=s))
        run_in_thread(w, keep)
        pump(lambda: "r" in done, 60)
        return done
    d1 = run(AutoTagWorker(db, P, {}, known_tags=[], rules={}, today_year=2026, store_keys=set(), fp_missing_keys=set(), store_hash="h0"))
    chk([os.path.basename(c) for c in calls] == ["doc3.pdf"], "C 재료가 있으면 다시 읽지 않는다 — 낡은 doc3 만 새로 뽑는다", str(calls))
    ix = PdfIndex(db)
    chk(ix.tagfeat(P[3]) is not None, "C 새로 뽑은 재료는 적어 둔다")
    ix.close()
    AT.extract_features = real_ef
    res = {r["path"]: [t for t, _ in r["auto"]] for r in d1.get("r", [])}
    chk(all("텍스트문서" in res.get(p, []) and "영어" in res.get(p, []) for p in P), "C 재료로 판정 — 속성 태그", str(res))

    # D
    s = d1["s"]
    ix = PdfIndex(db); ix.set_tagscan_sig(s["sig_key"], AutoTagWorker.final_sig(s["base_sig"], "h1", [])); ix.close()
    w2 = AutoTagWorker(db, P, {}, known_tags=[], rules={}, today_year=2026, store_keys=set(), fp_missing_keys=set(), store_hash="h1")
    d2 = run(w2)
    chk(w2.skipped and d2["r"] == [] and d2["s"].get("skipped"), "D 입력 서명이 같으면 통째로 건너뛴다")
    w3 = AutoTagWorker(db, P, {}, known_tags=[], rules={}, today_year=2026, store_keys=set(), fp_missing_keys=set(), store_hash="h2")
    run(w3)
    chk(not w3.skipped, "D 저장소 기록이 다르면 다시 계산")
    w4 = AutoTagWorker(db, P, {}, known_tags=[], rules={}, today_year=2026, store_keys=set(), fp_missing_keys=set(), store_hash="h1", force=True)
    run(w4)
    chk(not w4.skipped, "D force('태그 다시 계산'·규칙 적용)면 계산")

    # E 앱
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True; mw.show(); pump(lambda: False, 0.3)
    mw._db_path = Path(db)
    bt, st = mw.bookmark_tree, mw.bookmark_tree._tags
    bt.all_file_paths = lambda: list(P)
    st.set_auto(P[0], ["아스팔트", "보고서"])
    st.set_auto_part  # noqa: B018
    mw._light = {"t": time.monotonic(), "n": 0, "done": set(), "backup": False, "worker": None, "pending": False}
    mw._on_index_progress(10, 100, P[0])
    chk(mw._light["worker"] is None, "E 50개 전·10초 전에는 가벼운 판정을 걸지 않는다")
    mw._on_index_progress(50, 100, P[1])
    chk(pump(lambda: mw._light.get("worker") is None and "텍스트문서" in st.get_auto(P[1]), 20), "E 색인 50개 — 종류·속성이 붙는다", str(st.get(P[1])))
    chk("아스팔트" in st.get_auto(P[0]) and "보고서" not in st.get_auto(P[0]) and "텍스트문서" in st.get_auto(P[0]),
        "E 주제 태그는 그대로, 종전 종류(보고서)는 새 판정으로", str(st.get_auto(P[0])))
    mw._prefs["auto_tag_enabled"] = True
    mw._index_workers = []
    mw._probe_busy = False
    ends = []
    real_fin = mw._on_autotag_finished
    mw._on_autotag_finished = lambda r, s_: (ends.append(s_), real_fin(r, s_))[1]
    mw._start_autotag_scan(force=True)
    chk(pump(lambda: bool(ends), 60), "E 전체 계산이 끝난다")
    t = mw.__dict__.get("_tagscan_thread")
    if t is not None:
        t.join(10)
    ends.clear()
    mw._start_autotag_scan()
    chk(pump(lambda: bool(ends), 60) and ends[0].get("skipped"), "E 다음 계산은 입력이 같아 건너뛴다", str(ends[:1]))
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
