# -*- coding: utf-8 -*-
"""이사 판(261114-23, 마스터 §1.1·릴리스 SOT §14.5 U26) 뒷손질 — 설정 폴더 이사 기록·잠근 프로그램 찾기·옛 바로가기 고치기.

- `move_log(parent, text)`: `%APPDATA%\\LocalTools\\<APP_ID>-move.log` 에 한 줄(옛·새 폴더 **밖** — 이름 바꾸기와 상관없이 남는다).
- `who_locks(paths)`: Windows Restart Manager 로 그 파일을 열어 둔 프로그램 이름(PID) — 폴더 이름 바꾸기가 실패했을 때 기록용.
  폴더 핸들(탐색기 창·네트워크 경로 `\\\\localhost\\C$` 의 SMB 캐시)은 파일이 아니라 여기 안 나온다 → 기록에 '파일 잠금 없음'.
- `repair_shortcuts(exe, folders, …)`: 사용자 시작 메뉴·바탕 화면·작업 표시줄 고정의 `.lnk` 중 **없어진 옛 실행 파일**(`PolyPDF.exe`)을
  가리키는 것을 지금 실행 파일로(대상·작업 폴더·아이콘·작업 표시줄 앱 ID). 이사 판 설치는 옛 `Program Files\\PolyPDF` 를 지우므로
  손으로 만든 바로가기·작업 표시줄 고정이 죽는다(beta.14 설치 시험 261114). 이름에 옛 이름이 든 것은 새 이름으로 바꾼다(작업 표시줄 고정은 이름 그대로).
"""
import os
import time
from pathlib import Path


def move_log(parent, text: str) -> None:
    try:
        from viewer.branding import APP_ID
        p = Path(parent) / (APP_ID + "-move.log")
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + text.rstrip() + "\n")
    except Exception:
        pass


def who_locks(paths) -> list:
    """`paths` 를 열어 둔 프로그램 'name(pid)' 목록 — Windows 가 아니거나 실패하면 []."""
    if os.name != "nt":
        return []
    paths = [str(p) for p in paths][:64]
    if not paths:
        return []
    try:
        import ctypes
        from ctypes import wintypes
        rm = ctypes.WinDLL("rstrtmgr")

        class FILETIME(ctypes.Structure):
            _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

        class RM_UNIQUE_PROCESS(ctypes.Structure):
            _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", FILETIME)]

        class RM_PROCESS_INFO(ctypes.Structure):
            _fields_ = [("Process", RM_UNIQUE_PROCESS), ("strAppName", ctypes.c_wchar * 256),
                        ("strServiceShortName", ctypes.c_wchar * 64), ("ApplicationType", ctypes.c_int),
                        ("AppStatus", wintypes.ULONG), ("TSSessionId", wintypes.DWORD), ("bRestartable", wintypes.BOOL)]

        h = wintypes.DWORD()
        key = ctypes.create_unicode_buffer(64)
        if rm.RmStartSession(ctypes.byref(h), 0, key):
            return []
        try:
            arr = (ctypes.c_wchar_p * len(paths))(*paths)
            if rm.RmRegisterResources(h, len(paths), arr, 0, None, 0, None):
                return []
            need, n, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
            rm.RmGetList(h, ctypes.byref(need), ctypes.byref(n), None, ctypes.byref(reasons))
            if not need.value:
                return []
            info = (RM_PROCESS_INFO * need.value)()
            n = wintypes.UINT(need.value)
            if rm.RmGetList(h, ctypes.byref(need), ctypes.byref(n), info, ctypes.byref(reasons)):
                return []
            return ["%s(%d)" % (info[i].strAppName, info[i].Process.dwProcessId) for i in range(n.value)]
        finally:
            rm.RmEndSession(h)
    except Exception:
        return []


def lock_report(folder) -> str:
    """폴더 맨 위 파일(설정·색인 — 열어 둘 만한 것)을 연 프로그램 — 기록용 한 줄."""
    try:
        files = [p for p in Path(folder).iterdir() if p.is_file()]
    except Exception:
        return "cannot list folder"           # 기록 전용(화면 문구 아님) — 영어(다국어 SOT, clipboard_util.diag 선례)
    who = who_locks(files)
    return ("locked by: " + ", ".join(who)) if who else "no file locks (folder handle - Explorer window, network path or antivirus scan?)"


def shortcut_folders() -> dict:
    """사용자 시작 메뉴(맨 위와 한 단계 아래)·바탕 화면·작업 표시줄 고정 폴더 → {'programs': […], 'desktop': […], 'taskbar': […]}."""
    ad = Path(os.environ.get("APPDATA") or "")
    progs = ad / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    out = {"programs": [progs], "desktop": [], "taskbar": [ad / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar"]}
    try:
        out["programs"] += [d for d in progs.iterdir() if d.is_dir() and "polypdf" in d.name.lower()]
    except Exception:
        pass
    try:
        from PyQt6.QtCore import QStandardPaths
        dl = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if dl:
            out["desktop"].append(Path(dl))
    except Exception:
        pass
    return out


def _set_aumid(lnk: str, aumid: str) -> bool:
    try:
        import pythoncom
        from win32com.propsys import propsys, pscon
        from win32com.shell import shell
        link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
        pf = link.QueryInterface(pythoncom.IID_IPersistFile)
        pf.Load(lnk, 2)                                         # STGM_READWRITE
        store = link.QueryInterface(propsys.IID_IPropertyStore)
        store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(aumid))
        store.Commit()
        pf.Save(lnk, True)
        return True
    except Exception:
        return False


def repair_shortcuts(exe: str, folders: dict, old_exe_names=("polypdf.exe",), old_word="PolyPDF", new_word="PolyPinax",
                     aumid: str = "", exists=os.path.exists) -> list:
    """없어진 옛 실행 파일을 가리키는 바로가기를 `exe` 로 → [(옛 경로, 새 경로)]. 이름에 옛 이름이 없는 바로가기·살아 있는 대상은 건드리지 않는다."""
    done = []
    try:
        import win32com.client
        sh = win32com.client.Dispatch("WScript.Shell")
    except Exception:
        return done
    for kind, dirs in folders.items():
        for d in dirs:
            try:
                files = [p for p in Path(d).iterdir() if p.suffix.lower() == ".lnk" and old_word.lower() in p.name.lower()]
            except Exception:
                continue
            for p in files:
                try:
                    s = sh.CreateShortcut(str(p))
                    tgt = s.TargetPath or ""
                    if os.path.basename(tgt).lower() not in old_exe_names or exists(tgt):
                        continue
                    s.TargetPath = exe
                    s.WorkingDirectory = os.path.dirname(exe)
                    s.IconLocation = exe + ",0"
                    s.Save()
                    if aumid:
                        _set_aumid(str(p), aumid)
                    newp = p
                    if kind != "taskbar":                       # 작업 표시줄 고정은 파일 이름이 고정 항목 — 그대로
                        cand = p.with_name(p.name.replace(old_word, new_word))
                        if cand != p and not cand.exists():
                            os.replace(p, cand)
                            newp = cand
                    done.append((str(p), str(newp)))
                except Exception:
                    continue
    return done
