"""261017-16(가상 프린터 SOT §6.4): 가상 프린터 자동 대조 도구 — 사용자가 PowerPoint 로 찍어 보던 확인을 대신한다.

Windows·PowerPoint 가 있는 기계에서 개발 코드(`viewer/vprinter_recv.convert`)로 돌린다. 기본 프린터는 시작 때 저장하고 끝에 되돌린다.

  python scripts/vprinter_check.py compare             시험 문서를 만들어 PolyPDF 드라이버로 파일 인쇄 → 변환 → PowerPoint 'PDF로 내보내기' 와 대조
  python scripts/vprinter_check.py ps <PS 파일…>         받은 PS 를 변환해 방향·빈 글자 확인(기본: <작업 폴더>/_samples/vprinter/*.ps)
  python scripts/vprinter_check.py e2e [--dev]         시험 문서를 'PolyPDF' 로 실제 인쇄 → 저장된 PDF·열린 창·빈 스풀 폴더 확인
                                                       (--dev: 개발 코드 창이 받는다 — 코드만 고쳤을 때 설치본을 다시 받지 않는다)
  python scripts/vprinter_check.py install <설치 파일>   조용히 설치(UAC) → 설치 기록의 프린터 단계·상태·기본 프린터 확인

결과: `<작업 폴더>/_review/vprinter_<시각>/summary.md`·`compare.png`. 판정은 종료 코드(0 통과·1 실패).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # public/
WORK = ROOT.parent                                      # 비공개 작업 폴더(_review·_samples)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

PRINTER = "PolyPDF"
INSTALLED_GS = r"C:\Program Files\PolyPDF\_internal\printer\bin\gs\gswin64c.exe"
BANNER = "중동 지역 정세 불안 지속 대응과 성능 기반 시공 지침 개정 요구"


class Report:
    def __init__(self, out: Path):
        self.out, self.rows, self.fails = out, [], 0

    def check(self, ok: bool, what: str, detail: str = ""):
        self.rows.append(("통과" if ok else "**실패**", what, detail))
        if not ok:
            self.fails += 1
        print(("PASS" if ok else "FAIL"), "-", what, detail if not ok else "")

    def note(self, what: str, detail: str = ""):
        self.rows.append(("—", what, detail))
        print("NOTE -", what, detail)

    def write(self, title: str):
        lines = ["# 가상 프린터 대조 — " + title, "", "| 판정 | 항목 | 내용 |", "| --- | --- | --- |"]
        lines += ["| %s | %s | %s |" % (a, b, c.replace("|", "/").replace("\n", " ")) for a, b, c in self.rows]
        lines += ["", "**판정: %s**" % ("통과" if not self.fails else "실패 %d" % self.fails)]
        (self.out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("결과:", self.out)
        return 0 if not self.fails else 1


def out_dir() -> Path:
    p = WORK / "_review" / ("vprinter_" + time.strftime("%y%m%d-%H%M%S"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def gs_path():
    from viewer import vprinter_recv as R
    return R.gs_exe() or (INSTALLED_GS if os.path.isfile(INSTALLED_GS) else None)


# ── 쪽 검사 ────────────────────────────────────────────────────────────
def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def blank_spans(page, dpi: int = 72) -> list:
    """글자 자리에 잉크가 없는 글 조각(빈 글자) — 그 자리를 그려 밝기 변화가 거의 없으면."""
    import fitz
    out = []
    for b in page.get_text("dict").get("blocks", []):
        for ln in b.get("lines", []):
            for s in ln.get("spans", []):
                t = s.get("text", "").strip()
                r = fitz.Rect(s["bbox"])
                if len(t) < 2 or r.is_empty or r.width < 2 or r.height < 2:
                    continue
                pix = page.get_pixmap(clip=r, dpi=dpi, colorspace=fitz.csGRAY)
                px = pix.samples
                if px and max(px) - min(px) < 25:
                    out.append(t[:20])
    return out


def text_off(page):
    """글 줄 방향이 가로가 아닌 정도 — 검사 대상 코드(`text_rotation`)와 따로 잰다(판정이 고친 코드에 기대지 않게).
    가로가 아닌 줄의 글자가 더 많으면 그 방향(dx,dy), 아니면 None."""
    horiz = other = 0
    odir = None
    for b in page.get_text("dict").get("blocks", []):
        for ln in b.get("lines", []):
            n = sum(len(s.get("text", "").strip()) for s in ln.get("spans", []))
            dx, dy = (round(v) for v in ln.get("dir", (1, 0)))
            if (dx, dy) == (1, 0):
                horiz += n
            else:
                other += n
                odir = (dx, dy)
    return odir if other > horiz else None


def ps_nup(ps: str) -> int:
    with open(ps, "rb") as f:
        data = f.read(4 * 1024 * 1024)
    m = re.search(rb"(\d+)\s+(\d+)\s+definenup", data)
    return int(m.group(1)) * int(m.group(2)) if m else 1


def page_checks(rep: Report, label: str, page, ref_text: str | None = None):
    rot = text_off(page)
    rep.check(rot is None, "%s 바로 섬(글이 가로)" % label, "글이 %s 방향으로 흐름(누움)" % (rot,))
    rep.check(page.rotation == 0, "%s 회전 표시 없음" % label, str(page.rotation))
    bl = blank_spans(page)
    rep.check(not bl, "%s 빈 글자 없음" % label, ", ".join(bl[:5]))
    if ref_text is not None:
        got = norm(page.get_text())
        miss = sorted(set(norm(ref_text)) - set(got))
        rep.check(not miss, "%s 기준 PDF 의 글자가 모두 있음" % label, "빠진 글자 %d: %s" % (len(miss), "".join(miss[:40])))


def thumb(page, width: int = 520):
    import fitz
    return page.get_pixmap(matrix=fitz.Matrix(width / page.rect.width, width / page.rect.width)) if page is not None else None


def contact_sheet(rows: list, path: Path, width: int = 520):
    """[(기준 그림 또는 None, 결과 그림)](`thumb`) 을 왼쪽·오른쪽으로 놓은 그림 한 장."""
    import fitz
    h = sum(max((im.height for im in r if im), default=0) + 12 for r in rows) or 10
    doc = fitz.open()
    pg = doc.new_page(width=width * 2 + 24, height=h)
    y = 6
    for r in rows:
        for i, im in enumerate(r):
            if im:
                pg.insert_image(fitz.Rect(6 + i * (width + 12), y, 6 + i * (width + 12) + im.width, y + im.height), pixmap=im)
        y += max((im.height for im in r if im), default=0) + 12
    pg.get_pixmap().save(str(path))


# ── PowerPoint ─────────────────────────────────────────────────────────
def cff_family(prefix: str):
    """설치된 이름 기반 CFF 글꼴(PostScript 이름이 prefix 로 시작)의 글꼴 이름(name ID 1) — PowerPoint 에 쓸 이름."""
    from fontTools.ttLib import TTFont
    dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]
    for d in dirs:
        for p in sorted(glob.glob(os.path.join(d, "*.otf"))):
            try:
                f = TTFont(p, lazy=True)
                ps = f["name"].getDebugName(6) or ""
                fam = f["name"].getDebugName(1)
                named = not hasattr(f["CFF "].cff.topDictIndex[0], "ROS") if "CFF " in f else False
                f.close()
            except Exception:
                continue
            if ps.startswith(prefix) and named:
                return fam, ps
    return None, None


def make_fixture(app, path: Path, portrait: bool, cff_font):
    pres = app.Presentations.Add(False)
    pres.PageSetup.SlideWidth, pres.PageSetup.SlideHeight = (595, 842) if portrait else (960, 540)
    W, H = pres.PageSetup.SlideWidth, pres.PageSetup.SlideHeight
    s = pres.Slides.Add(1, 12)                             # ppLayoutBlank

    def box(x, y, w, h, text, font, size, bold=False, color=0x000000):
        tb = s.Shapes.AddTextbox(1, x, y, w, h)
        r = tb.TextFrame.TextRange
        r.Text = text
        r.Font.Name, r.Font.Size, r.Font.Bold, r.Font.Color.RGB = font, size, bold, color
        return tb

    title_font = cff_font or "맑은 고딕"
    box(30, 20, W - 60, 60, "1-1 제안배경", title_font, 36, True, 0x6B3A1F)
    band = s.Shapes.AddShape(1, 0, 100, W, 44)
    band.Fill.ForeColor.RGB, band.Line.Visible = 0x5A3D27, 0
    box(20, 106, W - 40, 30, BANNER, title_font, 18, True, 0xFFFFFF)
    box(30, 170, W / 2 - 40, 120, "맑은 고딕 본문 가나다라 ABC 123\n둘째 줄 65% 수급 불균형", "맑은 고딕", 16)
    for i, (rgb, tr) in enumerate(((0x0000FF, 0.3), (0x00A000, 0.5), (0xFF0000, 0.6))):
        sh = s.Shapes.AddShape(9, W / 2 + 20 + i * 60, 170 + i * 30, 160, 120)    # 타원
        sh.Fill.ForeColor.RGB, sh.Fill.Transparency, sh.Line.Visible = rgb, tr, 0
    s2 = s.Duplicate()(1)                                  # 둘째 쪽 — 한 장에 여러 쪽일 때 두 쪽이 한 장에
    s2.Shapes(1).TextFrame.TextRange.Text = "1-2 연구의 필요성"
    pres.SaveAs(str(path))
    return pres


def with_default_printer(fn):
    import win32print
    before = win32print.GetDefaultPrinter()
    try:
        return fn()
    finally:
        try:
            win32print.SetDefaultPrinter(before)
        except Exception:
            pass


def cmd_compare(args) -> int:
    import fitz
    import win32com.client
    from viewer import vprinter_recv as R
    out = out_dir()
    rep = Report(out)
    gs = gs_path()
    if not gs:
        rep.check(False, "Ghostscript 있음", "printer\\bin\\gs·설치본 모두 없음")
        return rep.write("compare")
    fam, ps_name = cff_family("S-CoreDream-6")
    if fam:
        rep.note("이름 기반 CFF 글꼴", "%s (%s)" % (fam, ps_name))
    else:
        rep.note("이름 기반 CFF 글꼴 없음 — 맑은 고딕으로 대신(빈 글자 시험은 못 함)")
    pairs = []

    def run():
        app = win32com.client.Dispatch("PowerPoint.Application")
        for name, portrait in (("가로 시험", False), ("세로 시험", True)):
            pptx = out / (name + ".pptx")
            pres = make_fixture(app, pptx, portrait, fam)
            try:
                ref = out / (name + " 기준.pdf")
                pres.SaveAs(str(ref), 32)                  # ppSaveAsPDF
                ps = out / (name + ".ps")
                pres.PrintOptions.ActivePrinter = PRINTER
                pres.PrintOut(1, pres.Slides.Count, str(ps), 1, False)
                for _ in range(60):
                    if ps.is_file() and ps.stat().st_size > 0:
                        break
                    time.sleep(0.5)
                time.sleep(1)
            finally:
                pres.Close()
            if not ps.is_file():
                rep.check(False, "%s 파일로 인쇄" % name, "PS 가 생기지 않음")
                continue
            got = out / (name + " 결과.pdf")
            t = time.time()
            try:
                R.convert(str(ps), str(got), title=name, gs=gs)
            except Exception as ex:                        # noqa: BLE001
                rep.check(False, "%s 변환" % name, repr(ex)[:300])
                continue
            rep.check(True, "%s 변환 %.1f초, %d KB" % (name, time.time() - t, got.stat().st_size // 1024))
            rd, gd = fitz.open(str(ref)), fitz.open(str(got))
            nup = ps_nup(str(ps))
            if nup > 1:
                rep.note("%s — 'PolyPDF' 프린터 설정이 한 장에 %d쪽" % (name, nup), "프린터 기본 설정(인쇄 창의 프린터 속성)에서 바뀐 값")
            want = -(-rd.page_count // nup)
            rep.check(gd.page_count == want, "%s 장 수(슬라이드 %d ÷ 한 장에 %d)" % (name, rd.page_count, nup), "%d / %d" % (gd.page_count, want))
            for i in range(gd.page_count):
                gp = gd[i]
                refs = [rd[j] for j in range(i * nup, min((i + 1) * nup, rd.page_count))]
                if nup == 1 and refs:
                    rp = refs[0]
                    same = (rp.rect.width > rp.rect.height) == (gp.rect.width > gp.rect.height)
                    rep.check(same, "%s %d쪽 가로·세로가 기준과 같음" % (name, i + 1), "%s / %s" % (rp.rect, gp.rect))
                page_checks(rep, "%s %d쪽" % (name, i + 1), gp, "".join(r.get_text() for r in refs))
                pairs.append((thumb(refs[0]) if refs else None, thumb(gp)))
            contact_sheet(pairs, out / "compare.png")
            rd.close(); gd.close()
    with_default_printer(run)
    return rep.write("compare")


def cmd_ps(args) -> int:
    import fitz
    from viewer import vprinter_recv as R
    out = out_dir()
    rep = Report(out)
    gs = gs_path()
    files = args.files or sorted(glob.glob(str(WORK / "_samples" / "vprinter" / "*.ps")))
    if not files:
        rep.note("PS 없음", str(WORK / "_samples" / "vprinter"))
    pairs = []
    for i, ps in enumerate(files):
        got = out / ("ps%d.pdf" % (i + 1))
        t = time.time()
        try:
            R.convert(ps, str(got), title=Path(ps).stem, gs=gs)
        except Exception as ex:                            # noqa: BLE001
            rep.check(False, "%s 변환" % Path(ps).name, repr(ex)[:300])
            continue
        d = fitz.open(str(got))
        rep.check(True, "%s 변환 %.1f초, %d쪽(한 장에 %d쪽)" % (Path(ps).name[:40], time.time() - t, d.page_count, ps_nup(ps)))
        for n in range(d.page_count):
            page_checks(rep, "ps%d %d쪽" % (i + 1, n + 1), d[n])
        pairs += [(None, thumb(d[n])) for n in range(min(3, d.page_count))]
    if pairs:
        contact_sheet(pairs, out / "compare.png")
    return rep.write("ps")


def polypdf_windows() -> list:
    import win32gui
    titles = []
    win32gui.EnumWindows(lambda h, _: titles.append(win32gui.GetWindowText(h)) if win32gui.IsWindowVisible(h) else None, None)
    return [t for t in titles if t.startswith("PolyPDF")]


def dev_receiver(rep: Report):
    """`--dev`: 개발 코드 창(`python main.py`)을 먼저 띄워 인쇄 받기 통로를 잡게 한다 — 설치본의 `--printed` 가 이 창에 넘긴다
    (통로 이름이 같다, 마스터 §14.2.1). 설치본을 다시 받지 않고 고친 코드를 실제 인쇄 흐름으로 확인한다(SOT §6.4)."""
    if any(t for t in polypdf_windows()):
        rep.check(False, "열린 PolyPDF 창 없음(개발 창이 받기 통로를 잡으려면)", ", ".join(polypdf_windows())[:200])
        return None
    p = subprocess.Popen([sys.executable, str(ROOT / "main.py")], cwd=str(ROOT))
    for _ in range(80):
        if polypdf_windows():
            break
        time.sleep(0.5)
    time.sleep(5)                                          # 창이 뜬 뒤 받기 통로를 잡는다(--printed 없는 실행은 2.5초 뒤)
    rep.check(bool(polypdf_windows()), "개발 코드 창이 떴다(받는 창)")
    return p


def close_windows(match):
    import win32con
    import win32gui
    hs = []
    win32gui.EnumWindows(lambda h, _: hs.append(h) if win32gui.IsWindowVisible(h) and match(win32gui.GetWindowText(h)) else None, None)
    for h in hs:
        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)


def cmd_e2e(args) -> int:
    import win32com.client
    from viewer import vprinter_recv as R
    out = out_dir()
    rep = Report(out)
    fam, _ = cff_family("S-CoreDream-6")
    name = "가상프린터 자동 시험"
    dev = dev_receiver(rep) if args.dev else None
    if args.dev and dev is None:
        return rep.write("e2e")
    start = time.time()

    def run():
        app = win32com.client.Dispatch("PowerPoint.Application")
        pres = make_fixture(app, out / (name + ".pptx"), False, fam)
        try:
            pres.PrintOptions.ActivePrinter = PRINTER
            pres.PrintOut(1, pres.Slides.Count, "", 1, False)
            time.sleep(3)
        finally:
            pres.Close()
    with_default_printer(run)
    cands = [out, Path(R.default_save_dir())]
    found = None
    for _ in range(120):
        for d in cands:
            for p in d.glob(name + "*.pdf"):
                if p.stat().st_mtime >= start:
                    found = p
        if found:
            break
        time.sleep(0.5)
    rep.check(bool(found), "인쇄 → PDF 저장(창 없이)", "%s 에 새 PDF 없음(60초)" % ", ".join(map(str, cands)) if not found else str(found))
    if found:
        rep.check(found.parent == out, "원래 파일 폴더에 저장", str(found.parent))
        win = None
        for _ in range(40):
            win = next((t for t in polypdf_windows() if found.name in t), None)
            if win:
                break
            time.sleep(0.5)
        rep.check(bool(win), "그 파일이 PolyPDF 창에 열림", win or "창 제목에 파일 이름 없음")
        import fitz
        d = fitz.open(str(found))
        for n in range(d.page_count):
            page_checks(rep, "%d쪽" % (n + 1), d[n])
    left = R.pending_jobs()
    rep.check(not left, "스풀 폴더가 비었다", ", ".join(Path(p).name for p in left[:3]))
    if dev is not None:                                    # 시작 때 창이 없었다 — 지금 있는 PolyPDF 창은 이 시험이 띄운 것
        close_windows(lambda t: t.startswith("PolyPDF"))
    return rep.write("e2e")


def run_as_admin(exe: str, params: str, timeout_ms: int = 900000) -> int:
    """UAC 로 실행해 끝날 때까지 기다린 종료 코드(취소는 1223)."""
    import win32con
    import win32event
    import win32process
    from win32com.shell import shell, shellcon
    try:
        info = shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS, lpVerb="runas", lpFile=exe,
                                    lpParameters=params, nShow=win32con.SW_SHOWNORMAL)
    except Exception as e:                                 # noqa: BLE001
        return getattr(e, "winerror", None) or 1
    win32event.WaitForSingleObject(info["hProcess"], timeout_ms)
    return win32process.GetExitCodeProcess(info["hProcess"])


def cmd_install(args) -> int:
    import win32print
    out = out_dir()
    rep = Report(out)
    before = win32print.GetDefaultPrinter()
    log = out / "setup.log"
    t = time.time()
    rc = run_as_admin(os.path.abspath(args.setup), '/SILENT /NORESTART "/LOG=%s"' % log)
    rep.check(rc == 0, "설치 종료 코드 0 (%.0f초)" % (time.time() - t), str(rc))
    txt = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    m = re.search(r"Parameters: --vprinter install.*?Process exit code: (\d+)", txt, re.S)
    rep.check(bool(m) and m.group(1) == "0", "설치 끝 가상 프린터 단계 종료 코드 0", m.group(1) if m else "기록에 없음")
    exe = r"C:\Program Files\PolyPDF\PolyPDF.exe"
    r = subprocess.run([sys.executable, str(ROOT / "main.py"), "--vprinter", "check"], capture_output=True, timeout=120, cwd=str(ROOT))
    try:
        st = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
    except Exception:
        st = {}
    need = ("monitor", "dll", "port", "driver", "printer", "ppd", "spool")
    rep.check(all(st.get(k) for k in need), "프린터 구성요소 모두 있음", json.dumps(st, ensure_ascii=False))
    rep.check(win32print.GetDefaultPrinter() == before, "기본 프린터 그대로", "%s → %s" % (before, win32print.GetDefaultPrinter()))
    rep.note("설치본", exe if os.path.isfile(exe) else "없음")
    return rep.write("install")


def main() -> int:
    ap = argparse.ArgumentParser(description="가상 프린터 자동 대조(SOT §6.4)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("compare")
    p = sub.add_parser("ps"); p.add_argument("files", nargs="*")
    p = sub.add_parser("e2e"); p.add_argument("--dev", action="store_true", help="개발 코드 창이 받는다(설치본을 다시 받지 않음)")
    p = sub.add_parser("install"); p.add_argument("setup")
    a = ap.parse_args()
    return {"compare": cmd_compare, "ps": cmd_ps, "e2e": cmd_e2e, "install": cmd_install}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
