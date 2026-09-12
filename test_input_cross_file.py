# -*- coding: utf-8 -*-
"""260912-5: 파일 경계를 넘기 전에 묻는다 (입력 장치 SOT §2.4).

사용자 지시: "PDF 마지막 페이지에서 다음 PDF 로 넘어갈 때 다음 PDF 의 파일명(확장자
제외)을 보여 주고 볼 건지 물어보는 창을 띄워. 첫 페이지에서 이전 PDF 로 갈 때도,
썸네일로 넘어갈 때도 마찬가지. **다만 책갈피창에서 항목을 고를 때는 적용하지 않는다.**"

가르는 자리는 하나다 — 경계 이동은 `_on_file_boundary()` 로 모이고, 책갈피·검색은
`_on_bookmark_activated()` 로 바로 간다. 그래서 이 검사는 **두 길이 갈라져 있는지**를
본다: 경계로 가면 묻고, 책갈피로 가면 묻지 않는다.
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

import fitz
from PyQt6.QtWidgets import QApplication, QDialogButtonBox
from viewer.widgets.file_cross_dialog import FileCrossDialog

app = QApplication.instance() or QApplication(sys.argv)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = tempfile.mkdtemp(prefix="polypdf_cross_")
try:
    # 쪽마다 글이 다른 3쪽짜리 PDF — 첫 쪽과 마지막 쪽을 가려낼 수 있게
    src = os.path.join(root, "다음 보고서.pdf")
    doc = fitz.open()
    for i in range(3):
        pg = doc.new_page(width=400, height=560)
        pg.insert_text((60, 80), "page %d" % (i + 1), fontsize=24)
    doc.save(src)
    doc.close()

    # ── ① 창이 뜨고, 확장자를 뺀 이름을 보여 준다 ─────────────────────
    from PyQt6.QtWidgets import QLabel
    dlg = FileCrossDialog(None, path=src, forward=True)
    labels = [w.text() for w in dlg.findChildren(QLabel)]
    chk("다음 보고서" in labels, "① 확장자를 뺀 파일명을 보여 준다", str(labels))
    chk(not any(".pdf" in (t or "") for t in labels),
        "① 확장자는 보여 주지 않는다", str(labels))
    chk(any("볼까요" in (t or "") for t in labels), "① 볼 건지 묻는다", str(labels))

    # ── ② 미리보기 — 다음이면 첫 쪽, 이전이면 마지막 쪽 ───────────────
    shots = [w for w in dlg.findChildren(QLabel) if w.pixmap() and not w.pixmap().isNull()]
    chk(len(shots) == 1, "② 미리보기 그림이 하나 있다", "%d개" % len(shots))
    caps = [w.text() for w in dlg.findChildren(QLabel)]
    chk("첫 쪽" in caps, "② 다음 파일이면 **첫 쪽**을 보여 준다", str(caps))

    back = FileCrossDialog(None, path=src, forward=False)
    bcaps = [w.text() for w in back.findChildren(QLabel)]
    chk("마지막 쪽" in bcaps, "② 이전 파일이면 **마지막 쪽**을 보여 준다", str(bcaps))
    chk(any("이전" in (t or "") for t in bcaps), "② 방향을 밝힌다", str(bcaps))

    #   글자만 보면 속는다 — 그린 **그림 자체**가 다른지 본다.
    #   표본은 쪽마다 글이 다르므로 첫 쪽과 마지막 쪽은 반드시 다르게 나와야 한다.
    bshots = [w for w in back.findChildren(QLabel) if w.pixmap() and not w.pixmap().isNull()]
    chk(len(bshots) == 1, "② 뒤로 갈 때도 그림이 하나", "%d개" % len(bshots))
    if shots and bshots:
        a = shots[0].pixmap().toImage()
        b = bshots[0].pixmap().toImage()
        chk(a != b, "② 그린 쪽이 실제로 다르다(첫 쪽 ≠ 마지막 쪽)")

    # ── ③ 기본 단추는 [예], Esc 는 아니오 ─────────────────────────────
    chk(dlg.btn_yes.text() == "예" and dlg.btn_no.text() == "아니오",
        "③ 단추는 예/아니오")
    chk(dlg.btn_yes.isDefault(), "③ 기본 단추는 [예] — 누르던 흐름을 잇는다")
    box = dlg.findChild(QDialogButtonBox)
    chk(box is not None and not any(
        b.text() in ("다시 묻지 않기",) for b in box.buttons()),
        "③ '다시 묻지 않기' 는 두지 않는다(사용자 결정)")

    # ── ④ 그림을 못 그려도 물음은 뜬다 ────────────────────────────────
    bad = os.path.join(root, "깨진 파일.pdf")
    open(bad, "wb").write(b"not a pdf")
    d2 = FileCrossDialog(None, path=bad, forward=True)
    t2 = [w.text() for w in d2.findChildren(QLabel)]
    chk("깨진 파일" in t2, "④ 미리보기가 실패해도 파일명은 뜬다", str(t2))
    shots2 = [w for w in d2.findChildren(QLabel) if w.pixmap() and not w.pixmap().isNull()]
    chk(not shots2, "④ 그때는 그림 없이 뜬다", "%d개" % len(shots2))

    # ── ⑤ ★ 묻는 길과 묻지 않는 길이 갈라져 있다 ─────────────────────
    import inspect
    from viewer import app as appmod
    src_boundary = inspect.getsource(appmod.MainWindow._on_file_boundary)
    chk("_ask_cross_file" in src_boundary,
        "⑤ 경계 이동(`_on_file_boundary`)은 묻는다")
    src_bm = inspect.getsource(appmod.MainWindow._on_bookmark_activated)
    chk("_ask_cross_file" not in src_bm,
        "⑤ 책갈피 선택(`_on_bookmark_activated`)은 **묻지 않는다**")
    chk(hasattr(appmod.MainWindow, "_ask_cross_file"), "⑤ 묻는 함수가 한 곳에 있다")

    # 썸네일도 같은 길을 쓴다 — 따로 물음을 달지 않아도 함께 적용된다
    from viewer.widgets import thumbs_list as tl
    chk("fileBoundaryRequested" in inspect.getsource(tl),
        "⑤ 썸네일은 같은 신호(`fileBoundaryRequested`)를 쓴다")
    wired = inspect.getsource(appmod.MainWindow._build_left_panel) \
        if hasattr(appmod.MainWindow, "_build_left_panel") else ""
    chk("_ask_cross_file" not in wired,
        "⑤ 썸네일 쪽에 물음을 따로 달지 않는다 — 한 곳에서 걸린다")
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("=== ALL PASS ===" if not fails else "=== FAILURE (%d) ===" % len(fails))
for f in fails:
    print(" -", f)
sys.stdout.flush()
os._exit(1 if fails else 0)
