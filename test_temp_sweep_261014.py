# -*- coding: utf-8 -*-
"""261014-3: 임시 폴더가 쌓이지 않게 (마스터 §14.8.1).

사용자 임시 폴더에 PolyPDF 가 남긴 폴더가 18,869개·16.5GB 쌓여 있었다. 앱 쪽 원인 —
`twoup.build_twoup`(병합·다단)이 표지·목차 임시 폴더를 지우지 않았다(4,714개), 발표 알림음이 실행마다 새 폴더,
`os._exit` 종료라 `atexit`·`TemporaryDirectory` 정리가 돌지 않는다. 검사 쪽 원인 — 검사가 `os._exit` 로 정리 전에 끝난다.

A. build_twoup 은 끝나면 제 임시 폴더를 지운다(실제 함수로 병합)
B. temp_sweep 은 앱 접두어의 **낡은** 폴더만 지운다(새것·다른 이름·파일은 그대로)
C. 앱 시작 뒤 배경 정리가 걸린다(실제 MainWindow)
D. 알림음은 고정 폴더 하나를 다시 쓴다
E. 전체 검사 실행기는 검사마다 제 TEMP 를 주고 지운다
"""
import os, sys, tempfile, shutil, time, inspect
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


box = Path(tempfile.mkdtemp(prefix="polypdf_tsweep_"))
_old_tempdir = tempfile.tempdir
try:
    # ── A. build_twoup ────────────────────────────────────────────
    work = box / "a"; work.mkdir()
    tempfile.tempdir = str(work)                      # 이 검사만의 임시 폴더에서 센다
    src = box / "src.pdf"
    d = fitz.open()
    for i in range(4):
        d.new_page().insert_text((72, 72), f"P{i + 1}")
    d.save(str(src)); d.close()
    from viewer import twoup
    out = box / "out.pdf"
    twoup.build_twoup([{"type": "pdf", "path": str(src), "name": "src"}],
                      {"nup": 2}, str(out))
    left = [p.name for p in work.iterdir() if p.name.startswith("polypdf_2up_")]
    chk(out.exists(), "A 준비 — 병합 결과가 생겼다")
    chk(not left, "A build_twoup 이 끝나면 임시 폴더가 남지 않는다", str(left))
    # 실패해도 지운다
    try:
        twoup.build_twoup([{"type": "pdf", "path": str(box / "없음.pdf"), "name": "x"}], {}, str(box / "o2.pdf"))
    except Exception:
        pass
    left = [p.name for p in work.iterdir() if p.name.startswith("polypdf_2up_")]
    chk(not left, "A 실패한 병합도 임시 폴더를 남기지 않는다", str(left))
    tempfile.tempdir = _old_tempdir

    # ── B. temp_sweep ─────────────────────────────────────────────
    from viewer import temp_sweep
    tb = box / "b"; tb.mkdir()
    old = time.time() - 3 * 86400
    for name in ("polypdf_2up_old", "polypdf_pages_old", "polypdf_2up_new", "polypdf_draw_old", "other_old"):
        (tb / name).mkdir(); (tb / name / "f.pdf").write_bytes(b"x")
        if name.endswith("_old"):
            os.utime(tb / name, (old, old))
    (tb / "polypdf_2up_file").write_bytes(b"x"); os.utime(tb / "polypdf_2up_file", (old, old))
    n = temp_sweep.sweep(str(tb))
    names = sorted(p.name for p in tb.iterdir())
    chk(n == 2 and names == ["other_old", "polypdf_2up_file", "polypdf_2up_new", "polypdf_draw_old"],
        "B 앱 접두어의 낡은 폴더만 지운다(새 폴더·검사 접두어·다른 이름·파일은 그대로)", "%d %s" % (n, names))

    # ── C. 앱 시작 뒤 배경 정리 ────────────────────────────────────
    from PyQt6.QtCore import QStandardPaths
    QStandardPaths.setTestModeEnabled(True)
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtTest import QTest
    app = QApplication.instance() or QApplication(sys.argv[:1])
    called = []
    temp_sweep.sweep_in_background = lambda: called.append(1)
    from viewer.app import MainWindow
    mw = MainWindow(); mw.show()
    t_end = time.monotonic() + 12
    while not called and time.monotonic() < t_end:
        app.processEvents(); QTest.qWait(100)
    chk(called == [1], "C 앱 시작 뒤 배경 정리가 한 번 걸린다", str(called))

    # ── D. 알림음 고정 폴더 ────────────────────────────────────────
    from viewer.widgets import pres_timer
    td = box / "d"; td.mkdir()
    tempfile.tempdir = str(td)
    cls = next(c for c in vars(pres_timer).values() if isinstance(c, type) and hasattr(c, "_gen_wav"))
    a, b = cls(), cls()
    pa, pb = a._gen_wav("beep_mid"), b._gen_wav("beep_mid")
    tempfile.tempdir = _old_tempdir
    dirs = sorted(p.name for p in td.iterdir())
    chk(pa and pb and dirs == ["polypdf_tone"], "D 알림음은 실행마다 새 폴더가 아니라 고정 폴더 하나", str(dirs))

    # ── E. 검사 실행기 ─────────────────────────────────────────────
    sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
    import release_test
    src_checks = inspect.getsource(release_test.checks)
    chk("TMPDIR=" in src_checks and "TEMP=" in src_checks and "rmtree(ttmp" in src_checks,
        "E 전체 검사는 검사마다 제 TEMP 를 주고 끝나면 지운다")
finally:
    tempfile.tempdir = _old_tempdir
    try:
        from viewer import twoup as _tw
        _tw.clear_preview_cache()        # 병합이 연 원본 핸들(미리보기 캐시)을 놓아야 지워진다 — 앱에서는 창을 닫을 때
    except Exception:
        pass
    shutil.rmtree(box, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
