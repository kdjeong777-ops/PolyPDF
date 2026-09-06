# -*- coding: utf-8 -*-
"""260906-3: 시작 시 무엇을 여는가 — 3택 + '보던 형태 그대로' + 캡처 목록 비움.

사용자 결정(260906):
  - 파일·폴더를 지정하지 않고 실행했을 때 **기본은 마지막에 보던 것**을 연다.
    단, 1번째 뷰어가 **파일 모드**로 보고 있었으면 그 **파일만** 연다 —
    상위 폴더를 훑으면 열라고 하지 않은 폴더를 뒤지게 된다(수천 개면 그만큼 느리다).
  - 기억해 둔 것이 없거나 사라졌으면 **빈 화면**. 대신 다른 것을 열어 주지 않는다.
  - '지정한 폴더·파일 열기'와 '아무것도 열지 않기' 옵션(환경설정 '시작 동작').
  - 캡처 목록은 **항상 빈 상태로 시작**하고, 종료할 때 있으면 PDF 저장 여부를 묻는다.

§14.7: 공유 설정(settings.json)을 건드리므로 스냅샷 → 끝에 원복.
"""
import os, sys, io, json, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
app.setApplicationName("PolyPDF")
app.setOrganizationName("LocalTools")
import test_fixtures as _fx
from viewer import settings_store
from viewer.app import MainWindow

SPATH = settings_store.settings_path("settings.json")
ORIG = io.open(SPATH, encoding="utf-8").read() if SPATH.exists() else None

# 표본 폴더: PDF 2개
root = Path(tempfile.mkdtemp(prefix="polypdf_startup_"))
src = Path(_fx.text_pdf())
one, two = root / "a.pdf", root / "b.pdf"
shutil.copy(src, one)
shutil.copy(src, two)


def write_settings(**over):
    d = json.loads(ORIG) if ORIG else {}
    prefs = dict(d.get("preferences") or {})
    prefs.update(over.pop("preferences", {}))
    d.update(over)
    d["preferences"] = prefs
    io.open(SPATH, "w", encoding="utf-8", newline="\n").write(
        json.dumps(d, ensure_ascii=False, indent=2))


def fresh(**over):
    write_settings(**over)
    mw = MainWindow()
    mw._skip_save_on_close = True
    mw._restore_session_deferred()          # 이벤트 루프가 부르는 것을 직접
    app.processEvents()
    return mw


try:
    # ── ① 기본(last) + 폴더 모드 → 그 폴더를 연다 ────────────────────────
    mw = fresh(last_open={"kind": "folder", "path": str(root)},
               last_folder=str(root), last_main=None,
               preferences={"startup_mode": "last"})
    chk(mw._folder is not None and Path(mw._folder) == root,
        "① 폴더로 보던 세션 → 그 폴더를 연다", repr(mw._folder))
    chk(not mw.bookmark_tree._is_file_mode(), "① 폴더 모드로 열린다")

    # ── ② 기본(last) + 파일 모드 → 그 파일만, 폴더를 훑지 않는다 ─────────
    mw = fresh(last_open={"kind": "file", "path": str(one)},
               last_folder=str(root), last_main=None,
               preferences={"startup_mode": "last"})
    chk(mw.bookmark_tree._is_file_mode(), "② 파일로 보던 세션 → 파일 모드로 열린다")
    listed = mw.bookmark_tree.all_file_paths()
    chk(len(listed) == 1 and Path(listed[0]) == one,
        "② 그 파일 하나만 목록에 오른다(상위 폴더 스캔 없음)", f"{len(listed)}개")

    # ── ③ 기억해 둔 것이 없으면 빈 화면 ──────────────────────────────────
    mw = fresh(last_open={}, last_folder="", last_main=None,
               preferences={"startup_mode": "last"})
    chk(mw._folder is None and not mw.bookmark_tree.all_file_paths(),
        "③ 열었던 것이 없으면 아무것도 열지 않는다", repr(mw._folder))

    # ── ④ 기억해 둔 경로가 사라졌으면 빈 화면(대신 열어 주지 않음) ───────
    gone = str(root / "없는폴더")
    mw = fresh(last_open={"kind": "folder", "path": gone}, last_folder=gone,
               preferences={"startup_mode": "last"})
    chk(mw._folder is None, "④ 사라진 경로 → 빈 화면", repr(mw._folder))

    # ── ⑤ none: 기억이 있어도 열지 않는다 ────────────────────────────────
    mw = fresh(last_open={"kind": "folder", "path": str(root)},
               preferences={"startup_mode": "none"})
    chk(mw._folder is None, "⑤ '아무것도 열지 않음' 은 기억이 있어도 안 연다")

    # ── ⑥ path: 지정한 파일을 연다(마지막 것 대신) ───────────────────────
    mw = fresh(last_open={"kind": "folder", "path": str(root)},
               preferences={"startup_mode": "path", "startup_path": str(two)})
    chk(mw.bookmark_tree._is_file_mode(), "⑥ 지정 경로가 PDF면 파일 모드")
    listed = mw.bookmark_tree.all_file_paths()
    chk(len(listed) == 1 and Path(listed[0]) == two,
        "⑥ 지정한 그 파일을 연다", str(listed))

    # ── ⑦ 구 설정 승계: restore_session=False → none ─────────────────────
    d = json.loads(ORIG) if ORIG else {}
    prefs = dict(d.get("preferences") or {})
    prefs.pop("startup_mode", None)
    prefs["restore_session"] = False
    d["preferences"] = prefs
    d["last_open"] = {"kind": "folder", "path": str(root)}
    io.open(SPATH, "w", encoding="utf-8", newline="\n").write(
        json.dumps(d, ensure_ascii=False, indent=2))
    mw = MainWindow(); mw._skip_save_on_close = True
    chk(mw._prefs.get("startup_mode") == "none",
        "⑦ 구 restore_session=False 는 '열지 않음' 으로 1회 승계",
        repr(mw._prefs.get("startup_mode")))

    # ── ⑧ 캡처 목록: 저장하지 않고, 시작은 항상 빈 목록 ──────────────────
    mw = fresh(last_open={}, preferences={"startup_mode": "last"})
    chk(mw.shot_strip.list.count() == 0, "⑧ 시작 시 캡처 목록은 비어 있다")
    payload = mw._build_settings_payload()
    chk(payload.get("screenshots") == [] and payload.get("screenshots_meta") == [],
        "⑧ 캡처 목록은 설정에 저장하지 않는다")
    chk(callable(getattr(mw, "_confirm_close_screenshots", None)),
        "⑧ 종료 시 저장 확인 진입점이 있다")
    chk(mw._confirm_close_screenshots() is True,
        "⑧ 목록이 비어 있으면 묻지 않고 그대로 종료")

    # ── ⑨ 저장 페이로드가 '보던 형태'를 기억한다 ─────────────────────────
    mw = fresh(last_open={"kind": "file", "path": str(one)},
               preferences={"startup_mode": "last"})
    lo = mw._build_settings_payload().get("last_open") or {}
    chk(lo.get("kind") == "file" and Path(lo.get("path", "")) == one,
        "⑨ 파일 모드는 kind=file 로 저장", str(lo))
    mw.open_folder(root); app.processEvents()
    lo = mw._build_settings_payload().get("last_open") or {}
    chk(lo.get("kind") == "folder" and Path(lo.get("path", "")) == root,
        "⑨ 폴더 모드는 kind=folder 로 저장", str(lo))
finally:
    if ORIG is None:
        if SPATH.exists():
            SPATH.unlink()
    else:
        io.open(SPATH, "w", encoding="utf-8", newline="\n").write(ORIG)
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
