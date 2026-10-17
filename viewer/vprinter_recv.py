"""261017(가상 프린터 SOT §4.1·§4.3): 가상 프린터로 받은 PostScript 를 PDF 로 바꾸고 저장할 자리를 정한다 — 사용자 쪽(Qt 없음).

- 스풀 폴더 `%ProgramData%\\PolyPDF\\Print\\<사용자>` 의 `<작업 번호>-<번호> <문서 이름>.ps` 를 집는다(모니터가 사용자 권한으로 쓴다 — P1).
- 원래 파일: 문서 이름을 다듬어 Windows 최근 항목 → Office 최근 목록에서 찾는다. 없거나 임시·쓸 수 없는 폴더면 기본 저장 폴더.
- 변환: 동봉한 Ghostscript(`printer\\bin\\gs`)를 **사용자 권한**으로. 가로 문서는 바로 세우고(회전 표시를 남기지 않는다) 제목을 문서 이름으로.
- 사용자별 예약 작업 'PolyPDF Print Receiver - <사용자>' 를 만든다(관리자 필요 없음) — 인쇄 후 모니터(SYSTEM)가 이것을 깨운다.
무거운 일(변환·파일 찾기)은 호출하는 쪽이 배경에서 부른다(응답성 SOT §4).
"""
from __future__ import annotations

import getpass
import glob
import os
import re
import subprocess
import sys
import tempfile
import time

from viewer.vprinter import TASK_PREFIX, spool_root

_NO_WINDOW = 0x08000000
# 작업 이름 앞에 프로그램이 붙이는 꼴 — 'Microsoft PowerPoint - 계획.pptx', 'Microsoft Word - 보고.docx'
_APP_PREFIX = re.compile(r"^(?:Microsoft\s+\w+(?:\s+\w+)?|[^-]{1,40}?)\s+-\s+(?=.+\.\w{2,5}\b)")
_TAIL = re.compile(r"\s*[\[(](?:읽기 전용|호환 모드|Read-Only|Compatibility Mode|보호된 보기|Protected View)[\])]\s*$", re.I)
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def user_name() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME", "user")


def user_spool_dir() -> str:
    return os.path.join(spool_root(), user_name())


def pending_jobs() -> list:
    """받은 PS — 오래된 것부터. 모니터는 파일을 **닫은 뒤에** 인쇄 후 명령을 부르므로(원본 `port.cpp` EndJob) 방금 쓴 파일도 다 쓴 것이다.
    261017 손 확인: 종전에는 1초 안에 바뀐 파일을 건너뛰어 알림이 오자마자 본 첫 인쇄를 놓쳤다."""
    out = []
    for p in glob.glob(os.path.join(user_spool_dir(), "*.ps")):
        try:
            out.append((os.path.getmtime(p), p))
        except OSError:
            pass
    return [p for _t, p in sorted(out)]


def job_title(ps_path: str) -> str:
    """'12-0001 Microsoft PowerPoint - 계획.pptx.ps' → 'Microsoft PowerPoint - 계획.pptx' (이름 규칙 `%j-%i %t.ps`)."""
    base = os.path.basename(ps_path)
    if base.lower().endswith(".ps"):
        base = base[:-3]
    m = re.match(r"^\d+-\d+ (.*)$", base)
    return (m.group(1) if m else base).strip()


def clean_title(title: str) -> str:
    """작업 이름에서 프로그램 이름·'[읽기 전용]' 같은 꼬리를 떼어 원래 파일 이름 후보를 만든다."""
    t = _TAIL.sub("", (title or "").strip())
    t = _APP_PREFIX.sub("", t, count=1).strip()
    return t


def safe_stem(name: str) -> str:
    """파일 이름으로 쓸 수 있게 — 경로 구분자·'..'·예약 이름·못 쓰는 글자를 걸러 저장 폴더 밖으로 나가지 않게(SOT §4.3)."""
    s = _BAD.sub("_", name or "").strip().strip(".")
    s = re.sub(r"\.{2,}", ".", s)
    if not s or s.upper() in _RESERVED:
        from viewer.i18n import tr                # 제안하는 파일 이름은 만드는 때의 언어로(다국어 SOT §8)
        s = tr("인쇄_{stamp}").format(stamp=time.strftime("%Y%m%d_%H%M%S"))
    return s[:150]


def _recent_lnk_target(file_name: str):
    """Windows 최근 항목(`%APPDATA%\\Microsoft\\Windows\\Recent\\<이름>.lnk`)이 가리키는 경로."""
    lnk = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Recent", file_name + ".lnk")
    if not os.path.isfile(lnk):
        return None
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            t = win32com.client.Dispatch("WScript.Shell").CreateShortcut(lnk).TargetPath
        finally:
            pythoncom.CoUninitialize()
        return t or None
    except Exception:
        return None


def _office_mru(file_name: str):
    """Office 최근 파일 목록(HKCU\\…\\Office\\<판>\\<앱>\\User MRU\\*\\File MRU) 에서 같은 이름의 가장 최근 경로."""
    import winreg
    best, best_t = None, -1
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Office")
    except OSError:
        return None

    def _subkeys(k):
        i = 0
        while True:
            try:
                yield winreg.EnumKey(k, i)
            except OSError:
                return
            i += 1

    for ver in list(_subkeys(root)):
        if not re.match(r"^\d+\.\d+$", ver):
            continue
        for app in ("PowerPoint", "Word", "Excel"):
            try:
                mru_root = winreg.OpenKey(root, "%s\\%s\\User MRU" % (ver, app))
            except OSError:
                continue
            for ident in list(_subkeys(mru_root)):
                try:
                    k = winreg.OpenKey(mru_root, ident + r"\File MRU")
                except OSError:
                    continue
                i = 0
                while True:
                    try:
                        _n, v, _t = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    m = re.match(r"^\[F[0-9A-F]+\]\[T([0-9A-F]+)\](?:\[O\d+\])?\*(.+)$", str(v))
                    if m and os.path.basename(m.group(2)).lower() == file_name.lower():
                        t = int(m.group(1), 16)
                        if t > best_t:
                            best, best_t = m.group(2), t
    return best


def find_original(file_name: str):
    """원래 파일의 전체 경로 — 확장자가 있는 이름일 때만 찾는다. 실제로 있어야 한다."""
    if not file_name or not re.search(r"\.\w{2,5}$", file_name):
        return None
    for fn in (_recent_lnk_target, _office_mru):
        try:
            p = fn(file_name)
        except Exception:
            p = None
        if p and os.path.isfile(p) and os.path.basename(p).lower() == file_name.lower():
            return p
    return None


def is_temp_dir(folder: str) -> bool:
    """메일 첨부·브라우저 캐시·임시 폴더 — 원래 파일 폴더로 쓰지 않는다(SOT §4.3)."""
    f = os.path.normcase(os.path.abspath(folder or ""))
    temps = {os.path.normcase(os.path.abspath(tempfile.gettempdir()))}
    for v in ("TEMP", "TMP"):
        if os.environ.get(v):
            temps.add(os.path.normcase(os.path.abspath(os.environ[v])))
    if any(f == t or f.startswith(t + os.sep) for t in temps):
        return True
    low = f.lower()
    return any(s in low for s in ("\\inetcache\\", "\\content.outlook\\", "\\temporary internet files\\"))


def folder_writable(folder: str) -> bool:
    if not folder or not os.path.isdir(folder):
        return False
    probe = os.path.join(folder, ".polypdf_write_test_%d" % os.getpid())
    try:
        with open(probe, "wb"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def default_save_dir() -> str:
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:     # CSIDL_PERSONAL
            docs = buf.value
    except Exception:
        pass
    return os.path.join(docs, "PolyPDF 인쇄")


def unique_pdf_path(folder: str, stem: str) -> str:
    """'이름.pdf' 가 있으면 '이름 (1).pdf', '이름 (2).pdf' …(사용자 지시 — SOT §4.3)."""
    stem = safe_stem(stem)
    p = os.path.join(folder, stem + ".pdf")
    n = 1
    while os.path.exists(p):
        p = os.path.join(folder, "%s (%d).pdf" % (stem, n))
        n += 1
    return p


def plan_save(ps_path: str, prefer: str = "original", default_dir: str = "") -> dict:
    """저장 자리 계획 — {title, name, original, orig_dir, default_dir, folder, reason}. 원래 파일 찾기가 COM·레지스트리라 배경에서 부른다."""
    title = job_title(ps_path)
    cand = clean_title(title)
    orig = find_original(cand)
    stem = os.path.splitext(os.path.basename(orig))[0] if orig else os.path.splitext(cand)[0] if re.search(r"\.\w{2,5}$", cand) else cand
    default_dir = default_dir or default_save_dir()
    orig_dir, reason = "", ""
    if orig:
        d = os.path.dirname(orig)
        if is_temp_dir(d):
            reason = "temp"
        elif not folder_writable(d):
            reason = "readonly"
        else:
            orig_dir = d
    else:
        reason = "notfound"
    folder = orig_dir if (prefer == "original" and orig_dir) else default_dir
    return {"title": title, "name": safe_stem(stem), "original": orig or "", "orig_dir": orig_dir,
            "default_dir": default_dir, "folder": folder, "reason": reason if not orig_dir else ""}


# ── Ghostscript ─────────────────────────────────────────────────────────
def gs_exe():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "printer", "bin", "gs", "gswin64c.exe")
    return p if os.path.isfile(p) else None


def is_landscape(ps_path: str) -> bool:
    """PScript5 는 문서 머리에 `%%Orientation: Landscape` 를 적는다(261017 표본) — 가로 문서는 세로 쪽에 돌려 그려 온다."""
    try:
        with open(ps_path, "rb") as f:
            head = f.read(65536)
        return b"%%Orientation: Landscape" in head
    except OSError:
        return False


def convert(ps_path: str, out_pdf: str, title: str = "", gray: bool = False, gs: str | None = None) -> None:
    """PS → PDF(사용자 권한). 가로면 쪽을 바로 세우고 회전 표시를 없앤다. 제목을 문서 이름으로. 실패하면 예외."""
    gs = gs or gs_exe()
    if not gs:
        raise FileNotFoundError("Ghostscript(printer\\bin\\gs) 없음")
    tmp = out_pdf + ".gs.pdf"
    args = [gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.7",
            "-dAutoRotatePages=/None", "-dEmbedAllFonts=true", "-dSubsetFonts=true"]
    if gray:
        args += ["-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray"]
    args += ["-sOutputFile=" + tmp, ps_path]
    env = dict(os.environ)
    env["GS_LIB"] = ""                      # 다른 Ghostscript 설치의 설정을 읽지 않게
    r = subprocess.run(args, capture_output=True, creationflags=_NO_WINDOW, env=env, timeout=600)
    if r.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("Ghostscript %d: %s" % (r.returncode, (r.stderr or r.stdout or b"")[-400:].decode("utf-8", "replace")))
    import fitz
    land = is_landscape(ps_path)
    d = fitz.open(tmp)
    try:
        for pg in d:
            if land and pg.rect.width < pg.rect.height:
                pg.set_rotation((pg.rotation + 90) % 360)
            if pg.rotation:
                pg.remove_rotation()           # 보이는 방향 그대로 놓는다(알PDF 의 회전 표시 흠 — SOT §3.10)
        meta = dict(d.metadata or {})
        meta["title"] = title or meta.get("title", "")
        meta["creator"] = "PolyPDF virtual printer"
        d.set_metadata(meta)
        d.save(out_pdf, garbage=3, deflate=True)
    finally:
        d.close()
    try:
        os.remove(tmp)
    except OSError:
        pass


def to_gray(src_pdf: str, out_pdf: str, gs: str | None = None) -> None:
    """저장 창에서 흑백을 고르면 — 벡터 그대로 회색조로(Ghostscript)."""
    gs = gs or gs_exe()
    if not gs:
        raise FileNotFoundError("Ghostscript 없음")
    env = dict(os.environ)
    env["GS_LIB"] = ""
    r = subprocess.run([gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", "-dAutoRotatePages=/None",
                        "-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray",
                        "-sOutputFile=" + out_pdf, src_pdf], capture_output=True, creationflags=_NO_WINDOW, env=env, timeout=600)
    if r.returncode != 0 or not os.path.isfile(out_pdf):
        raise RuntimeError("Ghostscript %d" % r.returncode)


# ── 사용자별 예약 작업 ─────────────────────────────────────────────────
def task_name() -> str:
    return TASK_PREFIX + user_name()


def _task_xml(exe_cmd: str, args: str) -> str:
    from xml.sax.saxutils import escape
    return ("<?xml version=\"1.0\" encoding=\"UTF-16\"?>\n"
            "<Task version=\"1.2\" xmlns=\"http://schemas.microsoft.com/windows/2004/02/mit/task\">\n"
            "  <RegistrationInfo><Description>PolyPDF virtual printer - opens printed PDFs</Description></RegistrationInfo>\n"
            "  <Principals><Principal id=\"Author\"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>\n"
            "  <Settings><MultipleInstancesPolicy>Queue</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
            "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><AllowStartOnDemand>true</AllowStartOnDemand>"
            "<Hidden>true</Hidden></Settings>\n"
            "  <Actions Context=\"Author\"><Exec><Command>%s</Command><Arguments>%s</Arguments></Exec></Actions>\n"
            "</Task>\n") % (escape(exe_cmd), escape(args))


def launch_command() -> tuple:
    """예약 작업이 부를 명령 — 설치본은 PolyPDF.exe, 개발 실행은 python main.py."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--printed"
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return sys.executable, '"%s" --printed' % main


def task_command():
    """지금 등록된 작업의 (명령, 인자) — 없으면 None."""
    r = subprocess.run(["schtasks", "/query", "/tn", task_name(), "/xml"], capture_output=True, creationflags=_NO_WINDOW)
    if r.returncode != 0:
        return None
    raw = r.stdout
    try:
        txt = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("mbcs", "replace")
    except Exception:
        txt = raw.decode("utf-8", "replace")
    c = re.search(r"<Command>(.*?)</Command>", txt, re.S)
    a = re.search(r"<Arguments>(.*?)</Arguments>", txt, re.S)
    from xml.sax.saxutils import unescape
    return (unescape(c.group(1)) if c else "", unescape(a.group(1)) if a else "")


def ensure_task() -> bool:
    """사용자별 예약 작업을 지금 실행 파일로 맞춘다(없거나 다르면 만든다). 바꿨으면 True."""
    exe, args = launch_command()
    cur = task_command()
    if cur and os.path.normcase(cur[0]) == os.path.normcase(exe) and cur[1] == args:
        return False
    fd, xml = tempfile.mkstemp(suffix=".xml", prefix="polypdf_task_")
    os.close(fd)
    try:
        with open(xml, "w", encoding="utf-16") as f:
            f.write(_task_xml(exe, args))
        r = subprocess.run(["schtasks", "/create", "/tn", task_name(), "/xml", xml, "/f"],
                           capture_output=True, creationflags=_NO_WINDOW)
        return r.returncode == 0
    finally:
        try:
            os.remove(xml)
        except OSError:
            pass
