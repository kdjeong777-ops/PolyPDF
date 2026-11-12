# -*- coding: utf-8 -*-
"""261112-13: `ocr_batch.cleanup(tmp)` 는 **OCR 묶음이 만든 전용 임시 폴더**만 지운다 (텍스트 창 SOT §5.5 '임시 폴더').

보고(261112-12 꾸밈 세션): 종전에는 임시 PDF 의 부모 폴더를 묻지 않고 `rmtree` 해, 다른 경로가 들어가면 그 폴더 전체가
지워졌다 — 검사 초안이 실제로 검사 폴더를 날렸다. 앱은 늘 전용 폴더를 넘겨 지금은 안전하지만, 지우는 쪽이 스스로 지킨다.
  A  전용 폴더가 아닌 곳(이 검사가 만든 폴더)의 파일을 넘기면 — 그 파일·옆 파일·폴더 모두 그대로
  B  이름이 `polypdf_ocrb_` 여도 시스템 임시 폴더 **바로 아래가 아니면** 그대로
  C  `run_file` 처럼 `mkdtemp(prefix=TEMP_PREFIX)` 로 만든 전용 폴더는 통째로 지운다(종전과 같다)
  D  빈 값·없는 경로는 조용히 넘어간다
검사는 자기가 만든 임시 폴더 안에서만 지우기를 부른다(시스템 임시 폴더 자체는 넘기지 않는다).
"""
import os, sys, shutil, tempfile
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from viewer import ocr_batch

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


ROOT = Path(tempfile.mkdtemp(prefix="ocrb_cleanup_test_"))
try:
    # ── A. 전용 폴더가 아닌 곳 ───────────────────────────────────
    a_dir = ROOT / "work"
    a_dir.mkdir()
    (a_dir / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    (a_dir / "keep.txt").write_text("남아야 한다", encoding="utf-8")
    ocr_batch.cleanup(str(a_dir / "doc.pdf"))
    chk(a_dir.is_dir() and (a_dir / "keep.txt").is_file(), "A 전용 폴더가 아니면 폴더·옆 파일이 남는다",
        str(sorted(os.listdir(a_dir)) if a_dir.is_dir() else "폴더가 지워짐"))
    chk((a_dir / "doc.pdf").is_file(), "A 넘긴 파일도 지우지 않는다(원본·사용자 파일일 수 있다)")

    # ── B. 접두어는 맞지만 시스템 임시 폴더 바로 아래가 아님 ──────────
    b_dir = ROOT / (ocr_batch.TEMP_PREFIX + "nested")
    b_dir.mkdir()
    (b_dir / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    (b_dir / "other.txt").write_text("x", encoding="utf-8")
    ocr_batch.cleanup(str(b_dir / "doc.pdf"))
    chk(b_dir.is_dir() and (b_dir / "other.txt").is_file(), "B 접두어만 같고 임시 폴더 바로 아래가 아니면 그대로")

    # ── C. 전용 폴더(run_file 과 같은 길) ─────────────────────────
    c_dir = Path(tempfile.mkdtemp(prefix=ocr_batch.TEMP_PREFIX))
    try:
        (c_dir / "doc.pdf").write_bytes(b"%PDF-1.4\n")
        ocr_batch.cleanup(str(c_dir / "doc.pdf"))
        chk(not c_dir.exists(), "C 전용 임시 폴더는 통째로 지운다")
        # 원본에 놓은 뒤(임시 PDF 가 이미 옮겨져 없음)에도 폴더는 지운다
        c2 = Path(tempfile.mkdtemp(prefix=ocr_batch.TEMP_PREFIX))
        ocr_batch.cleanup(str(c2 / "moved_away.pdf"))
        chk(not c2.exists(), "C 임시 PDF 가 옮겨져 없어도 빈 전용 폴더는 지운다")
    finally:
        shutil.rmtree(c_dir, ignore_errors=True)

    # ── D. 빈 값·없는 경로 ───────────────────────────────────────
    try:
        ocr_batch.cleanup("")
        ocr_batch.cleanup(None)
        ocr_batch.cleanup(str(ROOT / "nope" / "x.pdf"))
        ok = True
    except Exception as e:                      # noqa: BLE001
        ok = False
        print(e)
    chk(ok and ROOT.is_dir(), "D 빈 값·없는 경로는 조용히 넘어가고 아무것도 지우지 않는다")
finally:
    shutil.rmtree(ROOT, ignore_errors=True)

if fails:
    print("FAIL", len(fails), fails)
    sys.exit(1)
print("ALL PASS")
