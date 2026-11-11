# -*- coding: utf-8 -*-
"""새 파일을 만드는 저장·사본 명령에도 해시태그가 따라간다 (태그 SOT §6.1-⑥, 책갈피창·저장 SOT §4.7.14, 261111-10).

사용자 결정(2026-11-11) '①~⑥ 모두 따라감' — 다른 이름으로 저장·잠겨 새 이름으로 저장·평탄화·용량 줄인·개인정보 지운·사진 공유용 사본.
실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다).
A. `_finalize_save` 가 원본과 다른 경로를 돌려주면(다른 이름으로·새 이름으로) 새 파일에 태그 — 같은 경로(덮어쓰기)면 아무것도 안 한다
B. 용량 줄인 사본(`action_compress` 실제 길, 압축 엔진만 가짜) · 사진 평탄화·공유용 사본 끝 처리기
C. 정적 — 새 파일을 만드는 저장·사본 명령의 끝 함수가 모두 `_carry_tags` 를 부른다(새 명령이 빠지지 않게)
"""
import os, sys, tempfile, shutil, time, ast, re
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_carry_save_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "저장 사본 태그", echo=False)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pdf(p):
    d = fitz.open(); d.new_page(); d.save(p); d.close()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tagsave_"))
try:
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.show(); app.processEvents()
    st = mw.bookmark_tree._tags
    src = str(tmp / "a.pdf"); pdf(src)
    st.set(src, ["가족"]); st.set_auto(src, ["보고서"])

    # A _finalize_save
    newp = str(tmp / "a (2).pdf"); pdf(newp)
    real_place = mw._finalize_save_place
    mw._finalize_save_place = lambda s, produced, shift=None: newp
    mw._file_op_bg = lambda fn, label="": None
    got = mw._finalize_save(src, str(tmp / "produced.pdf"))
    chk(got == newp and st.get_manual(newp) == ["가족"] and st.get_auto(newp) == ["보고서"],
        "A 다른 이름으로·새 이름으로 저장 — 새 파일에 태그", str(st.get(newp)))
    other = str(tmp / "b.pdf"); pdf(other)
    mw._finalize_save_place = lambda s, produced, shift=None: s
    before = st.record(src)
    mw._finalize_save(src, str(tmp / "produced.pdf"))
    chk(st.record(src) == before, "A 덮어쓰기(같은 경로)면 기록을 건드리지 않는다")
    mw._finalize_save_place = real_place

    # B 용량 줄인 사본 — 실제 action_compress, 엔진만 가짜
    from viewer import pdf_compress
    from viewer import compress_controller as CD
    real_run = pdf_compress.run
    def fake_run(s, level, tick):
        out = str(Path(s).with_name(Path(s).stem + "_small.pdf")); shutil.copy2(s, out); return out, 100, 50
    pdf_compress.run = fake_run
    CD.CompressDialog.exec = lambda self_: CD.CompressDialog.DialogCode.Accepted
    mw.action_compress([src])
    pdf_compress.run = real_run
    small = str(tmp / "a_small.pdf")
    chk(os.path.exists(small) and st.get_manual(small) == ["가족"], "B 용량 줄인 사본에 태그", str(st.get(small)))
    ph, ph_flat, ph_share = str(tmp / "p.jpg"), str(tmp / "p_flat.jpg"), str(tmp / "share" / "p.jpg")
    for p in (ph, ph_flat):
        Path(p).write_bytes(b"x")
    Path(ph_share).parent.mkdir(); Path(ph_share).write_bytes(b"x")
    st.set(ph, ["가족"]); st.set_auto_part(ph, "meta", ["2026-11-05", "고양시"]); st.set_auto_part(ph, "kind", ["영수증"])
    mw._photo_flattened(ph, ph_flat, "")
    chk(st.get_manual(ph_flat) == ["가족"] and st.get_auto(ph_flat) == ["영수증"], "B 사진 평탄화 사본에 태그(기본 정보는 빼고 — 261111-26)", str(st.get(ph_flat)))
    mw._photo_shared([(ph, ph_share)], [])
    chk(st.get_manual(ph_share) == ["가족"] and st.get_auto(ph_share) == ["영수증"], "B 공유용·정보 지운 사본에도 태그(사용자 결정 '모두 따라감', 기본 정보는 빼고)", str(st.get(ph_share)))
    chk(mw._carry_tags([(src, src)]) == 0, "B 같은 경로는 건너뛴다")
    mw.close()

    # C 정적 — 끝 함수마다 _carry_tags
    root = Path(__file__).resolve().parent / "viewer"
    want = {"app.py": ["_finalize_save", "_on_files_copied"], "edit_controller.py": ["_apply_drawings_to_pdf"],
            "compress_controller.py": ["action_compress"], "redact_controller.py": ["action_redact"],
            "photo_controller.py": ["_photo_flattened", "_photo_shared"]}
    miss = []
    for fn, names in want.items():
        src_txt = (root / fn).read_text(encoding="utf-8")
        tree = ast.parse(src_txt)
        found = {n.name: ast.get_source_segment(src_txt, n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for nm in names:
            if nm not in found or "_carry_tags(" not in found[nm]:
                miss.append("%s:%s" % (fn, nm))
    chk(not miss, "C 새 파일을 만드는 저장·사본 끝 함수가 모두 _carry_tags 를 부른다", str(miss))
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
