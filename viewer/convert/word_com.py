# -*- coding: utf-8 -*-
"""Word(Microsoft Word 사용) — Word 가 PDF 를 열어 docx 로 저장한다 (형식 변환 SOT §4.4, 261014-20).

- 보이는 때: Word 가 설치돼 있을 때만(`word_installed` — 레지스트리, COM 을 띄우지 않는다).
- Word 는 PDF 변환을 부속 프로그램 `pdfreflow.exe` 에 맡기고, 그것이 'PDF 를 편집 가능한 Word 문서로 변환합니다' 안내 창을
  띄워 자동화가 멈춘다. 이 Word 판은 그 창 끄기를 레지스트리 옵션으로 지키지 않아(실측), 지켜보는 스레드가 **이 변환이 띄운
  pdfreflow 의 안내 창에만** '확인' 을 보낸다 — Word 설정은 바꾸지 않는다.
- 배경 스레드에서 돈다. 중지·시간 상한이면 이 변환이 띄운 Word·pdfreflow 만 끝낸다(사용자 Word 는 건드리지 않는다).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

WORD_TIMEOUT_S = 300          # 기본 시간 상한
WORD_PER_PAGE_S = 3           # 쪽마다 더 준다
_FMT_DOCX = 16                # wdFormatXMLDocument
_CACHE: dict = {}


def word_installed() -> bool:
    """Word 가 설치돼 있나 — 레지스트리 `Word.Application\\CLSID` 를 한 번 보고 기억한다."""
    if "installed" not in _CACHE:
        ok = False
        if os.name == "nt":
            try:
                import winreg
                winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"))
                ok = True
            except Exception:
                ok = False
        _CACHE["installed"] = ok
    return _CACHE["installed"]


def _pids(name: str) -> set:
    """그 이름의 프로세스 번호들(가볍게 — 지켜보는 스레드가 0.3초마다 부른다)."""
    out = set()
    try:
        import win32api
        import win32con
        import win32process
        for pid in win32process.EnumProcesses():
            try:
                h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            except Exception:
                continue
            try:
                exe = win32process.GetModuleFileNameEx(h, 0)
            except Exception:
                exe = ""
            finally:
                win32api.CloseHandle(h)
            if os.path.basename(exe).lower() == name:
                out.add(int(pid))
    except Exception:
        pass
    return out


def _kill(pids) -> None:
    for pid in pids or ():
        try:
            import win32api
            import win32con
            h = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, int(pid))
            try:
                win32api.TerminateProcess(h, 1)
            finally:
                win32api.CloseHandle(h)
        except Exception:
            pass


def _press_ok(pids) -> int:
    """그 프로세스들의 대화상자(#32770)에 '확인'(IDOK) — 언어와 상관없이. 보낸 창 수."""
    if not pids:
        return 0
    n = 0
    try:
        import win32con
        import win32gui
        import win32process
        found = []

        def cb(h, _):
            try:
                _t, p = win32process.GetWindowThreadProcessId(h)
                if p in pids and win32gui.GetClassName(h) == "#32770":
                    found.append(h)
            except Exception:
                pass
            return True
        win32gui.EnumWindows(cb, None)
        for h in found:
            win32gui.PostMessage(h, win32con.WM_COMMAND, win32con.IDOK, 0)
            n += 1
    except Exception:
        pass
    return n


def convert_word(ps, pages, dst: Path, tick) -> None:
    """배경 스레드에서. `tick` 이 `Cancelled` 를 던지면 Word 를 끝내고 다시 던진다(부르는 쪽이 결과를 지운다)."""
    from viewer.convert import Cancelled, step_text
    from viewer.convert.proc import _layered_copy
    tmpdir = Path(tempfile.mkdtemp(prefix="polypdf_conv_"))
    layered = None
    try:
        layered = _layered_copy(ps, pages, tick)              # 스캔 쪽은 우리 OCR 글자층(§4.1 과 같은 길)
        src = layered or ps.path
        # Word 에는 **매번 새 이름의 사본**을 준다 — 중지·시간 상한으로 Word 를 끝낸 뒤 같은 파일을 다시 열면 Word 가
        #   '지난번에 열 때 오류가 났다, 그래도 열까요?' 창을 띄워 멈춘다(261014-20 실측)
        part = tmpdir / f"polypdf_{uuid.uuid4().hex[:12]}.pdf"
        if sorted(int(p) for p in pages) != list(range(ps.page_count)):
            import fitz
            d = fitz.open(src)
            try:
                d.select([int(p) for p in pages])          # 고른 쪽만
                d.save(str(part))
            finally:
                d.close()
        else:
            shutil.copy2(str(src), str(part))
        state = {"word": set(), "reflow0": _pids("pdfreflow.exe"), "cancel": False, "done": False, "timeout": False}
        limit = WORD_TIMEOUT_S + WORD_PER_PAGE_S * len(pages)

        def ours():
            return set(state["word"]) | (_pids("pdfreflow.exe") - state["reflow0"])

        def watch():
            t0 = time.monotonic()
            while not state["done"]:
                time.sleep(0.3)
                try:
                    tick(0, 1, step_text("word"))           # 진행 창 글(형식 변환 SOT §5, 261026-2)
                except Exception:
                    state["cancel"] = True
                if state["cancel"] or time.monotonic() - t0 > limit:
                    state["timeout"] = not state["cancel"]
                    _kill(ours())
                    return
                _press_ok(_pids("pdfreflow.exe") - state["reflow0"])   # 이 변환이 띄운 pdfreflow 의 안내 창에만
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        app = None
        w = threading.Thread(target=watch, daemon=True)
        try:
            before = _pids("winword.exe")
            app = win32com.client.DispatchEx("Word.Application")
            app.Visible = False
            app.DisplayAlerts = 0
            new = _pids("winword.exe") - before            # 이 변환이 띄운 Word — 사용자가 연 Word 는 건드리지 않는다
            state["word"] = new if len(new) == 1 else set()
            w.start()
            doc = app.Documents.Open(str(part), ConfirmConversions=False, ReadOnly=True,
                                     AddToRecentFiles=False, Visible=False)
            doc.SaveAs2(str(dst), FileFormat=_FMT_DOCX)
            doc.Close(False)
        except Exception as e:
            if state["cancel"]:
                raise Cancelled() from e
            if state["timeout"]:
                raise RuntimeError("Word did not finish in time") from e
            raise
        finally:
            state["done"] = True
            leftovers = ours()
            try:
                if app is not None:
                    app.Quit()
            except Exception:
                pass
            time.sleep(0.5)
            _kill({p for p in leftovers if p in _pids("winword.exe") | _pids("pdfreflow.exe")})   # 남은 자식까지
            pythoncom.CoUninitialize()
        if state["cancel"]:
            raise Cancelled()
    finally:
        if layered:
            shutil.rmtree(Path(layered).parent, ignore_errors=True)
        shutil.rmtree(tmpdir, ignore_errors=True)
