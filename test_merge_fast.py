# -*- coding: utf-8 -*-
"""260915-4: PDF 병합은 그대로 합쳐 빠르게 저장하고 쪽수를 확인한다 (마스터 §4.8.4).

사용자 지시: "pdf 병합시, pdf 파일들을 순서대로 그냥 합치고, 검사하는 것이 빠를 것 같은데 검토해."
실측(샘플 8개·139MB): 합치기 0.7~1.4초, 종전 정리 저장(garbage=4, deflate) 15.1초 / 빠른 저장 0.2초(+11%),
책갈피 없는 원본 자동 책갈피 139쪽 46초. 결정: 빠른 저장 기본 + '용량 줄이기' 선택, 자동 생성 기본 끔, 쪽수 확인.
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = Path(tempfile.mkdtemp(prefix="polypdf_merge_fast_"))
try:
    # 같은 그림을 담은 원본 셋 — 정리 저장이 중복을 합칠 거리가 있게
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 400))
    for y in range(0, 400, 7):
        for x in range(0, 400, 5):
            pix.set_pixel(x, y, ((x * 7) % 256, (y * 3) % 256, (x + y) % 256))
    img = pix.tobytes("png")
    srcs = []
    for k, n in enumerate((3, 5, 2)):
        p = root / f"S{k}.pdf"
        d = fitz.open()
        for i in range(n):
            pg = d.new_page()
            pg.insert_image(fitz.Rect(50, 50, 350, 350), stream=img)
            pg.insert_text((72, 400), f"S{k} page {i + 1}")
        if k != 1:
            d.set_toc([[1, f"S{k} 처음", 1], [2, f"S{k} 둘째", 2]])
        d.save(str(p)); d.close()
        srcs.append(p)
    items = [{"type": "pdf", "path": str(p), "name": p.stem} for p in srcs]

    from viewer.app import MainWindow
    mw = MainWindow()
    calls = []
    mw._gen_source_bookmarks = lambda path, doc=None: (calls.append(path), [])[1]
    labels = []
    prog = lambda d, t, lbl: (labels.append(lbl), True)[1]

    fast = root / "fast.pdf"
    mw._do_normal_merge(items, str(fast), False, prog)
    d = fitz.open(str(fast))
    n, toc = d.page_count, d.get_toc()
    d.close()
    chk(n == 10, "빠른 저장 — 쪽수가 합과 같다", str(n))
    chk([t[1] for t in toc] == ["S0 처음", "S0 둘째", "S2 처음", "S2 둘째"] and toc[2][2] == 9,
        "원본 책갈피는 쪽 번호를 옮겨 그대로 붙인다", str(toc))
    chk(calls == [], "자동 생성을 끄면 책갈피 없는 원본도 분석하지 않는다(병합이 기다리지 않는다)")
    chk(labels and labels[-1] == "저장 중…", "진행창 — 빠른 저장 문구", str(labels[-1:]))

    small = root / "compact.pdf"
    labels.clear()
    mw._do_normal_merge(items, str(small), False, prog, compact=True)
    chk(os.path.getsize(small) < os.path.getsize(fast),
        "용량 줄이기 — 같은 그림을 합쳐 더 작다", "%d vs %d" % (os.path.getsize(small), os.path.getsize(fast)))
    chk("용량 줄여" in labels[-1], "진행창 — 오래 걸릴 수 있다고 알린다", labels[-1])

    mw._do_normal_merge(items, str(root / "auto.pdf"), True, prog)
    chk(calls == [str(srcs[1])], "자동 생성을 켜면 책갈피 없는 원본만 분석한다(종전과 같다)", str(calls))

    real_open = fitz.open

    class _Short:
        page_count = 9
        def close(self): pass

    def fake_open(*a, **k):
        if a and str(a[0]).endswith("check.pdf"):
            return _Short()
        return real_open(*a, **k)
    fitz.open = fake_open
    try:
        err = ""
        try:
            mw._do_normal_merge(items, str(root / "check.pdf"), False, prog)
        except RuntimeError as e:
            err = str(e)
    finally:
        fitz.open = real_open
    chk("쪽수가 맞지 않습니다" in err and "10쪽" in err, "검사 — 다시 연 쪽수가 다르면 오류로 알린다", err)

    from viewer.widgets.merge_dialog import MergeFilesDialog
    dlg = MergeFilesDialog([], [], [], None)
    chk(not dlg.auto_build() and not dlg.compact(), "병합창 기본값 — 자동 생성 끔·용량 줄이기 끔")
    dlg.chk_compact.setChecked(True)
    chk(dlg.compact(), "용량 줄이기를 켤 수 있다")
    dlg.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
