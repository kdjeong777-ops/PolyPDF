# -*- coding: utf-8 -*-
"""261105-7: 책갈피창 '파일 복사'(편집 모드·우클릭·[복사])가 **배경**에서 복사한다 (응답성 SOT §4.4, 마스터 §4.7.14).

종전 `BookmarkTree._transfer_files` 의 복사 가지는 메인 스레드에서 `shutil.copy2` 를 불렀다 — 큰 PDF·네트워크 폴더·
백신 검사가 붙으면 그동안 창이 선다(261105-5 사진 복사·이동 작업 중 발견). 이동은 이미 `_rename_bg` 로 배경이었다.

A. 앱이 배경 실행기(`_file_op`)를 넣었으면 복사는 그 실행기 안(메인 아닌 스레드)에서 한다
B. 복사본이 생기고 원본은 그대로, 같은 이름이면 번호
C. 복사가 실패하면 반쯤 쓴 파일이 남지 않는다(임시 이름에 쓰고 다 쓰면 바꿔 이름)
"""
import os, sys, tempfile, shutil, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = Path(tempfile.mkdtemp(prefix="polypdf_copybg_"))
try:
    for nm in ("a.pdf", "b.pdf"):
        d = fitz.open(); d.new_page().insert_text((40, 80), nm); d.save(str(root / nm)); d.close()
    dst = root / "dst"; dst.mkdir()
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)

    from viewer.widgets.bookmark_tree import BookmarkTree
    bt = BookmarkTree(); bt.show(); app.processEvents()
    bt.load_folder(root); app.processEvents()

    main_id = threading.get_ident()
    seen = {"ops": 0, "copy_threads": []}
    real_copy2, real_copyfile = shutil.copy2, shutil.copyfile

    def spy_copy2(*a, **k):
        seen["copy_threads"].append(threading.get_ident())
        return real_copy2(*a, **k)

    def spy_copyfile(*a, **k):
        seen["copy_threads"].append(threading.get_ident())
        return real_copyfile(*a, **k)
    shutil.copy2, shutil.copyfile = spy_copy2, spy_copyfile

    def file_op(fn, label):                        # 앱의 `_file_op_bg` 흉내 — 배경 스레드에서 fn
        seen["ops"] += 1
        out = {}

        def run():
            try:
                fn()
            except Exception as e:                 # noqa: BLE001
                out["e"] = e
        t = threading.Thread(target=run); t.start(); t.join()
        return out.get("e")
    bt._file_op = file_op

    # ── A·B ──
    bt._transfer_files([root / "a.pdf"], dst, False); app.processEvents()
    bt._transfer_files([root / "a.pdf"], dst, False); app.processEvents()
    chk(seen["ops"] >= 2 and seen["copy_threads"] and all(t != main_id for t in seen["copy_threads"]),
        "A 복사는 배경 실행기 안에서(메인 스레드에서 copy 를 부르지 않는다)",
        f"ops={seen['ops']} main_calls={sum(t == main_id for t in seen['copy_threads'])}")
    names = sorted(p.name for p in dst.iterdir())
    chk((root / "a.pdf").exists() and len(names) == 2 and "a.pdf" in names,
        "B 복사본이 생기고 원본 그대로, 같은 이름이면 번호", str(names))

    # ── C ──
    def boom(src, dst_, *a, **k):
        Path(dst_).write_bytes(b"half")
        raise OSError("디스크 가득 흉내")
    shutil.copy2 = shutil.copyfile = boom
    before = set(p.name for p in dst.iterdir())
    bt._transfer_files([root / "b.pdf"], dst, False); app.processEvents()
    after = set(p.name for p in dst.iterdir())
    chk(after == before, "C 복사 실패면 반쯤 쓴 파일이 남지 않는다", str(after - before))
    shutil.copy2, shutil.copyfile = real_copy2, real_copyfile
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
