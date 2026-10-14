# -*- coding: utf-8 -*-
"""261014-4: 잠깐 잡힌 파일의 이름 바꾸기·옮기기 (마스터 §4.7.14).

`test_file_rename_menu.py` 가 전체 검사에서 가끔 실패했다(불안정). 원인은 검사가 아니라 앱이었다 —
Windows 는 누가 파일을 열고 있으면(색인 자식 프로세스·같은 프로세스의 MuPDF) 이름을 못 바꾼다(`WinError 32`).
폴더를 열면 배경 색인이 파일을 하나씩 짧게 여는데, 그 순간 이름을 바꾸면 '변경 실패' 가 떴다. 부하가 클수록 잦다.
옮기기는 더 나빴다 — `shutil.move` 가 이름 바꾸기에 실패하면 **복사 후 지우기**로 넘어가, 지우기가 막혀 두 벌이 남았다.

다른 프로세스가 파일을 1초 잡고 있는 동안 실제 앱 경로로:
A. 파일 이름 변경(`_edit_file_node`)  B. 폴더 이름 변경(`_rename_folder`)  C. 파일 이동(`_transfer_files`, 두 벌 없음)
D. 끝내 안 풀리면 기다린 뒤 실패를 알린다(원본 그대로)
"""
import os, sys, tempfile, shutil, subprocess, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog, QLineEdit, QInputDialog
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=10, ms=20):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


def make_pdf(p, tag):
    d = fitz.open()
    for i in range(2):
        d.new_page().insert_text((72, 72), f"{tag} {i}")
    d.save(str(p)); d.close()


def hold(path, seconds):
    """다른 프로세스가 MuPDF 로 `seconds` 동안 열어 둔다(배경 색인 흉내). 열린 뒤에 돌아온다."""
    code = ("import fitz,sys,time;d=fitz.open(sys.argv[1]);print('open',flush=True);"
            "time.sleep(float(sys.argv[2]));d.close()")
    p = subprocess.Popen([sys.executable, "-c", code, str(path), str(seconds)], stdout=subprocess.PIPE, text=True)
    p.stdout.readline()
    return p


root = Path(tempfile.mkdtemp(prefix="polypdf_rnlock_"))
procs = []
try:
    warns = []
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: warns.append(str(a[2]) if len(a) > 2 else ""))
    QDialog.exec = lambda dlg: (dlg.findChild(QLineEdit).setText(dlg.findChild(QLineEdit).text() + "_새")
                                if dlg.findChild(QLineEdit) else None) or QDialog.DialogCode.Accepted
    fo = root / "fo"; (fo / "sub").mkdir(parents=True)
    for nm in ("A", "B"):
        make_pdf(fo / f"{nm}.pdf", nm)
    make_pdf(fo / "sub" / "C.pdf", "C")
    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1200, 800); mw.show(); app.processEvents()
    bt = mw.bookmark_tree
    mw.open_folder(fo); spin(20)
    end = time.monotonic() + 60
    while mw._index_workers and time.monotonic() < end:     # 이 검사의 잠금은 우리가 건다 — 앱 색인은 끝내 둔다
        spin(1, 50)

    # ── A. 파일 이름 변경 ──────────────────────────────────────────
    src = fo / "A.pdf"
    procs.append(hold(src, 1.0))
    node = bt._file_node_for_path(str(src))
    t0 = time.monotonic()
    bt._edit_file_node(node); spin(5)
    chk((fo / "A_새.pdf").exists() and not src.exists() and not warns,
        "A 잠깐 잡힌 파일도 이름이 바뀐다(풀릴 때까지 기다렸다 다시)", f"{warns[:1]} {time.monotonic() - t0:.1f}s")

    # ── B. 폴더 이름 변경 ──────────────────────────────────────────
    warns.clear()
    procs.append(hold(fo / "sub" / "C.pdf", 1.0))
    QInputDialog.getText = staticmethod(lambda *a, **k: ("sub_새", True))
    bt._rename_folder(fo / "sub"); spin(5)
    chk((fo / "sub_새" / "C.pdf").exists() and not (fo / "sub").exists() and not warns,
        "B 안의 파일이 잠깐 잡힌 폴더도 이름이 바뀐다", str(warns[:1]))

    # ── C. 파일 이동 — 두 벌이 남지 않는다 ───────────────────────────
    warns.clear()
    dst = root / "dst"; dst.mkdir()
    srcb = fo / "B.pdf"
    procs.append(hold(srcb, 1.0))
    bt._transfer_files([srcb], dst, True); spin(5)
    chk((dst / "B.pdf").exists() and not srcb.exists(),
        "C 잠깐 잡힌 파일도 옮겨진다 — 원본이 남지 않는다(종전: 복사 뒤 지우기 실패로 두 벌)",
        f"dst={(dst / 'B.pdf').exists()} src={srcb.exists()} {warns[:1]}")

    # ── D. 끝내 안 풀리면 ──────────────────────────────────────────
    warns.clear()
    srcd = fo / "A_새.pdf"
    procs.append(hold(srcd, 30))
    node = bt._file_node_for_path(str(srcd))
    t0 = time.monotonic()
    bt._edit_file_node(node); spin(5)
    took = time.monotonic() - t0
    chk(srcd.exists() and not (fo / "A_새_새.pdf").exists() and warns,
        "D 끝내 잡혀 있으면 실패를 알리고 원본은 그대로", f"{warns[:1]}")
    from viewer.pathutil import RENAME_WAIT_S
    chk(RENAME_WAIT_S - 0.5 <= took <= RENAME_WAIT_S + 5, "D 기다리는 시간은 상한까지만", f"{took:.1f}s")
finally:
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    time.sleep(0.3)
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
