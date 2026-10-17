"""261017(가상 프린터 SOT §4.2·§4.5): 가상 프린터 'PolyPDF' 설치·제거·상태.

설치 프로그램(`PolyPDF.iss` 의 [Run]·`CurUninstallStepChanged`)과 도구 메뉴가 **같은 이 모듈**을 쓴다 —
`PolyPDF.exe --vprinter install|remove|check` (설치·제거는 관리자, 상태는 일반 권한).

- 스풀러 API 는 ctypes·pywin32 로 **직접** 부른다. 종전 PowerShell 판(`printer.ps1`)은 C# 을 임시 폴더에 즉석 컴파일했는데,
  백신(알약)이 그 DLL 4개를 `Gen:Variant.MSILHeracles` 로 잡았다(261017) — 즉석 컴파일을 하지 않는다.
- 순서·까닭은 P0 실측(SOT §3.13): 모니터 DLL 은 스풀러가 물고 있어 다시 시작해야 바뀌고 지워진다, 드라이버는 파일을
  스풀러 드라이버 폴더에 두고 **이름만** 넘긴다(전체 경로면 오류 3019), 드라이버를 지워도 PPD 는 남는다.
종료 코드: 0 성공 / 1 실패 / 2 이 PC 에서 쓸 수 없음 / 3 구성요소 없음.
"""
from __future__ import annotations

import ctypes
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

PRINTER_NAME = "PolyPDF"
DRIVER_NAME = "PolyPDF"
PORT_NAME = "PolyPDF Port"
MONITOR_NAME = "PolyPDF Port Monitor"
MONITOR_DLL = "polypdfmon.dll"
PPD_NAME = "POLYPDF.PPD"
TASK_PREFIX = "PolyPDF Print Receiver - "
FILE_PATTERN = "%u\\%j-%i %t.ps"
ENV = "Windows x64"
DRIVER_FILES = ("PSCRIPT5.DLL", "PS5UI.DLL", "PSCRIPT.NTF", "PSCRIPT.HLP")
MON_KEY = "SYSTEM\\CurrentControlSet\\Control\\Print\\Monitors\\" + MONITOR_NAME

EXIT_OK, EXIT_FAIL, EXIT_UNSUPPORTED, EXIT_MISSING = 0, 1, 2, 3
ERROR_PRINT_MONITOR_ALREADY_INSTALLED = 3006
APD_COPY_ALL_FILES, APD_COPY_NEW_FILES = 0x4, 0x8
_NO_WINDOW = 0x08000000


def spool_root() -> str:
    return os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "PolyPDF", "Print")


def _log_path() -> str:
    return os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "PolyPDF", "printer.log")


def info(action: str, msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(_log_path()), exist_ok=True)
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write("%s [%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), action, msg))
    except OSError:
        pass


def default_source_dir() -> str:
    """POLYPDF.PPD·bin\\polypdfmon.dll 이 있는 폴더 — 설치본은 `_internal\\printer`, 개발 실행은 저장소의 `printer`."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "printer")


def _sys32() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ── winspool (ctypes) ──────────────────────────────────────────────────
class _MONITOR_INFO_2(ctypes.Structure):
    _fields_ = [("pName", wintypes.LPWSTR), ("pEnvironment", wintypes.LPWSTR), ("pDLLName", wintypes.LPWSTR)]


class _DRIVER_INFO_3(ctypes.Structure):
    _fields_ = [("cVersion", wintypes.DWORD), ("pName", wintypes.LPWSTR), ("pEnvironment", wintypes.LPWSTR),
                ("pDriverPath", wintypes.LPWSTR), ("pDataFile", wintypes.LPWSTR), ("pConfigFile", wintypes.LPWSTR),
                ("pHelpFile", wintypes.LPWSTR), ("pDependentFiles", ctypes.c_wchar_p), ("pMonitorName", wintypes.LPWSTR),
                ("pDefaultDataType", wintypes.LPWSTR)]


class _PORT_INFO_1(ctypes.Structure):
    _fields_ = [("pName", wintypes.LPWSTR)]


class _PRINTER_INFO_2(ctypes.Structure):
    _fields_ = [("pServerName", wintypes.LPWSTR), ("pPrinterName", wintypes.LPWSTR), ("pShareName", wintypes.LPWSTR),
                ("pPortName", wintypes.LPWSTR), ("pDriverName", wintypes.LPWSTR), ("pComment", wintypes.LPWSTR),
                ("pLocation", wintypes.LPWSTR), ("pDevMode", ctypes.c_void_p), ("pSepFile", wintypes.LPWSTR),
                ("pPrintProcessor", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR), ("pParameters", wintypes.LPWSTR),
                ("pSecurityDescriptor", ctypes.c_void_p), ("Attributes", wintypes.DWORD), ("Priority", wintypes.DWORD),
                ("DefaultPriority", wintypes.DWORD), ("StartTime", wintypes.DWORD), ("UntilTime", wintypes.DWORD),
                ("Status", wintypes.DWORD), ("cJobs", wintypes.DWORD), ("AveragePPM", wintypes.DWORD)]


def _ws():
    w = ctypes.WinDLL("winspool.drv", use_last_error=True)
    w.AddMonitorW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p]
    w.DeleteMonitorW.argtypes = [wintypes.LPWSTR, wintypes.LPWSTR, wintypes.LPWSTR]
    w.AddPrinterDriverExW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    w.GetPrinterDriverDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p,
                                             wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    w.EnumPortsW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    for f in (w.AddMonitorW, w.DeleteMonitorW, w.AddPrinterDriverExW, w.GetPrinterDriverDirectoryW, w.EnumPortsW):
        f.restype = wintypes.BOOL
    w.AddPrinterW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p]
    w.AddPrinterW.restype = wintypes.HANDLE
    w.ClosePrinter.argtypes = [wintypes.HANDLE]
    return w


def _add_printer() -> int:
    pi = _PRINTER_INFO_2()
    pi.pPrinterName, pi.pPortName, pi.pDriverName = PRINTER_NAME, PORT_NAME, DRIVER_NAME
    pi.pPrintProcessor, pi.pDatatype = "winprint", "RAW"
    pi.Attributes = 0x40                                            # PRINTER_ATTRIBUTE_LOCAL
    ws = _ws()
    h = ws.AddPrinterW(None, 2, ctypes.byref(pi))
    if not h:
        return ctypes.get_last_error()
    ws.ClosePrinter(h)
    return 0


def driver_dir() -> str:
    buf = ctypes.create_unicode_buffer(520)
    need = wintypes.DWORD(0)
    if _ws().GetPrinterDriverDirectoryW(None, ENV, 1, buf, ctypes.sizeof(buf), ctypes.byref(need)):
        return buf.value
    return os.path.join(_sys32(), "spool", "drivers", "x64")


def _add_monitor() -> int:
    mi = _MONITOR_INFO_2(MONITOR_NAME, ENV, MONITOR_DLL)
    return 0 if _ws().AddMonitorW(None, 2, ctypes.byref(mi)) else ctypes.get_last_error()


def _delete_monitor() -> int:
    return 0 if _ws().DeleteMonitorW(None, ENV, MONITOR_NAME) else ctypes.get_last_error()


def _add_driver(flags: int) -> int:
    di = _DRIVER_INFO_3(3, DRIVER_NAME, ENV, "PSCRIPT5.DLL", PPD_NAME, "PS5UI.DLL", "PSCRIPT.HLP",
                        "PSCRIPT.NTF\0\0", None, None)
    return 0 if _ws().AddPrinterDriverExW(None, 3, ctypes.byref(di), flags) else ctypes.get_last_error()


def port_exists() -> bool:
    ws = _ws()
    need, ret = wintypes.DWORD(0), wintypes.DWORD(0)
    ws.EnumPortsW(None, 1, None, 0, ctypes.byref(need), ctypes.byref(ret))
    if not need.value:
        return False
    buf = ctypes.create_string_buffer(need.value)
    if not ws.EnumPortsW(None, 1, buf, need.value, ctypes.byref(need), ctypes.byref(ret)):
        return False
    arr = ctypes.cast(buf, ctypes.POINTER(_PORT_INFO_1))
    return any((arr[i].pName or "").lower() == PORT_NAME.lower() for i in range(ret.value))


# ── 이 PC 에서 쓸 수 있나 (SOT §3.8) ───────────────────────────────────
def _native_arm64() -> bool:
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        proc, native = ctypes.c_ushort(0), ctypes.c_ushort(0)
        if k.IsWow64Process2(k.GetCurrentProcess(), ctypes.byref(proc), ctypes.byref(native)):
            return native.value == 0xAA64
    except (AttributeError, OSError):
        pass
    return False


def pscript_source():
    """받은편지함 PSCRIPT5 의 최신 판이 있는 폴더(ntprint 드라이버 저장소)."""
    best, best_v = None, ()
    pat = os.path.join(_sys32(), "DriverStore", "FileRepository", "ntprint.inf_amd64_*", "Amd64", "PSCRIPT5.DLL")
    for p in glob.glob(pat):
        d = os.path.dirname(p)
        if not all(os.path.exists(os.path.join(d, f)) for f in DRIVER_FILES):
            continue
        try:
            import win32api
            info = win32api.GetFileVersionInfo(p, "\\")
            v = (info["FileVersionMS"] >> 16, info["FileVersionMS"] & 0xFFFF, info["FileVersionLS"] >> 16, info["FileVersionLS"] & 0xFFFF)
        except Exception:
            v = (0,)
        if best is None or v > best_v:
            best, best_v = d, v
    return best


def support() -> str:
    if _native_arm64():
        return "arm64"
    if sys.maxsize <= 2 ** 32:
        return "x86"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows NT\Printers\WPP") as k:
            for name in ("WindowsProtectedPrintGroupPolicyState", "WindowsProtectedPrintMode"):
                try:
                    if winreg.QueryValueEx(k, name)[0] == 1:
                        return "wpp"
                except OSError:
                    pass
    except OSError:
        pass
    if not pscript_source():
        return "no-pscript"
    return "ok"


# ── 상태 ──────────────────────────────────────────────────────────────
def _reg_exists(path: str) -> bool:
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path))
        return True
    except OSError:
        return False


def _printers() -> list:
    import win32print
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [p[2] for p in win32print.EnumPrinters(flags)]


def _driver_exists() -> bool:
    import win32print
    try:
        return any(d.get("Name") == DRIVER_NAME for d in win32print.EnumPrinterDrivers(None, ENV, 1))
    except Exception:
        return False


def state() -> dict:
    import win32print
    try:
        default = win32print.GetDefaultPrinter()
    except Exception:
        default = ""
    return {
        "support": support(),
        "monitor": _reg_exists(MON_KEY),
        "dll": os.path.exists(os.path.join(_sys32(), MONITOR_DLL)),
        "port": port_exists(),
        "driver": _driver_exists(),
        "printer": PRINTER_NAME in _printers(),
        "ppd": os.path.exists(os.path.join(driver_dir(), "3", PPD_NAME)),
        "spool": os.path.isdir(spool_root()),
        "default": default == PRINTER_NAME,
    }


# ── 설치 ──────────────────────────────────────────────────────────────
def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _restart_spooler() -> None:
    import win32serviceutil
    win32serviceutil.RestartService("Spooler")
    for _ in range(30):
        if win32serviceutil.QueryServiceStatus("Spooler")[1] == 4:     # SERVICE_RUNNING
            break
        time.sleep(0.5)
    time.sleep(1.5)


def _replace_dll(src: str, dst: str) -> None:
    """등록된 모니터의 DLL 을 새 판으로 — 스풀러를 멈추고 **멈춤(STOPPED)을 기다린 뒤** 복사하고, 복사가 실패해도
    **반드시 다시 시작**한다(261017-18 점검: 종전에는 복사가 실패하면 스풀러가 멈춘 채 남아 PC 전체 인쇄가 멈출 수 있었다)."""
    import win32serviceutil
    try:
        win32serviceutil.StopService("Spooler")
        for _ in range(40):                                      # SERVICE_STOPPED = 1, 최대 20초
            if win32serviceutil.QueryServiceStatus("Spooler")[1] == 1:
                break
            time.sleep(0.5)
        shutil.copy2(src, dst)
    finally:
        try:
            win32serviceutil.StartService("Spooler")
        except Exception as ex:                                  # 이미 돌고 있으면(1056) 그대로
            info("install", "스풀러 시작: %s" % ex)
        for _ in range(30):
            if win32serviceutil.QueryServiceStatus("Spooler")[1] == 4:   # SERVICE_RUNNING
                break
            time.sleep(0.5)


def _set_spool_acl() -> None:
    root = spool_root()
    os.makedirs(root, exist_ok=True)
    # P0 ②(SOT §3.13): SYSTEM·관리자 모두, Users 는 '제 폴더 만들기'만(남의 폴더는 목록도 못 봄), 만든 사람이 그 폴더의 주인.
    #   SID 로 적는다 — 'Users' 같은 이름은 Windows 언어마다 다르다.
    subprocess.run(["icacls", root, "/inheritance:r",
                    "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F",
                    "*S-1-5-32-545:(AD,X,RA,S)", "*S-1-3-0:(OI)(CI)(IO)F"],
                   capture_output=True, creationflags=_NO_WINDOW, check=True)


def port_config() -> tuple:
    """포트 설정 값(문자열, 숫자) — 값 이름은 원본 portlist.cpp. 인쇄 후 명령은 SYSTEM 이 사용자별 예약 작업을 깨운다(SOT §4.1)."""
    cmd = os.path.join(_sys32(), "schtasks.exe") + ' /run /tn "' + TASK_PREFIX + '%u"'
    want_s = {"OutputPath": spool_root(), "FilePattern": FILE_PATTERN, "UserCommand": cmd, "ExecPath": ""}
    want_d = {"Overwrite": 0, "WaitTermination": 0, "WaitTimeout": 10, "PipeData": 0, "HideProcess": 1}
    return want_s, want_d


def _write_port_config() -> bool:
    """포트 설정(모니터 키 아래 포트 이름 키). 바뀐 것이 있으면 True."""
    import winreg
    want_s, want_d = port_config()
    changed = False
    k = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, MON_KEY + "\\" + PORT_NAME, 0, winreg.KEY_ALL_ACCESS)
    try:
        for name, val in list(want_s.items()) + list(want_d.items()):
            typ = winreg.REG_SZ if isinstance(val, str) else winreg.REG_DWORD
            try:
                cur = winreg.QueryValueEx(k, name)[0]
            except OSError:
                cur = None
            if cur != val:
                winreg.SetValueEx(k, name, 0, typ, val)
                changed = True
    finally:
        winreg.CloseKey(k)
    return changed


def install(src: str | None = None) -> int:
    src = src or default_source_dir()
    sup = support()
    if sup != "ok":
        info("install", "쓸 수 없음: " + sup)
        return EXIT_UNSUPPORTED
    dll_src, ppd_src = os.path.join(src, "bin", MONITOR_DLL), os.path.join(src, PPD_NAME)
    if not (os.path.exists(dll_src) and os.path.exists(ppd_src)):
        info("install", "구성요소 없음: %s / %s" % (dll_src, ppd_src))
        return EXIT_MISSING
    import win32print
    try:
        default = win32print.GetDefaultPrinter()
    except Exception:
        default = ""

    # 1) 모니터 DLL — 다를 때만, 이미 등록돼 있으면 스풀러를 멈추고 바꾼다(P0 ⑤)
    dll_dst = os.path.join(_sys32(), MONITOR_DLL)
    registered = _reg_exists(MON_KEY)
    if not (os.path.exists(dll_dst) and _sha(dll_dst) == _sha(dll_src)):
        if registered:
            _replace_dll(dll_src, dll_dst)
            info("install", "모니터 DLL 새 판으로")
        else:
            shutil.copy2(dll_src, dll_dst)
            info("install", "모니터 DLL 복사")
    if not registered:
        e = _add_monitor()
        if e and e != ERROR_PRINT_MONITOR_ALREADY_INSTALLED:
            info("install", "모니터 등록 실패 %d" % e)
            return EXIT_FAIL
        info("install", "모니터 등록")

    # 2) 포트·스풀 폴더 — 바뀐 값이 있을 때만 스풀러를 다시 시작한다(모니터가 레지스트리를 시작할 때 읽는다)
    changed = _write_port_config()
    _set_spool_acl()
    if changed or not port_exists():
        _restart_spooler()
        info("install", "포트 설정 — 스풀러 다시 시작")
    for _ in range(20):
        if port_exists():
            break
        time.sleep(0.5)
    else:
        info("install", "포트가 보이지 않음")
        return EXIT_FAIL

    # 3) 드라이버 — PPD 가 같으면 건너뛴다
    ddir = driver_dir()
    ppd_inst = os.path.join(ddir, "3", PPD_NAME)
    has_drv = _driver_exists()
    if not has_drv or not (os.path.exists(ppd_inst) and _sha(ppd_inst) == _sha(ppd_src)):
        ps = pscript_source()
        staged = []
        try:
            for f in DRIVER_FILES:
                shutil.copy2(os.path.join(ps, f), os.path.join(ddir, f))
                staged.append(os.path.join(ddir, f))
            shutil.copy2(ppd_src, os.path.join(ddir, PPD_NAME))
            staged.append(os.path.join(ddir, PPD_NAME))
            e = _add_driver(APD_COPY_NEW_FILES | (APD_COPY_ALL_FILES if has_drv else 0))
        finally:
            for s in staged:
                try:
                    os.remove(s)
                except OSError:
                    pass
        if e:
            info("install", "드라이버 등록 실패 %d" % e)
            return EXIT_FAIL
        info("install", "드라이버 등록(PSCRIPT5: %s)" % ps)

    # 4) 프린터
    if PRINTER_NAME not in _printers():
        ok = False
        for i in range(5):
            e = _add_printer()
            if not e:
                ok = True
                break
            info("install", "프린터 추가 재시도 %d: 오류 %d" % (i + 1, e))
            time.sleep(2)
        if not ok:
            return EXIT_FAIL
        info("install", "프린터 추가")
    else:
        h = win32print.OpenPrinter(PRINTER_NAME, {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
        try:
            pinfo = win32print.GetPrinter(h, 2)        # 'info' 는 기록 함수 이름 — 지역 변수로 쓰면 함수 전체가 깨진다(261017)
            if pinfo["pDriverName"] != DRIVER_NAME or pinfo["pPortName"] != PORT_NAME:
                pinfo["pDriverName"], pinfo["pPortName"] = DRIVER_NAME, PORT_NAME
                win32print.SetPrinter(h, 2, pinfo, 0)
                info("install", "프린터 고침")
        finally:
            win32print.ClosePrinter(h)

    # 5) 기본 프린터는 바꾸지 않는다(SOT §4.5). 'Windows 에서 기본 프린터 관리' 가 켜진 PC 는 프린터를 더한 **몇 초 뒤**
    #   기본을 바꾼다(261017 P1 실측) — 잠시 지켜보며 되돌린다.
    if default:
        for _ in range(8):
            try:
                if win32print.GetDefaultPrinter() != default:
                    win32print.SetDefaultPrinter(default)
                    info("install", "기본 프린터 되돌림: " + default)
            except Exception:
                pass
            time.sleep(0.5)
    info("install", "설치 끝 " + json.dumps(state(), ensure_ascii=False))
    return EXIT_OK


# ── 제거 ──────────────────────────────────────────────────────────────
def _delete_tasks() -> None:
    r = subprocess.run(["schtasks", "/query", "/fo", "csv", "/nh"], capture_output=True, creationflags=_NO_WINDOW)
    out = r.stdout.decode("mbcs", errors="replace")
    for line in out.splitlines():
        name = line.split('","')[0].strip('"').lstrip("\\")
        if name.startswith(TASK_PREFIX):
            subprocess.run(["schtasks", "/delete", "/tn", name, "/f"], capture_output=True, creationflags=_NO_WINDOW)


def remove(keep: bool = False) -> int:
    if keep:
        info("remove", "업그레이드 — 프린터 유지")
        return EXIT_OK
    import win32print
    if PRINTER_NAME in _printers():
        h = win32print.OpenPrinter(PRINTER_NAME, {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
        try:
            try:
                win32print.SetPrinter(h, 0, None, 3)        # PRINTER_CONTROL_PURGE — 대기 작업 지우기
            except Exception:
                pass
            win32print.DeletePrinter(h)
        finally:
            win32print.ClosePrinter(h)
        info("remove", "프린터 지움")
    # 261017 설치 시험: 인쇄한 프로그램(PowerPoint)이 아직 프린터 핸들을 쥐고 있으면 프린터 삭제가 '대기' 로 남아
    #   드라이버 지우기(3001)·모니터 해제(3008)가 '사용 중' 으로 실패했다 → 스풀러를 다시 시작해 대기 삭제를 끝낸 뒤 다시 한다.
    def _del_driver():
        try:
            win32print.DeletePrinterDriverEx(None, ENV, DRIVER_NAME, 0x1, 0)   # DPD_DELETE_UNUSED_FILES
            return 0
        except Exception as ex:                                    # pywintypes.error(3001, …)
            return ex.args[0] if ex.args and isinstance(ex.args[0], int) else 1
    if _driver_exists():
        e = _del_driver()
        if e:
            info("remove", "드라이버 지우기 %d — 스풀러 다시 시작 뒤 다시" % e)
            _restart_spooler()
            e = _del_driver() if _driver_exists() else 0
        info("remove", "드라이버 지움" if not e else "드라이버 못 지움 %d" % e)
    try:                                                            # 드라이버를 지워도 PPD 는 남는다(P0 ⑤)
        os.remove(os.path.join(driver_dir(), "3", PPD_NAME))
    except OSError:
        pass
    if _reg_exists(MON_KEY):
        import winreg
        try:
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, MON_KEY + "\\" + PORT_NAME)
        except OSError:
            pass
        e = _delete_monitor()
        if e:
            info("remove", "모니터 등록 해제 %d — 스풀러 다시 시작 뒤 다시" % e)
            _restart_spooler()
            e = _delete_monitor() if _reg_exists(MON_KEY) else 0
        if e and _reg_exists(MON_KEY) and not os.path.exists(os.path.join(_sys32(), MONITOR_DLL)):
            # 3000(알 수 없는 모니터): DLL 이 이미 없어 스풀러가 모니터를 싣지 못했다 — 등록 키만 남은 상태라 키를 직접 지운다
            try:
                winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, MON_KEY)
                e = 0
            except OSError as ex:
                info("remove", "모니터 키 못 지움: %s" % ex)
        info("remove", "모니터 등록 해제 %d" % e)
    dll = os.path.join(_sys32(), MONITOR_DLL)
    if os.path.exists(dll):
        _restart_spooler()                                          # 물고 있던 DLL 을 놓게(P0 ⑤)
        try:
            os.remove(dll)
            info("remove", "모니터 DLL 지움")
        except OSError as ex:
            # 그래도 물려 있으면 재부팅 때 지우기 예약(SOT §4.5, 261017-18) — MOVEFILE_DELAY_UNTIL_REBOOT
            ok = ctypes.windll.kernel32.MoveFileExW(dll, None, 0x4)
            info("remove", "모니터 DLL 못 지움: %s — 재부팅 때 지우기 예약 %s" % (ex, "됨" if ok else "실패"))
    for p in glob.glob(os.path.join(_sys32(), "polypdfmon*.log")):
        try:
            os.remove(p)
        except OSError:
            pass
    _delete_tasks()
    shutil.rmtree(spool_root(), ignore_errors=True)
    st = state()
    info("remove", "제거 끝 " + json.dumps(st, ensure_ascii=False))
    return EXIT_FAIL if (st["printer"] or st["driver"] or st["monitor"] or st["dll"]) else EXIT_OK


def run_cli(argv: list) -> int:
    """`--vprinter install|remove|check [--source DIR] [--keep]`"""
    action = argv[0] if argv else "check"
    src = argv[argv.index("--source") + 1] if "--source" in argv[:-1] else None
    try:
        if action == "check":
            if sys.stdout is not None:              # 설치본(창 전용)은 표준 출력이 없다 — 상태는 기록에 남긴다
                print(json.dumps(state(), ensure_ascii=False))
            else:
                info("check", json.dumps(state(), ensure_ascii=False))
            return EXIT_OK
        if action in ("install", "remove") and not _is_admin():
            info(action, "관리자 아님")
            return EXIT_FAIL
        if action == "install":
            return install(src)
        if action == "remove":
            return remove(keep="--keep" in argv)
    except Exception as ex:                                         # 처리 안 된 예외도 기록하고 실패로 끝낸다
        info(action, "오류: %r" % (ex,))
        return EXIT_FAIL
    return EXIT_FAIL
