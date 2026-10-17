# -*- coding: utf-8 -*-
"""261017(가상 프린터 SOT §4.3·§4.4·§4.8): 가상 프린터로 받은 문서의 저장·여는 흐름(창 쪽). Ghostscript 변환은 가짜로 바꾼다.

A. 저장 창 = 인쇄 창 저장 모드 — 범위(전체·현재·범위)·다단·컬러/흑백·미리보기, 종이 전용 항목 숨김, 저장 폴더·이름, '다음부터 창 없이'
B. 원래 파일 폴더에 원래 이름으로, 같은 이름이면 '이름 (1).pdf' (사용자 결정 261017-6) · 받은 PS 는 지운다
C. 원래 파일이 없으면 기본 저장 폴더 · 이름 다듬기(프로그램 이름·'[읽기 전용]' 떼기, 못 쓰는 글자)
D. 여는 곳 — 저장 폴더를 이 창이 보고 있으면 목록 다시 읽기 + 본문, 다른 폴더면 새 창
E. 변환 실패면 PS 를 남긴다(잃지 않게)
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
from viewer.widgets.print_dialog import PrintScopeDialog

root = Path(tempfile.mkdtemp(prefix="vprinter_recv_"))
spool, orig_dir, dflt = root / "spool", root / "원래", root / "기본"
for d_ in (spool, orig_dir):
    d_.mkdir()
sample = root / "sample.pdf"
mkpdf(sample, 3)

print("=== A. 저장 창 ===")
tgt = {"name": "계획", "orig_dir": str(orig_dir), "default_dir": str(dflt), "folder": str(orig_dir), "reason": "", "skip": False}
dlg = PrintScopeDialog(3, 0, 0, 0, None, sample=str(sample), save_target=tgt)
chk(dlg.windowTitle().startswith("PolyPDF"), "A1 제목이 PolyPDF 프린터 저장 창")
chk(not dlg.rb_shot.isVisibleTo(dlg) and not dlg.rb_files.isVisibleTo(dlg) and dlg.rb_range.isVisibleTo(dlg), "A2 범위는 전체·현재·범위만")
chk(not dlg._pform.isRowVisible(dlg.cmb_printer) and not dlg._pform.isRowVisible(dlg.sp_copies)
    and dlg._pform.isRowVisible(dlg.cmb_color), "A3 종이 전용 항목 숨김, 색상은 보임")
chk(dlg.cmb_color.findData("default") < 0 and dlg.cmb_color.currentData() == "color", "A4 색상은 컬러/흑백(기본 컬러)")
chk(dlg.rb_sv_orig.isChecked() and dlg.to_pdf(), "A5 원래 폴더가 기본, 저장 모드")
chk(dlg.lbl_sv_path.text() == str(orig_dir / "계획.pdf"), "A6 저장될 경로를 미리 보인다", dlg.lbl_sv_path.text())
(orig_dir / "계획.pdf").write_bytes(b"x")
dlg.rb_sv_default.setChecked(True); dlg.rb_sv_orig.setChecked(True)
chk(dlg.lbl_sv_path.text().endswith("계획 (1).pdf"), "A7 같은 이름이 있으면 (1)", dlg.lbl_sv_path.text())
(orig_dir / "계획.pdf").unlink()
dlg.rb_sv_default.setChecked(True)
dlg.cmb_color.setCurrentIndex(dlg.cmb_color.findData("gray")); dlg.chk_sv_skip.setChecked(True)
c = dlg.save_choice()
chk(c["kind"] == "default" and c["folder"] == str(dflt) and c["color"] == "gray" and c["skip"] and c["name"] == "계획", "A8 선택 결과", str(c))
dlg.reject()
t2 = dict(tgt, orig_dir="", reason="notfound", folder=str(dflt))
dlg2 = PrintScopeDialog(3, 0, 0, 0, None, sample=str(sample), save_target=t2)
chk(not dlg2.rb_sv_orig.isEnabled() and dlg2.rb_sv_default.isChecked(), "A9 원래 파일이 없으면 기본 저장 폴더")
dlg2.reject()
dlg3 = PrintScopeDialog(3, 0, 0, 0, None, sample=str(sample))
chk(dlg3._pform.isRowVisible(dlg3.cmb_printer) and dlg3.btn_pdf.isVisibleTo(dlg3) and not dlg3.to_pdf(), "A10 보통 인쇄 창은 그대로")
dlg3.reject()

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
mw._prefs["vprinter"] = {"kind": "original", "skip": True, "color": "color"}
opened, newwin = [], []
mw._vprinter_new_window = lambda p: newwin.append(p)
mw._load_main = lambda item: opened.append(item.file if hasattr(item, "file") else str(item))
refreshed = []
mw.bookmark_tree.refresh = lambda: refreshed.append(1)
old = time.time() - 10
for name in ("3-0001 Microsoft PowerPoint - 계획.pptx.ps", "4-0001 Microsoft PowerPoint - 계획.pptx.ps", "5-0001 웹 페이지 제목.ps"):
    p = spool / name; p.write_bytes(b"%!PS"); os.utime(p, (old, old))
mw._folder = orig_dir                    # 이 창이 원래 폴더를 보고 있다
mw._vprinter_receive()
chk((orig_dir / "계획.pdf").is_file() and (orig_dir / "계획 (1).pdf").is_file(), "B1 원래 폴더에 원래 이름, 둘째는 (1)",
    str(sorted(x.name for x in orig_dir.iterdir())))
chk((dflt / "웹 페이지 제목.pdf").is_file(), "B2 원래 파일이 없는 문서는 기본 저장 폴더에", str(list(dflt.glob("*")) if dflt.exists() else "없음"))
chk(not list(spool.glob("*.ps")), "B3 받은 PS 는 지운다")
d = fitz.open(str(orig_dir / "계획.pdf")); chk(d.page_count == 2, "B4 받은 PDF 를 그대로(쪽 수)"); d.close()
chk(len(refreshed) == 2 and any("계획" in str(o) for o in opened), "D1 같은 폴더 → 목록 다시 읽고 본문에", "%s %s" % (refreshed, opened))
chk(len(newwin) == 1 and newwin[0].endswith("웹 페이지 제목.pdf"), "D2 다른 폴더 → 새 창", str(newwin))
# 261017 손 확인: 모니터는 파일을 닫자마자 알린다 — 방금 쓴 파일도 처리해야 한다(종전엔 1초 안 된 파일을 건너뛰어 첫 인쇄를 놓쳤다)
fresh = spool / "8-0001 Microsoft PowerPoint - 계획.pptx.ps"; fresh.write_bytes(b"%!PS")
mw._vprinter_receive()
chk(not fresh.exists() and (orig_dir / "계획 (2).pdf").is_file(), "B5 방금 쓴 PS 도 곧바로 처리한다", str(sorted(x.name for x in orig_dir.iterdir())))
p = spool / "9-0001 실패 문서.ps"; p.write_bytes(b"%!PS"); os.utime(p, (old, old))
mw._vprinter_receive()
chk(p.exists() and msgs, "E1 변환 실패면 PS 를 남기고 알린다", str(msgs[-1:] if msgs else ""))
print("\n=== F. 도구 메뉴 ===")
from PyQt6.QtGui import QAction
texts = [a.text() for a in mw.findChildren(QAction)]
chk(any(t.startswith("가상 프린터(PolyPDF) 설치·제거") for t in texts), "F1 도구 메뉴에 '가상 프린터(PolyPDF) 설치·제거…'")
from viewer.widgets.vprinter_dialog import VPrinterDialog
import viewer.widgets.vprinter_dialog as VD
VD.read_state = lambda: {"support": "ok", "monitor": False, "dll": False, "port": False, "driver": False,
                         "printer": False, "ppd": False, "spool": False, "default": False}
vd = VPrinterDialog(mw, {"kind": "default", "default_dir": str(dflt), "skip": True})
t0 = time.time()
while time.time() - t0 < 3 and vd.lbl_state.text().startswith("상태 확인"):
    app.processEvents(); time.sleep(0.02)
chk(vd.lbl_state.text() == "설치되지 않음" and vd.btn_install.text() == "설치" and vd.btn_install.isEnabled()
    and not vd.btn_remove.isEnabled(), "F2 설치 안 됨 — 설치 단추만", vd.lbl_state.text())
vd._show_state({"support": "ok", "monitor": True, "dll": True, "port": True, "driver": True, "printer": True})
chk(vd.btn_install.text() == "수리" and vd.btn_remove.isEnabled(), "F3 설치됨 — 수리·제거")
vd._show_state({"support": "arm64", "printer": False, "monitor": False})
chk(not vd.btn_install.isEnabled() and "ARM64" in vd.lbl_state.text(), "F4 쓸 수 없는 PC 는 까닭을 보이고 설치하지 않는다")
rp = vd.result_prefs()
chk(rp["kind"] == "default" and rp["skip"] and rp["default_dir"] == str(dflt), "F5 저장 설정을 돌려준다", str(rp))
vd.reject()
mw._skip_save_on_close = True
mw.close()
shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for f in fails:
    print(" -", f)
sys.stdout.flush()
os._exit(1 if fails else 0)
