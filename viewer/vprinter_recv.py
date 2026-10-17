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

from viewer.i18n import tr
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
        # 제안하는 파일 이름은 만드는 때의 언어로(다국어 SOT §8)
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


def nup_count(ps_path: str) -> int:
    """PScript5 '한 장에 여러 쪽' — 첫 쪽 설정의 `<각> <테> <w> <h> <nx> <ny> definenup` 의 nx×ny(없으면 1)."""
    try:
        with open(ps_path, "rb") as f:
            data = f.read(4 * 1024 * 1024)
    except OSError:
        return 1
    i = data.find(b"%%BeginPageSetup")
    m = re.search(rb"(-?\d+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+definenup", data[i:i + 4000] if i >= 0 else b"")
    return int(m.group(5)) * int(m.group(6)) if m else 1


_DIR_ROT = {(1, 0): 0, (0, 1): 270, (0, -1): 90, (-1, 0): 180}


def text_rotation(page) -> int | None:
    """쪽의 글 줄 방향(글자 수로 가중)으로 바로 세울 회전(시계 방향 0·90·180·270). 글이 없으면 None.
    아래로 흐르는 글(0,1)은 270°, 위로(0,-1)는 90°, 거꾸로(-1,0)는 180°(가상 프린터 SOT §4.1, 261017-16)."""
    votes = {}
    for b in page.get_text("dict").get("blocks", []):
        for ln in b.get("lines", []):
            n = sum(len(s.get("text", "").strip()) for s in ln.get("spans", []))
            key = tuple(int(round(v)) for v in ln.get("dir", (1, 0)))
            if n and key in _DIR_ROT:
                votes[_DIR_ROT[key]] = votes.get(_DIR_ROT[key], 0) + n
    return max(votes, key=votes.get) if votes else None


def upright_pages(doc, landscape: bool, nup: int) -> list:
    """쪽마다 바로 세울 회전. 글 방향이 우선, 글이 없는 쪽은 문서의 다수 결정, 문서 전체에 글이 없으면
    머리 규칙(가로이고 1쪽씩일 때만 90°) — 머리만 보면 '한 장에 2쪽' 을 다시 눕혔다(261017-16)."""
    rots = [text_rotation(pg) for pg in doc]
    known = [r for r in rots if r is not None]
    if known:
        fallback = max(set(known), key=known.count)
    else:
        fallback = 90 if landscape and nup == 1 else 0
    return [fallback if r is None else r for r in rots]


# ── 이름 기반 CFF 글꼴(261017-16, 가상 프린터 SOT §4.1) ─────────────────────
# PScript5 는 OpenType(CFF, 이름 기반) 글꼴을 `%!FontType1` 글로 보내고 composefont(CMap WinCharSetFFFF-H = 코드 그대로)로 묶는데,
# 코드는 그 글리프 이름의 CFF 문자열 번호(SID)다. Ghostscript 는 이 대응을 몰라 빈 글자를 그렸다 → 설치된 OTF 에서 SID → 이름 표를 만든다.
_CFF_RE = re.compile(rb"%!FontType1\b.{0,4000}?/FontName /(\S+) def", re.S)
_GLYPH_RE = re.compile(rb"^/(\S+) \d+ -\|", re.M)


def _font_dirs() -> list:
    out = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
    la = os.environ.get("LOCALAPPDATA")
    if la:
        out.append(os.path.join(la, "Microsoft", "Windows", "Fonts"))
    return out


def find_otf(ps_name: str, dirs=None):
    """PostScript 이름(name ID 6)이 같은 설치된 .otf(CFF) 경로. 없으면 None."""
    try:
        from fontTools.ttLib import TTFont
    except Exception:
        return None
    for d in dirs or _font_dirs():
        for p in glob.glob(os.path.join(d, "*.otf")):
            try:
                f = TTFont(p, lazy=True, fontNumber=0)
                nm = f["name"].getDebugName(6)
                ok = nm == ps_name and "CFF " in f
                f.close()
            except Exception:
                continue
            if ok:
                return p
    return None


def cff_tables(otf_path: str, wanted=None):
    """이름 기반 CFF 의 ({SID: 글리프 이름}, {글리프 이름: 유니코드}). `wanted`(이름 집합)가 있으면 그 글리프만.
    CID 기반이면 빈 표 — PScript5 가 진짜 CIDFont 로 보내 Ghostscript 가 그대로 읽는다."""
    from fontTools.ttLib import TTFont
    f = TTFont(otf_path, lazy=True)
    try:
        cff = f["CFF "].cff
        top = cff.topDictIndex[0]
        if hasattr(top, "ROS"):
            return {}, {}
        strings = cff.strings
        sids, uni = {}, {}
        for name in top.charset:
            if wanted is not None and name not in wanted:
                continue
            sids[strings.getSID(name)] = name
        for cp, name in (f.getBestCmap() or {}).items():
            if name in sids.values() and name not in uni:
                uni[name] = cp
        return sids, uni
    finally:
        f.close()


def _ps_name(s: str) -> str:
    """PS 이름을 앞머리에 그대로 쓸 수 있게(이름 글자만)."""
    return re.sub(r"[^A-Za-z0-9_.+\-]", "", s)


def cff_prolog(ps_path: str, dirs=None) -> str:
    """PS 에 이름 기반 CFF 글꼴이 있으면 `/PolyPDF_CFFMAP << /<글꼴> << SID /이름 … >> … >> def` 와
    `/PolyPDF_CFFG2U << /<글꼴> << /이름 유니코드 … >> … >> def`(글 추출용)를 돌려준다(없으면 '')."""
    try:
        with open(ps_path, "rb") as f:
            data = f.read()
    except OSError:
        return ""
    fonts = {}
    for m in _CFF_RE.finditer(data):
        full = m.group(1).decode("latin-1")
        if (b"[/" + m.group(1) + b"] composefont") in data:
            fonts[full] = full.split("+", 1)[-1]
    if not fonts:
        return ""
    wanted = {g.decode("latin-1") for g in _GLYPH_RE.findall(data)}
    maps, g2us = [], []
    for full, base in fonts.items():
        otf = find_otf(base, dirs)
        if not otf:
            continue
        sids, uni = cff_tables(otf, wanted)
        if sids:
            fn = _ps_name(full)
            maps.append("/%s << %s >>" % (fn, " ".join("%d /%s" % (s, _ps_name(n)) for s, n in sorted(sids.items()))))
            g2us.append("/%s << %s >>" % (fn, " ".join("/%s %d" % (_ps_name(n), cp) for n, cp in sorted(uni.items()))))
    if not maps:
        return ""
    return "/PolyPDF_CFFMAP << %s >> def\n/PolyPDF_CFFG2U << %s >> def\n" % (" ".join(maps), " ".join(g2us))


# 이름 기반 CFF 글꼴을 composefont 로 묶을 때(CMap WinCharSetFFFF-H, 글꼴 하나) 표가 있으면 FMapType 2(8/8) 복합 글꼴로 만든다 —
# 코드의 윗 바이트로 하위 글꼴(같은 CharStrings·Private 를 쓰는 사본, Encoding 만 다름)을 고르고 아랫 바이트로 글리프 이름을 고른다.
# 0번 하위 글꼴은 모두 .notdef(표에 없는 코드가 엉뚱한 글자로 그려지지 않게).
_CFF_COMPOSE = r"""
/PolyPDF_CFFMAP where { pop } { /PolyPDF_CFFMAP 0 dict def /PolyPDF_CFFG2U 0 dict def } ifelse
/PolyPDF_T 16 dict def PolyPDF_T /seq 0 put
/PolyPDF_sub {
  //PolyPDF_T /enc 3 -1 roll put
  dup length 2 add dict begin
    { 1 index /FID eq { pop pop } { def } ifelse } forall
    /Encoding //PolyPDF_T /enc get def
    /FontInfo currentdict /FontInfo known { FontInfo dup length 1 add dict copy } { 1 dict } ifelse
      dup /GlyphNames2Unicode //PolyPDF_T /g2u get put def
  currentdict end
  (PPCFF___________) dup length string copy dup 5 11 getinterval //PolyPDF_T /seq get exch cvs pop cvn
  //PolyPDF_T /seq 2 copy get 1 add put
  exch definefont
} bind def
/composefont {
  dup length 1 eq 2 index /WinCharSetFFFF-H eq and
  { dup 0 get dup type /nametype eq { //PolyPDF_CFFMAP exch known } { pop false } ifelse } { false } ifelse
  { //PolyPDF_T begin
      0 get /fn exch def pop /nm exch def
      /g2u //PolyPDF_CFFG2U fn known { //PolyPDF_CFFG2U fn get } { 0 dict } ifelse def
      /base fn /Font findresource def
      /encs 256 array def
      //PolyPDF_CFFMAP fn get {
        exch dup -8 bitshift encs 1 index get null eq
        { encs 1 index 256 array 0 1 255 { 1 index exch /.notdef put } for put } if
        encs exch get exch 255 and 3 -1 roll put
      } forall
      /e0 256 array def /idx 1 def
      /fdep [ base 256 array 0 1 255 { 1 index exch /.notdef put } for //PolyPDF_sub exec
        0 1 255 { /hi exch def
          encs hi get null ne
          { e0 hi idx put /idx idx 1 add def base encs hi get //PolyPDF_sub exec }
          { e0 hi 0 put } ifelse
        } for ] def
      10 dict begin
        /FontType 0 def /FMapType 2 def /FontMatrix [1 0 0 1 0 0] def /WMode 0 def
        /Encoding e0 def /FDepVector fdep def /FontName nm def
      currentdict end
      nm exch definefont
    end }
  { //composefont exec } ifelse
} bind def
"""


# 261017-14: PowerPoint 가 OpenType(CFF) 글꼴(예: S-Core Dream)을 쓰면 PScript5 는 그 글꼴을 Font 로 정의(definefont)하고
#   composefont 뒤 `T0AddCFFMtx2` 에서 같은 이름을 **CIDFont** 로 찾아 `/Metrics2`(세로쓰기 너비)에 넣는다. Adobe 해석기는 그렇게
#   찾아지지만 Ghostscript 는 undefinedresource 로 변환이 통째로 실패했다. → CIDFont 로 못 찾고 같은 이름의 Font 가 있을 때만
#   `/Metrics2` 하나를 가진 대리 사전을 돌려준다(글자 모양은 composefont 가 Font 로 이미 묶었다 — 세로쓰기 너비만 잃는다).
_PS_PROLOG = (
    "/PolyPDF_M2 64 dict def "
    "/findresource { dup /CIDFont eq "
    "{ 1 index /CIDFont resourcestatus { pop pop //findresource exec } "
    "{ 1 index /Font resourcestatus { pop pop pop "
    "//PolyPDF_M2 1 index known not { //PolyPDF_M2 1 index 2 dict dup /Metrics2 32 dict put put } if "
    "//PolyPDF_M2 exch get } { //findresource exec } ifelse } ifelse } "
    "{ //findresource exec } ifelse } bind def"
)


def convert(ps_path: str, out_pdf: str, title: str = "", gray: bool = False, gs: str | None = None) -> None:
    """PS → PDF(사용자 권한). 쪽을 글 방향으로 바로 세우고 회전 표시를 없앤다. 제목을 문서 이름으로. 실패하면 예외."""
    gs = gs or gs_exe()
    if not gs:
        raise FileNotFoundError("Ghostscript(printer\\bin\\gs) 없음")
    tmp = out_pdf + ".gs.pdf"
    prolog = out_pdf + ".prolog.ps"           # 글자표가 길어 명령 줄(-c)에 넣지 않고 파일로
    with open(prolog, "w", encoding="latin-1", errors="replace") as f:
        f.write(cff_prolog(ps_path) + _CFF_COMPOSE + _PS_PROLOG + "\n")
    args = [gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.7",
            "-dAutoRotatePages=/None", "-dEmbedAllFonts=true", "-dSubsetFonts=true"]
    if gray:
        args += ["-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray"]
    args += ["-sOutputFile=" + tmp, prolog, ps_path]
    env = dict(os.environ)
    env["GS_LIB"] = ""                      # 다른 Ghostscript 설치의 설정을 읽지 않게
    try:
        r = subprocess.run(args, capture_output=True, creationflags=_NO_WINDOW, env=env, timeout=600)
    finally:
        try:
            os.remove(prolog)
        except OSError:
            pass
    if r.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("Ghostscript %d: %s" % (r.returncode, (r.stderr or r.stdout or b"")[-400:].decode("utf-8", "replace")))
    import fitz
    d = fitz.open(tmp)
    try:
        for pg, rot in zip(d, upright_pages(d, is_landscape(ps_path), nup_count(ps_path))):
            if rot:
                pg.set_rotation((pg.rotation + rot) % 360)
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
