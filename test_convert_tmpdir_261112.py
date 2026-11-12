# -*- coding: utf-8 -*-
"""261112-14: 형식 변환이 끝나며 지우는 임시 폴더는 **전용 폴더일 때만** (형식 변환 SOT §4.1 '임시 폴더 지우기', 마스터 §14.8.1).

보고(261112-13): `convert/proc.py` 는 `src != ps.path` 면 `Path(src).parent` 를, `word_com.py` 는 `Path(layered).parent` 를
묻지 않고 `rmtree` 했다. str·Path 비교라 원본 경로가 다른 꼴(Path·대소문자·슬래시·짧은 이름)로 오면 **원본 폴더가 통째로** 지워진다.
실제 처리기(`proc.convert_docx`·`word_com.convert_word`)를 부르고, 무거운 것(자식 프로세스·Word COM)만 가짜로 바꾼다.
  A  Word(모양 그대로): 사본 자리에 원본이 다른 꼴로 오면 — 원본 폴더·원본·옆 파일 모두 그대로
  B  Microsoft Word 로: 같은 상황에서 원본 폴더 그대로
  C  진짜 전용 사본 폴더(`mkdtemp(prefix="polypdf_conv_")`)는 끝나면 지운다(두 길 모두)
  D  공용 판정 `temp_sweep.is_own_temp_dir` — 접두어만 같고 임시 폴더 바로 아래가 아니면 아님
검사는 자기가 만든 임시 폴더 안의 원본만 넘긴다. **수정 전 코드로 A·B 실패.**
"""
import os, sys, shutil, tempfile, types
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from viewer.convert import proc, word_com, layout
from viewer import index_proc

PREFIX = "polypdf_conv_"
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def short_name(p: str) -> str:
    """Windows 짧은 이름(8.3) — 볼륨이 끄고 있으면 그대로."""
    if os.name != "nt":
        return p
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024)
    return buf.value if 0 < n < 1024 else p


def other_forms(orig: Path):
    s = str(orig)
    out = [("Path", Path(s)), ("슬래시", s.replace("\\", "/")), ("대문자", s.upper() if os.name == "nt" else s)]
    sn = short_name(s)
    if sn != s:
        out.append(("짧은 이름", sn))
    return out


# ── 가짜: 자식 프로세스(pdf2docx)·머리말 찾기·Word COM ──────────────
def fake_run_job(job, on_progress, cancelled, **kw):
    Path(job["dst"]).write_bytes(b"PK")
    return True


index_proc.run_job = fake_run_job
layout.page_edges = lambda ps, pg: []


class _Doc:
    def SaveAs2(self, dst, FileFormat=None):
        Path(dst).write_bytes(b"PK")

    def Close(self, *_a):
        pass


class _App:
    Visible = False
    DisplayAlerts = 0

    class Documents:
        @staticmethod
        def Open(*_a, **_k):
            return _Doc()

    def Quit(self):
        pass


sys.modules["pythoncom"] = types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
w32 = types.ModuleType("win32com")
w32.client = types.SimpleNamespace(DispatchEx=lambda name: _App())
sys.modules["win32com"] = w32
sys.modules["win32com.client"] = w32.client
word_com._pids = lambda name: set()
word_com._kill = lambda pids: None
word_com._press_ok = lambda pids: 0


def run(kind, orig: Path, copy_value, dst: Path):
    """실제 처리기를 부른다 — `_layered_copy` 만 정해진 값을 돌려주게."""
    proc._layered_copy = lambda ps, pages, tick: copy_value
    ps = types.SimpleNamespace(path=str(orig), page_count=1)
    tick = lambda *a, **k: None
    if kind == "docx":
        proc.convert_docx(ps, [0], dst, tick)
    else:
        word_com.convert_word(ps, [0], dst, tick)


ROOT = Path(tempfile.mkdtemp(prefix="convtmp_test_"))
try:
    for kind, label in (("docx", "A Word(모양 그대로)"), ("word", "B Microsoft Word 로")):
        orig_dir = ROOT / f"{kind} 원본 폴더 long name"
        orig_dir.mkdir()
        orig = orig_dir / "원본 문서.pdf"
        orig.write_bytes(b"%PDF-1.4\n%%EOF\n")
        (orig_dir / "keep.txt").write_text("남아야 한다", encoding="utf-8")
        out_dir = ROOT / f"{kind}_out"
        out_dir.mkdir()
        for fname, form in other_forms(orig):
            try:
                run(kind, orig, form, out_dir / f"{fname}.docx")
                err = ""
            except Exception as e:                  # noqa: BLE001
                err = repr(e)
            chk(orig_dir.is_dir() and orig.is_file() and (orig_dir / "keep.txt").is_file(),
                f"{label}: 원본이 다른 꼴({fname})로 와도 원본 폴더·원본·옆 파일 그대로",
                (str(sorted(os.listdir(orig_dir))) if orig_dir.is_dir() else "원본 폴더가 지워짐") + (" " + err if err else ""))
            if not orig_dir.is_dir():
                break

        # ── C. 진짜 전용 사본 폴더는 지운다 ──
        own = Path(tempfile.mkdtemp(prefix=PREFIX))
        try:
            copy = own / "layered.pdf"
            copy.write_bytes(b"%PDF-1.4\n%%EOF\n")
            try:
                run(kind, orig, str(copy), out_dir / "own.docx")
            except Exception as e:                  # noqa: BLE001
                print(" ", e)
            chk(not own.exists(), f"C {label}: 전용 사본 폴더는 끝나면 지운다")
            chk(orig.is_file(), f"C {label}: 원본은 그대로")
        finally:
            shutil.rmtree(own, ignore_errors=True)

    # ── D. 공용 판정 ──
    try:
        from viewer import temp_sweep as ts
        nested = ROOT / (PREFIX + "nested")
        nested.mkdir()
        mine = Path(tempfile.mkdtemp(prefix=PREFIX))
        chk(ts.is_own_temp_dir(mine, PREFIX), "D 시스템 임시 폴더 바로 아래 + 접두어 → 전용")
        chk(not ts.is_own_temp_dir(nested, PREFIX), "D 접두어만 같고 바로 아래가 아니면 전용 아님")
        chk(not ts.is_own_temp_dir(ROOT, PREFIX), "D 접두어가 다르면 전용 아님")
        chk(not ts.is_own_temp_dir(tempfile.gettempdir(), PREFIX), "D 시스템 임시 폴더 자체는 전용 아님")
        chk(not ts.remove_own_temp_dir(nested, PREFIX, who="test") and nested.is_dir(), "D 전용 아니면 지우지 않는다")
        chk(ts.remove_own_temp_dir(mine, PREFIX, who="test") and not mine.exists(), "D 전용이면 지운다")
        chk(ts.same_path(str(ROOT).upper() if os.name == "nt" else str(ROOT), Path(ROOT)), "D 실제 경로로 같은 곳")
    except (ImportError, AttributeError) as e:
        chk(False, "D 공용 판정 함수가 temp_sweep 에 있다", repr(e))
finally:
    shutil.rmtree(ROOT, ignore_errors=True)

if fails:
    print("FAIL", len(fails), fails)
    sys.exit(1)
print("ALL PASS")
