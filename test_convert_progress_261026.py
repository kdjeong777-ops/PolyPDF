# -*- coding: utf-8 -*-
"""261026-2: 변환 진행 창 글·형식 차례 (형식 변환 SOT §2.1·§5, 디자인 SOT §2.7 '진행 창 글').

사용자 보고: 전체 변환을 취소하고 1-50쪽으로 다시 변환하자 진행 창에 `24 ….pdf  parse 33  (320/1000)  |||` —
원인은 취소 뒤 남은 상태가 아니라 **엔진 내부 값**(pdf2docx 단계 이름 `parse`, 파일마다 나눈 척도 1000)이 그대로 보인 것.
가운데 정렬 글은 하트비트(`|`→`||`→`|||`)가 폭을 바꿀 때마다 출렁거렸다.

실제 처리기(`action_convert` → `_run_merge_job` 진행 창)로:
A. 형식 차례 — 형식마다 '모양 그대로' 가 위, 'Word (Microsoft Word 사용)' 은 'Word (모양 그대로)' 바로 아래, 변환 창의 처음 고른 형식 = 'Word (모양 그대로)'
B. Word(모양 그대로) 전체 변환을 진행 창 [취소] 로 멈춘 뒤 쪽 범위 11-20 으로 다시 변환하면 결과에 그 쪽만, 진행 창 글은 `단계 k/10 · 원본 p쪽`
C. 모든 형식의 진행 글이 `단계 k/n · 원본 p쪽` 꼴 — 날 글(`p.12`·`parse 33`·`make 12`)·내부 척도(/1000)가 없다, 범위 변환은 그 쪽만(편집 가능·HWPX·텍스트)
D. 실제 진행 창 글 폭이 하트비트·쪽 수가 바뀌어도 같다(`counts=False` 변환 꼴과 `(k/n)` 을 붙이는 다른 일 꼴 둘 다)
수정 전 코드로 A·B·C·D 모두 실패를 확인했다.
"""
import os, sys, re, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QProgressDialog, QPushButton, QLabel
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
import modal_guard
# 진행 창(창 모달 QProgressDialog)은 오래 떠 있는 것이 정상이라 감시 타이머는 끈다(켜면 진행 창을 닫아 변환이 취소된다)
guard = modal_guard.install(label=lambda: "변환 진행", watch_ms=0, echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=10, ms=20):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


# 진행 글 2줄 꼴: 단계 k/n · 원본 p쪽 (숫자 앞 채움은 U+2007)
STEP = re.compile(r"^(쪽 변환|쪽 분석|Word 쓰기|OCR 글자층|머리말·꼬리말 찾기|저장|Word 로 변환)"
                  r"( [ \d]+/\d+)?(  ·  원본 [ \d]+쪽)?$")
RAW = re.compile(r"\bparse\b|\bmake\b|\bp\.\d|/1000\b")

root = Path(tempfile.mkdtemp(prefix="polypdf_convprog_"))
try:
    src = root / "R.pdf"
    d = fitz.open()
    for i in range(60):
        p = d.new_page()
        p.insert_text((72, 100), f"PAGEMARK{i + 1:03d} body text line", fontsize=12)
    d.save(str(src)); d.close()

    # ── A. 형식 차례·처음 고른 형식 ─────────────────────────────────
    from viewer import convert
    keys = [f.key for f in convert.FORMATS]
    chk(keys.index("docx_shape") < keys.index("docx_edit") and keys.index("hwpx_shape") < keys.index("hwpx_edit"),
        "A 형식마다 '모양 그대로' 가 '편집 가능' 위", str(keys))
    chk(keys.index("docx_word") == keys.index("docx_shape") + 1, "A 'Word (Microsoft Word 사용)' 은 'Word (모양 그대로)' 바로 아래", str(keys))
    from viewer.widgets.convert_dialog import ConvertDialog
    dlg0 = ConvertDialog(None, files=[str(src)], page_count=60)
    chk(dlg0.format_key() == "docx_shape", "A 변환 창의 처음 고른 형식 = Word (모양 그대로)", str(dlg0.format_key()))
    dlg0.deleteLater()

    # 변환 창: 쪽 범위를 정해 '변환' 을 누른 것과 같게(실제 _accept)
    want = {"range": None}

    def fake_exec(dlg):
        if want["range"]:
            dlg.rb_range.setChecked(True); dlg.ed_range.setText(want["range"])
        dlg._accept()
        return ConvertDialog.DialogCode.Accepted if dlg.result() else ConvertDialog.DialogCode.Rejected
    ConvertDialog.exec = fake_exec

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    mw.open_folder(root); spin(15)
    mw._load_main(HistoryItem(str(src), 0, "", "bookmark")); spin(10)

    # 진행 창 글을 20ms 마다 받아 적고, 조건이 되면 진행 창의 [취소] 단추를 누른다
    shot = {"labels": [], "cancel_when": None, "widths": []}

    def sample():
        for pd in mw.findChildren(QProgressDialog):
            if not pd.isVisible() and not pd.labelText():
                continue
            t = pd.labelText()
            if not shot["labels"] or shot["labels"][-1] != t:
                shot["labels"].append(t)
            lab = pd.findChild(QLabel)
            if lab is not None:
                fm = lab.fontMetrics()
                shot["widths"].append((t, tuple(fm.horizontalAdvance(x) for x in t.split("\n"))))
            cw = shot["cancel_when"]
            if cw and cw(t):
                shot["cancel_when"] = None
                btn = pd.findChild(QPushButton)
                if btn is not None:
                    btn.click()
    sampler = QTimer(); sampler.setInterval(20); sampler.timeout.connect(sample); sampler.start()

    def line2(t):
        """진행 글의 단계 줄(마지막 줄)에서 하트비트를 뗀다."""
        ln = t.split("\n")[-1]
        return re.sub(r"\s+\S{3}$", "", ln)

    # ── B. 전체 변환 → 진행 창 [취소] → 11-20 으로 다시 ─────────────────
    shot.update(labels=[], cancel_when=lambda t: "쪽 분석" in t or "parse" in t)
    want["range"] = None
    ok1 = mw.action_convert(fmt="docx_shape"); spin(5)
    chk(not ok1 and not (root / "R.docx").exists(), "B 준비 — 전체 변환을 진행 창 [취소] 로 멈추면 결과가 없다",
        str(shot["labels"][-3:]))
    shot.update(labels=[], cancel_when=None)
    want["range"] = "11-20"
    ok2 = mw.action_convert(fmt="docx_shape"); spin(5)
    out = root / "R.docx"
    marks = []
    if out.exists():
        from docx import Document
        marks = sorted(set(re.findall(r"PAGEMARK(\d{3})", "\n".join(p.text for p in Document(str(out)).paragraphs))))
    chk(ok2 and marks == ["%03d" % k for k in range(11, 21)], "B 취소 뒤 쪽 범위 11-20 변환 — 결과에 그 쪽만", str(marks))
    labs = [t for t in shot["labels"] if "\n" in t]
    chk(labs and all(t.split("\n")[0] == "R.pdf" for t in labs), "B 진행 글 1줄 = 파일 이름", str(shot["labels"][:3]))
    steps = [line2(t) for t in labs]
    chk(steps and all(STEP.match(s) for s in steps) and not any(RAW.search(t) for t in shot["labels"]),
        "B 진행 글 2줄 = '단계 k/n · 원본 p쪽' — parse·(…/1000) 같은 내부 값 없음",
        str([s for s in steps if not STEP.match(s)][:3] or shot["labels"][:3]))
    # 표본은 20ms 마다라 빠른 단계는 놓칠 수 있다 — 단계별 글 전체는 C(convert.run)가 본다
    chk(any(re.search(r" [ \d]+/10  ·", s) for s in steps) and not any(re.search(r"/(100|1000)\b", s) for s in steps),
        "B 범위 변환의 쪽 수는 범위(…/10)", str(steps[:6]))
    if out.exists():
        out.unlink()

    # ── C. 모든 형식의 진행 글·범위 ─────────────────────────────────
    for key in ("docx_edit", "hwpx_edit", "hwpx_shape", "pptx_shape", "txt", "png", "xlsx", "docx_shape"):
        seen = []
        try:
            res = convert.run(str(src), key, list(range(10, 20)), progress=lambda i, n, l: seen.append(l) or True)
        except convert.NothingToWrite:
            res = None
        bad = [l for l in seen if not STEP.match(l)]
        chk(seen and not bad, f"C {key} 진행 글이 모두 '단계 k/n · 원본 p쪽' 꼴", str(bad[:3]))
        chk(any("/10  ·  원본 11쪽" in l for l in seen), f"C {key} 범위의 쪽 수(/10)·원본 쪽 번호", str(seen[:3]))
        if res is not None and key in ("docx_edit", "txt", "hwpx_edit"):
            if key == "txt":
                txt = res.read_text(encoding="utf-8-sig")
            elif key == "docx_edit":
                from docx import Document
                txt = "\n".join(p.text for p in Document(str(res)).paragraphs)
            else:
                import zipfile
                with zipfile.ZipFile(str(res)) as z:
                    txt = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
            mk = sorted(set(re.findall(r"PAGEMARK(\d{3})", txt)))
            chk(mk == ["%03d" % k for k in range(11, 21)], f"C {key} 범위 변환 — 그 쪽만", str(mk))
        if res is not None:
            shutil.rmtree(res, ignore_errors=True) if Path(res).is_dir() else Path(res).unlink(missing_ok=True)

    # ── D. 실제 진행 창 글 폭 — 하트비트·쪽 수가 바뀌어도 같다 ───────────────
    def slow_job(fmt_label):
        def job(progress):
            for k in range(1, 61):
                progress(k, 60, fmt_label(k))
                time.sleep(0.03)
        return job
    for name, counts, lab in (
            ("변환 꼴(counts=False)", False,          # 수정 전 코드에는 step_text 가 없다 — 그때의 날 글로
             lambda k: "R.pdf\n" + (convert.step_text("parse", k, 60, k, 60) if hasattr(convert, "step_text")
                                    else "parse %d" % k)),
            ("다른 일 꼴((k/n) 붙임)", True, lambda k: "병합 중")):
        shot.update(labels=[], widths=[], cancel_when=None)
        import inspect                                   # 수정 전 코드에는 counts 가 없다
        kw = {"counts": counts} if "counts" in inspect.signature(mw._run_merge_job).parameters else {}
        mw._run_merge_job(slow_job(lab), "변환", **kw); spin(2)
        mine = [(t, w) for t, w in shot["widths"] if t.startswith("R.pdf" if not counts else "병합 중")]   # '준비 중…' 은 뺀다
        last = {w[-1] for _t, w in mine}
        chk(len({t for t, _w in mine}) >= 8 and len(last) == 1,
            f"D {name} — 진행 글 폭이 하트비트·쪽 수가 바뀌어도 같다", f"widths={sorted(last)[:6]} n={len(mine)}")

    # ── E. 같은 종류의 다른 일(261026-2 '다른 유사한 것도') — 실제 함수가 내는 글 ─────────────
    # E1 문서 비교 — 옛판·새판 읽기 k/n, 바뀐 곳 찾기
    b2 = root / "R2.pdf"
    shutil.copy2(str(src), str(b2))
    from viewer import compare as cmpmod
    seen = []
    cmpmod.compare(str(src), str(b2), lambda d, l: seen.append(l))
    lines2 = [l.split("\n")[-1] for l in seen if l]
    chk(seen and not any(RAW.search(l) or "diff" in l for l in seen)
        and any(l.startswith("옛판 읽기") and "/60" in l for l in lines2) and any(l.startswith("새판 읽기") for l in lines2)
        and "바뀐 곳 찾기" in lines2 and all(l.split("\n")[0] in ("R.pdf", "R2.pdf") for l in seen if "\n" in l),
        "E1 문서 비교 — '파일 / 옛판 읽기 k/n'·'바뀐 곳 찾기'(p.N·diff 없음)", str(seen[:2] + seen[-2:]))
    # E2 가림 — 자리 찾기 k/n, 가리기 k/m · 원본 p쪽, 저장
    from viewer import redact as rdmod
    rsrc = root / "D.pdf"                      # 글이 적은 쪽은 스캔 쪽으로 본다 — 쪽마다 글을 넉넉히
    d = fitz.open()
    for i in range(15):
        p = d.new_page()
        for k in range(12):
            p.insert_text((72, 80 + k * 16), f"Line {k} on page {i + 1} with enough words to count as text.", fontsize=11)
        if i == 11:
            p.insert_text((72, 400), "SECRETWORD here", fontsize=11)
    d.save(str(rsrc)); d.close()
    seen = []
    marks = rdmod.find_marks(str(rsrc), custom="SECRETWORD", tick=lambda i, n, l: seen.append(l))
    seen_apply = []
    if marks:
        rdmod.apply(str(rsrc), marks, tick=lambda i, n, l: seen_apply.append(l))
    chk(seen and all(STEP.match(l) or l.startswith("자리 찾기") for l in seen) and not any(RAW.search(l) for l in seen + seen_apply)
        and any("가리기 1/1  ·  원본 12쪽" in l for l in seen_apply),
        "E2 가림 — '자리 찾기 k/n'·'가리기 k/m · 원본 p쪽'(p.N 없음)", str(seen[:2] + seen_apply))
    # E3 텍스트 창 Word 저장
    from viewer import text_word as twmod
    seen = []
    doc_ = fitz.open(str(src))
    try:
        twmod.export_pages_to_docx(str(src), doc_, [11, 12], str(root / "tw.docx"), {},
                                   progress=lambda i, n, l: seen.append(l) or True)
    finally:
        doc_.close()
    chk(seen and not any(RAW.search(l) for l in seen) and "쪽 쓰기 1/2  ·  원본 12쪽" in seen,
        "E3 텍스트 창 Word 저장 — '쪽 쓰기 k/n · 원본 p쪽'", str(seen))
    # E4 PDF 압축 — 실제 처리기: 진행 글에 1000칸 척도가 없다
    from viewer import compress_controller as ccmod
    ccmod.CompressDialog.exec = lambda dlg: ccmod.CompressDialog.DialogCode.Accepted
    shot.update(labels=[], widths=[], cancel_when=None)
    mw.action_compress([str(src)]); spin(5)
    labs = [t for t in shot["labels"] if t != "준비 중…" and not t.startswith("준비 중…")]
    chk(labs and not any(RAW.search(t) or re.search(r"\(\s*[ \d]+/\d+\)", t) for t in labs)
        and all(t.split("\n")[0] == "R.pdf" for t in labs),
        "E4 PDF 압축 — 진행 글 '이름 / 압축 중'(파일마다 1000칸 숫자 없음)", str(shot["labels"][:4]))
    # E5 자동 태그 상태줄 — 두 바퀴를 합친 전체(…/200)가 아니라 바퀴마다 파일 k/n
    import viewer.app as appmod
    t1, t2 = appmod._autotag_text(30, 200), appmod._autotag_text(130, 200)
    chk("파일 읽기" in t1 and "30/100" in t1 and "태그 고르기" in t2 and "30/100" in t2,
        "E5 자동 태그 상태줄 — '파일 읽기 k/n'·'태그 고르기 k/n'", f"{t1} | {t2}")
    # E6 코드 전체 — 진행 글에 날 쪽 글을 넣지 않고, 파일마다 1000칸 척도를 쓰는 일은 counts=False
    vroot = Path(__file__).parent / "viewer"
    raw_hits, scale_hits = [], []
    for f in vroot.rglob("*.py"):
        if "_vendor" in f.parts:
            continue
        txt = f.read_text(encoding="utf-8")
        for ln_no, ln in enumerate(txt.splitlines(), 1):
            if re.search(r"\b(tick|progress|_tick|on_progress|emit)\(.*(f\"p\.\{|\"p\.%d|OCR p\.)", ln):
                raw_hits.append(f"{f.name}:{ln_no}")
        if re.search(r"_i \* 1000 \+", txt):
            for m in re.finditer(r"_run_merge_job\(([^\n]*)", txt):
                if "counts=False" not in m.group(1):
                    scale_hits.append(f"{f.name}: {m.group(0)[:60]}")
    chk(not raw_hits, "E6 진행 글에 날 쪽 글(p.N)을 넣는 곳이 없다", str(raw_hits))
    chk(not scale_hits, "E6 파일마다 1000칸 척도를 쓰는 일은 _run_merge_job(counts=False)", str(scale_hits))
    sampler.stop()

    # ── F. 진행 창 작업은 겹치지 않는다(응답성 SOT §4.3) — crash.log 1.0.0: 취소 뒤 다시 시작해 변환이 네 겹 ─────
    depth = {"now": 0, "max": 0}
    _orig_rmj = MainWindow._run_merge_job

    def spy_rmj(self, *a, **k):
        depth["now"] += 1
        try:
            return _orig_rmj(self, *a, **k)
        finally:
            depth["now"] -= 1
    from viewer import app as _appmod
    _orig_thread_start = _appmod._MergeThread.start

    def _count_start(self, *a):
        # 작업 스레드가 실제로 시작한 겹 수만 센다 — 거절된 호출은 스레드를 띄우지 않는다
        depth["max"] = max(depth["max"], depth["now"])
        return _orig_thread_start(self, *a)
    _appmod._MergeThread.start = _count_start
    MainWindow._run_merge_job = spy_rmj
    fst = {"clicked": False, "after": None, "status": ""}

    def slow_stop_job(progress):
        """Word·pdf2docx 처럼 취소를 받고도 잠깐 더 도는 일(Word 를 끝내고·자식을 기다린다)."""
        from viewer.twoup import MergeCancelled
        for k in range(200):
            if progress(k, 200, "SLOWJOB") is False:
                time.sleep(0.8)
                raise MergeCancelled()
            time.sleep(0.02)

    def f_poll():
        if fst["clicked"]:
            return
        for pd in mw.findChildren(QProgressDialog):
            if pd.isVisible() and "SLOWJOB" in pd.labelText():
                fst["clicked"] = True
                pd.findChild(QPushButton).click()                  # 사용자가 [취소]
                QTimer.singleShot(60, f_after)
                return

    def f_after():
        vis = any(pd.isVisible() for pd in mw.findChildren(QProgressDialog))
        modal = QApplication.activeModalWidget()
        lab = next((pd.labelText() for pd in mw.findChildren(QProgressDialog) if pd.isVisible()), "")
        fst["after"] = (vis, type(modal).__name__ if modal else None, lab)
        mw.act_export.trigger()                                    # 그 사이 또 '변환...'(창이 풀려 있었다면 사용자가 누를 수 있었다)
        QTimer.singleShot(30, lambda: fst.update(status=mw.status.currentMessage()))   # 안내는 부르는 쪽 글 다음 틱에
    mw._load_main(HistoryItem(str(src), 0, "", "bookmark")); spin(5)
    fp = QTimer(); fp.setInterval(20); fp.timeout.connect(f_poll); fp.start()
    want["range"] = None
    resF = mw._run_merge_job(slow_stop_job, "변환"); spin(5)
    fp.stop()
    chk(resF.get("cancelled"), "F 준비 — 취소가 작업에 닿았다", str(resF))
    chk(fst["after"] and fst["after"][0] and fst["after"][1] == "QProgressDialog" and "취소하는 중" in fst["after"][2],
        "F1 [취소] 뒤에도 진행 창이 '취소하는 중…' 으로 남아 창을 막는다", str(fst["after"]))
    spin(5)
    chk(depth["max"] == 1, "F2 작업이 도는 동안 또 시작한 변환은 그 안에서 돌지 않는다(겹침 없음)", f"max={depth['max']}")
    chk("앞 작업이 끝난 뒤에" in (fst["status"] or ""), "F2 거절하면 상태줄에 알린다", repr(fst["status"]))
    # F3 취소 없는 일(원본 제자리 쓰기·가상 프린터 받기 등)은 앞 작업 안에서도 거절하지 않는다 — 저장 길이 반쯤 끊기지 않게
    inner = {}

    def outer_job(progress):
        for k in range(30):
            progress(k, 30, "outer")
            time.sleep(0.02)
    QTimer.singleShot(150, lambda: inner.update(r=mw._run_merge_job(lambda pr: pr(1, 1, "inner"), "inner",
                                                                      cancellable=False)))
    mw._run_merge_job(outer_job, "outer"); spin(3)
    chk(inner.get("r", {}).get("ok") is True, "F3 cancellable=False 인 일은 앞 작업 중에도 돈다", str(inner))
    MainWindow._run_merge_job = _orig_rmj
    _appmod._MergeThread.start = _orig_thread_start
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
