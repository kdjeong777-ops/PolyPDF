# -*- coding: utf-8 -*-
"""261017(가상 프린터 SOT §4.3·§4.4·§4.8): 가상 프린터로 받은 문서의 저장·여는 흐름(창 쪽). 창 흐름의 Ghostscript 변환은 가짜로 바꾼다.

G. Ghostscript 변환 — PScript5 가 OpenType(CFF) 글꼴을 CIDFont 로 찾는 PS 도 바뀐다(261017-14), 이름 기반 CFF 의 SID 글자표(261017-16)
O. 쪽 방향 — 글 방향으로 바로 세운다('한 장에 2쪽' 을 다시 눕히지 않는다, 261017-16)
B. 저장 창 없이 바로 저장(261017-14) — 원래 파일 폴더에 원래 이름으로, 같은 이름이면 '이름 (1).pdf' (사용자 결정 261017-6) · 받은 PS 는 지운다 · 흑백 설정
C. 원래 파일이 없으면 기본 저장 폴더 · 이름 다듬기(프로그램 이름·'[읽기 전용]' 떼기, 못 쓰는 글자)
D. 여는 곳 — 저장 폴더를 이 창이 보고 있으면 목록 다시 읽기 + 본문, 다른 폴더면 새 창
E. 변환 실패면 PS 를 남긴다(잃지 않게)
Q. 연이어 인쇄 — 예약 작업은 'Parallel', 옛 'Queue' 작업은 다시 만든다(261031-2)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_vprinter_recv_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def mkpdf(path, n=3, land=False):
    d = fitz.open()
    for i in range(n):
        pg = d.new_page(width=842 if land else 595, height=595 if land else 842)
        pg.insert_text((72, 72), "page %d" % (i + 1))
    d.save(str(path)); d.close()


from viewer import vprinter_recv as R
import viewer.widgets.print_dialog as PD

root = Path(tempfile.mkdtemp(prefix="vprinter_recv_"))
spool, orig_dir, dflt = root / "spool", root / "원래", root / "기본"
for d_ in (spool, orig_dir):
    d_.mkdir()

print("=== G. Ghostscript 변환 ===")
# 261017-14 실제 인쇄: PowerPoint 의 OpenType(CFF) 글꼴(S-Core Dream)을 PScript5 는 definefont 로 정의하고
#   T0AddCFFMtx2 에서 같은 이름을 CIDFont 로 찾아 /Metrics2 를 쓴다 — Ghostscript 는 undefinedresource 로 변환 전체가 실패했다
import subprocess
gs = R.gs_exe() or next((p for p in (r"C:\Program Files\PolyPDF\_internal\printer\bin\gs\gswin64c.exe",) if os.path.isfile(p)), None)
if not gs:
    print("SKIP - Ghostscript 없음(printer\\bin\\gs 또는 설치본)")
else:
    ps_cff = root / "cff.ps"
    ps_cff.write_bytes(b"%!PS\n"
                       b"/Helvetica findfont dup length dict begin { 1 index /FID ne { def } { pop pop } ifelse } forall\n"
                       b"/FontName /PolyTestCFF def currentdict end /PolyTestCFF exch definefont pop\n"
                       b"/PolyTestCFF /CIDFont findresource /Metrics2 get begin 1 [0 -1000 500 0] def end\n"
                       b"/Helvetica findfont 20 scalefont setfont 72 700 moveto (CFF ok) show showpage\n")
    raw = subprocess.run([gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", "-sOutputFile=" + str(root / "raw.pdf"),
                          str(ps_cff)], capture_output=True, timeout=120)
    chk(raw.returncode != 0, "G1 (재현) 손대지 않은 Ghostscript 는 이 PS 에서 실패한다", str(raw.returncode))
    out_cff = root / "cff.pdf"
    try:
        R.convert(str(ps_cff), str(out_cff), title="cff", gs=gs)
        err = ""
    except Exception as ex:                     # noqa: BLE001
        err = repr(ex)[:200]
    ok = out_cff.is_file()
    chk(ok and "CFF ok" in fitz.open(str(out_cff))[0].get_text(), "G2 convert() 는 CIDFont 로 찾는 CFF 글꼴 PS 도 바꾼다", err)
    # 261017-16 실제 인쇄: 이름 기반 CFF 글꼴은 코드 = 글리프 이름의 CFF 문자열 번호(SID) — 표가 없으면 제목·띠 글이 빈 글자로 그려졌다.
    #   Helvetica 사본을 그런 글꼴처럼 묶고(코드 391·392·600 → /A·/B·/C) 앞머리 표로 그려지는지·글이 추출되는지 본다
    from viewer.vprinter_recv import _CFF_COMPOSE, _PS_PROLOG
    pro = root / "cff_pro.ps"
    pro.write_text("/PolyPDF_CFFMAP << /TESTAA+Fake << 391 /A 392 /B 600 /C >> >> def\n"
                   "/PolyPDF_CFFG2U << /TESTAA+Fake << /A 65 /B 66 /C 67 >> >> def\n" + _CFF_COMPOSE + _PS_PROLOG + "\n", encoding="latin-1")
    sid_ps = root / "sid.ps"
    sid_ps.write_bytes(b"%!PS\n/Helvetica findfont dup length dict begin { 1 index /FID ne { def } { pop pop } ifelse } forall\n"
                       b"/FontName /TESTAA+Fake def currentdict end /TESTAA+Fake exch definefont pop\n"
                       b"/FakeH /WinCharSetFFFF-H [/TESTAA+Fake] composefont pop\n"
                       b"/TESTAA+Fake /CIDFont findresource /Metrics2 get begin 391 [0 -1000 500 0] def end\n"
                       b"/FakeH findfont 40 scalefont setfont 72 700 moveto <0187018802580187> show showpage\n")
    r4 = subprocess.run([gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", "-sOutputFile=" + str(root / "sid.pdf"),
                         str(pro), str(sid_ps)], capture_output=True, timeout=120)
    t4 = fitz.open(str(root / "sid.pdf"))[0].get_text().strip() if r4.returncode == 0 else r4.stderr[-200:]
    chk(t4 == "ABCA", "G3 SID 표로 묶은 CFF 글꼴의 글자가 그려지고 글로 추출된다(빈 글자 아님)", repr(t4))
    # 표 만들기 — 이름 기반 CFF OTF 를 fontTools 로 만들어 설치 폴더처럼 두고, PScript5 꼴 PS 에서 표를 만든다
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    fdir = root / "fonts"; fdir.mkdir()
    names = [".notdef", "_1", "_2", "_3"]
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({0xC81C: "_2", 0xC548: "_3"})          # 제·안
    cs = {}
    for n in names:
        pen = T2CharStringPen(500, None); pen.moveTo((0, 0)); pen.lineTo((400, 0)); pen.lineTo((400, 600)); pen.closePath()
        cs[n] = pen.getCharString()
    fb.setupCFF("PolyTest-Bold", {"FullName": "PolyTest Bold"}, cs, {})
    fb.setupHorizontalMetrics({n: (500, 0) for n in names}); fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "PolyTest", "styleName": "Bold", "psName": "PolyTest-Bold"})
    fb.setupOS2(); fb.setupPost(); fb.save(str(fdir / "polytest.otf"))
    gps = root / "cff_doc.ps"
    gps.write_bytes(b"%!FontType1\n14 dict begin\n/FontName /QWERTY+PolyTest-Bold def\ncurrentdict end\n"
                    b"/_2 5 -| 00 |-\n/_3 5 -| 00 |-\n/QWERTY+PolyTest-BoldH /WinCharSetFFFF-H [/QWERTY+PolyTest-Bold] composefont pop\n")
    prol = R.cff_prolog(str(gps), dirs=[str(fdir)])
    chk("/QWERTY+PolyTest-Bold << 392 /_2 393 /_3 >>" in prol and "/_2 51228" in prol and "/_1" not in prol,
        "G4 PS 의 이름 기반 CFF 글꼴을 설치된 OTF 에서 찾아 SID→이름·이름→유니코드 표를 만든다(온 글리프만)", prol[:300])

print("\n=== O. 쪽 방향 ===")
# 261017-16 실제 인쇄: '한 장에 2쪽' 은 머리가 Landscape 여도 종이가 이미 바로 서 있다 — 머리만 보고 돌려 눕혔다
od = fitz.open()
p_up = od.new_page(width=595, height=842); p_up.insert_text((72, 100), "upright text 가나다", fontname="helv")
p_side = od.new_page(width=595, height=842); p_side.insert_text((300, 100), "sideways text here", fontname="helv", rotate=90)
p_down = od.new_page(width=595, height=842); p_down.insert_text((300, 700), "sideways other way", fontname="helv", rotate=270)
od.new_page(width=595, height=842)                                   # 글 없는 쪽
rots = R.upright_pages(od, True, 2)
chk(rots[0] == 0, "O1 글이 가로인 쪽은 머리가 Landscape·2쪽 모아 찍기여도 돌리지 않는다", str(rots))
for i, rr in ((1, rots[1]), (2, rots[2])):
    pg = od[i]; pg.set_rotation(rr); pg.remove_rotation() if rr else None
    chk(R.text_rotation(od[i]) == 0, "O2 옆으로 누운 글의 쪽은 글이 가로가 되게 돌린다(쪽 %d → %d°)" % (i + 1, rr), str(rots))
chk(rots[3] == 0, "O3 글 없는 쪽은 문서의 다수 결정을 따른다", str(rots))
e = fitz.open(); e.new_page(width=595, height=842)
chk(R.upright_pages(e, True, 1) == [90] and R.upright_pages(e, True, 2) == [0], "O4 문서에 글이 없으면 머리 규칙(가로·1쪽씩일 때만 90°)")

print("\n=== C. 이름 다듬기 ===")
chk(R.clean_title("Microsoft PowerPoint - 계획.pptx [읽기 전용]") == "계획.pptx", "C1 프로그램 이름·[읽기 전용] 떼기")
chk(R.safe_stem("..\\a/b:c") == "_a_b_c" or "\\" not in R.safe_stem("..\\a/b:c") and "/" not in R.safe_stem("..\\a/b:c"), "C2 경로 문자 걸러냄", R.safe_stem("..\\a/b:c"))
chk(R.job_title("C:\\s\\7-0001 Microsoft Word - 보고.docx.ps") == "Microsoft Word - 보고.docx", "C3 이름 규칙에서 문서 이름")

print("\n=== B·D·E. 창 흐름 ===")
from viewer.app import MainWindow
mw = MainWindow(); mw._skip_save_on_close = True
msgs = []
QMessageBox.warning = staticmethod(lambda *a, **k: msgs.append(a[2] if len(a) > 2 else ""))
orig_file = orig_dir / "계획.pptx"; orig_file.write_bytes(b"pptx")
R.user_spool_dir = lambda: str(spool)
R.find_original = lambda name: str(orig_file) if name == "계획.pptx" else None
R.default_save_dir = lambda: str(dflt)
chk(R.is_temp_dir(str(orig_dir)), "C4 임시 폴더 아래의 원래 파일은 원래 폴더로 쓰지 않는다(검사 폴더가 TEMP 아래)")
R.is_temp_dir = lambda d: False          # 아래 흐름 검사는 '원래 폴더' 가 보통 폴더라고 본다
conv_calls = []


def fake_convert(ps, out, title="", gray=False, gs=None):
    conv_calls.append(title)
    if "실패" in ps:
        raise RuntimeError("가짜 변환 실패")
    mkpdf(out, 2)


R.convert = fake_convert
grays = []
R.to_gray = lambda src, out, gs=None: (grays.append(out), shutil.copyfile(src, out))
mw._prefs["vprinter"] = {"kind": "original", "color": "color"}      # 기본 설정 그대로(종전 '저장 창 없이' 를 켜지 않은 상태)
dialogs = []
PD.PrintScopeDialog.exec = lambda self: dialogs.append(1) or 0      # 종전 판은 여기서 저장 창을 띄웠다(취소 = 저장 안 함)
opened, newwin = [], []
mw._vprinter_new_window = lambda p: newwin.append(p)
mw._load_main = lambda item: opened.append(item.file if hasattr(item, "file") else str(item))
refreshed, added, saved_open = [], [], []
mw.bookmark_tree.refresh = lambda: refreshed.append(1)
mw.bookmark_tree.add_or_refresh_file = lambda p, after=None: added.append(p)
mw._open_saved_file = lambda p, page=None: saved_open.append(p)
# 261017-18 점검: 임시 폴더 만들기·PS 지우기가 메인 스레드에서 돌았다 — 어느 스레드에서 부르는지 적는다
import threading
_mk = tempfile.mkdtemp
_rm = os.remove
fileops_main = []
tempfile.mkdtemp = lambda *a, **k: (fileops_main.append(("mkdtemp", threading.current_thread() is threading.main_thread())), _mk(*a, **k))[1]


def _rm_spy(p, *a, **k):
    if str(p).endswith(".ps"):
        fileops_main.append(("remove", threading.current_thread() is threading.main_thread()))
    return _rm(p, *a, **k)


os.remove = _rm_spy
old = time.time() - 10
for name in ("3-0001 Microsoft PowerPoint - 계획.pptx.ps", "4-0001 Microsoft PowerPoint - 계획.pptx.ps", "5-0001 웹 페이지 제목.ps"):
    p = spool / name; p.write_bytes(b"%!PS"); os.utime(p, (old, old))
mw._folder = orig_dir                    # 이 창이 원래 폴더를 보고 있다
mw._vprinter_receive()
chk(not dialogs, "B0 저장 창(인쇄 창)을 띄우지 않고 바로 저장한다(261017-14)", str(len(dialogs)))
chk((orig_dir / "계획.pdf").is_file() and (orig_dir / "계획 (1).pdf").is_file(), "B1 원래 폴더에 원래 이름, 둘째는 (1)",
    str(sorted(x.name for x in orig_dir.iterdir())))
chk((dflt / "웹 페이지 제목.pdf").is_file(), "B2 원래 파일이 없는 문서는 기본 저장 폴더에", str(list(dflt.glob("*")) if dflt.exists() else "없음"))
chk(not list(spool.glob("*.ps")), "B3 받은 PS 는 지운다")
d = fitz.open(str(orig_dir / "계획.pdf")); chk(d.page_count == 2, "B4 받은 PDF 를 그대로(쪽 수)"); d.close()
chk(not refreshed and len(added) == 2 and len(saved_open) == 2 and all("계획" in s for s in saved_open),
    "D1 같은 폴더 → 그 파일만 목록에 더하고 _open_saved_file 로 연다(폴더 전체 다시 읽기 없음, 261017-18)",
    "refresh %d · add %s · open %s" % (len(refreshed), added, saved_open))
chk(fileops_main and not any(m for _, m in fileops_main), "D3 임시 폴더 만들기·PS 지우기는 배경 스레드에서(261017-18)", str(fileops_main))
chk(len(newwin) == 1 and newwin[0].endswith("웹 페이지 제목.pdf"), "D2 다른 폴더 → 새 창", str(newwin))
# 261017 손 확인: 모니터는 파일을 닫자마자 알린다 — 방금 쓴 파일도 처리해야 한다(종전엔 1초 안 된 파일을 건너뛰어 첫 인쇄를 놓쳤다)
fresh = spool / "8-0001 Microsoft PowerPoint - 계획.pptx.ps"; fresh.write_bytes(b"%!PS")
mw._vprinter_receive()
chk(not fresh.exists() and (orig_dir / "계획 (2).pdf").is_file(), "B5 방금 쓴 PS 도 곧바로 처리한다", str(sorted(x.name for x in orig_dir.iterdir())))
chk(not grays, "B6a 컬러 설정이면 흑백으로 바꾸지 않는다")
mw._prefs["vprinter"] = {"kind": "original", "color": "gray"}
gp = spool / "10-0001 Microsoft PowerPoint - 계획.pptx.ps"; gp.write_bytes(b"%!PS")
mw._vprinter_receive()
chk(len(grays) == 1 and grays[0].endswith("계획 (3).pdf"), "B6 도구 메뉴의 '흑백으로 저장' 이면 흑백으로", str(grays))
p = spool / "9-0001 실패 문서.ps"; p.write_bytes(b"%!PS"); os.utime(p, (old, old))
mw._vprinter_receive()
chk(p.exists() and msgs, "E1 변환 실패면 PS 를 남기고 알린다", str(msgs[-1:] if msgs else ""))
# 261017-18 점검: 실패한 PS 를 알림마다 다시 시도해 경고가 되풀이됐다 — 이 창에서는 한 번만
n_msgs, n_conv = len(msgs), len(conv_calls)
mw._vprinter_receive(); mw._vprinter_receive()
chk(len(msgs) == n_msgs and len(conv_calls) == n_conv and p.exists(), "E2 실패한 PS 는 이 창에서 다시 시도·경고하지 않는다(지우지도 않는다)",
    "경고 %d→%d · 변환 %d→%d" % (n_msgs, len(msgs), n_conv, len(conv_calls)))
tempfile.mkdtemp, os.remove = _mk, _rm

print("\n=== T. 예약 작업은 설치본 창만 ===")
# 261017-18 점검: 개발 main.py·휴대용·시험 프로필 창이 사용자의 예약 작업을 자기 쪽으로 바꿨다(e2e --dev 때 실제로)
import viewer.vprinter_controller as VC
ens = []
_ens, _inst = R.ensure_task, VC._printer_installed
R.ensure_task = lambda: ens.append(1) or True
VC._printer_installed = lambda: True
outs = []
w = VC._StartWorker(); w.finished.connect(outs.append); w.run()
chk(not ens and not R.task_owner(), "T1 개발 실행(빌드된 exe 아님)은 예약 작업을 바꾸지 않는다", str(outs))
sys.frozen = True
try:
    os.environ["POLYPDF_PROFILE"] = "test"
    w.run()
    chk(not ens, "T2 시험 프로필 창도 바꾸지 않는다")
    os.environ.pop("POLYPDF_PROFILE", None)
    import viewer.settings_store as SS
    _port = getattr(SS, "PORTABLE", False)
    SS.PORTABLE = True
    w.run()
    chk(not ens, "T3 휴대용도 바꾸지 않는다")
    SS.PORTABLE = False
    w.run()
    chk(len(ens) == 1, "T4 설치본(빌드된 exe·휴대용 아님·시험 프로필 아님)만 맞춘다", str(ens))
    SS.PORTABLE = _port
finally:
    del sys.frozen
    R.ensure_task, VC._printer_installed = _ens, _inst

print("\n=== Q. 연이어 인쇄 — 예약 작업은 겹쳐 실행(261031-2) ===")
# 사용자 보고: 창이 없을 때 인쇄하면 --printed 실행이 그대로 창이 되어 작업 인스턴스가 살아 있고, 'Queue' 정책이라
#   두 번째 인쇄의 작업이 그 창이 닫힐 때까지 줄에서 기다려 PDF 가 만들어지지 않았다(이 PC 작업이 실제로 Queue 였다)
xml = R._task_xml(r"C:\Program Files\PolyPDF\PolyPDF.exe", "--printed")
chk("<MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>" in xml, "Q1 새 예약 작업은 'Parallel' — 두 번째 실행이 곧바로 받는 창에 넘긴다")
_run, _lc = R.subprocess.run, R.launch_command
calls = []


class _R:
    def __init__(self, rc=0, out=b""):
        self.returncode, self.stdout = rc, out


def _fake_run(args, **k):
    calls.append(list(args))
    if "/query" in args:
        return _R(0, R._task_xml(r"C:\P\PolyPDF.exe", "--printed").replace("Parallel", "Queue").encode("utf-16"))
    return _R(0)


R.subprocess.run = _fake_run
R.launch_command = lambda: (r"C:\P\PolyPDF.exe", "--printed")
try:
    changed = R.ensure_task()
    chk(changed and any("/create" in c for c in calls), "Q2 이미 있는 옛 'Queue' 작업은 명령이 같아도 다시 만든다(업데이트한 설치본)", str(calls))
    calls.clear()
    R.subprocess.run = lambda args, **k: (calls.append(list(args)),
                                          _R(0, R._task_xml(r"C:\P\PolyPDF.exe", "--printed").encode("utf-16")) if "/query" in args else _R(0))[1]
    chk(not R.ensure_task() and not any("/create" in c for c in calls), "Q3 이미 'Parallel' 이면 건드리지 않는다", str(calls))
finally:
    R.subprocess.run, R.launch_command = _run, _lc
print("\n=== F. 도구 메뉴 ===")
from PyQt6.QtGui import QAction
texts = [a.text() for a in mw.findChildren(QAction)]
# 261025-1(디자인 SOT §2.9.1): 도구 탭 '등록·설치 ▾' 안의 '가상 프린터 설치·제거…'(명령 id tools.vprinter 그대로)
_vp = (getattr(mw, "_cmds", {}) or {}).get("tools.vprinter")
_inst = (getattr(mw, "_cmds", {}) or {}).get("tools.install")
chk(_vp is not None and _vp.text().startswith("가상 프린터 설치·제거") and _inst is not None
    and _vp in _inst.menu().actions(), "F1 도구 탭 '등록·설치 ▾' 에 '가상 프린터 설치·제거…'")
from viewer.widgets.vprinter_dialog import VPrinterDialog
import viewer.widgets.vprinter_dialog as VD
VD.read_state = lambda: {"support": "ok", "monitor": False, "dll": False, "port": False, "driver": False,
                         "printer": False, "ppd": False, "spool": False, "default": False}
vd = VPrinterDialog(mw, {"kind": "default", "default_dir": str(dflt), "skip": True, "color": "color"})
t0 = time.time()
while time.time() - t0 < 3 and vd.lbl_state.text().startswith("상태 확인"):
    app.processEvents(); time.sleep(0.02)
chk(vd.lbl_state.text() == "설치되지 않음" and vd.btn_install.text() == "설치" and vd.btn_install.isEnabled()
    and not vd.btn_remove.isEnabled(), "F2 설치 안 됨 — 설치 단추만", vd.lbl_state.text())
vd._show_state({"support": "ok", "monitor": True, "dll": True, "port": True, "driver": True, "printer": True})
chk(vd.btn_install.text() == "수리" and vd.btn_remove.isEnabled(), "F3 설치됨 — 수리·제거")
vd._show_state({"support": "arm64", "printer": False, "monitor": False})
chk(not vd.btn_install.isEnabled() and "ARM64" in vd.lbl_state.text(), "F4 쓸 수 없는 PC 는 까닭을 보이고 설치하지 않는다")
vd._done("install", VD.STILL_RUNNING)
chk("진행 중" in vd.lbl_state.text() and "실패" not in vd.lbl_state.text(),
    "F6 관리자 실행을 기다리는 시간이 넘으면 '실패' 가 아니라 '아직 진행 중'(261017-18)", vd.lbl_state.text())
vd.chk_gray.setChecked(True)
rp = vd.result_prefs()
chk(rp["kind"] == "default" and rp["color"] == "gray" and "skip" not in rp and rp["default_dir"] == str(dflt),
    "F5 저장 설정(폴더·흑백)을 돌려주고, 옛 '저장 창 없이' 값은 버린다", str(rp))
vd.reject()
mw._skip_save_on_close = True
mw.close()
shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for f in fails:
    print(" -", f)
sys.stdout.flush()
os._exit(1 if fails else 0)
