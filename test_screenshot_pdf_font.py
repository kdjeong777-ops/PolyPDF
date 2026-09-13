# -*- coding: utf-8 -*-
"""260913-7: 스크린샷 PDF 저장 — 머리말·꼬리말 글꼴이 파일을 불리지 않는다 (스크린샷 SOT §7, 마스터 §4.5.10).

종전 `_overlay_header_footer` 는 `insert_htmlbox` 로 쪽마다 대체 글꼴 3.6MB 를 넣고 부분집합 없이
저장해 10쪽이 36.57MB 였다.

  ① 파일명+순번 10쪽 저장이 1MB 를 넘지 않는다 (글꼴 전체가 안 들어감)
  ② 한글 파일명·순번이 추출되고 글꼴은 맑은 고딕 부분집합이다
  ③ 옛 스크린샷 PDF 의 쪽을 다시 담아 머리말을 적어도 새 글이 사라지지 않는다(`krhdr2`)
  ④ 머리말·꼬리말이 띠 가운데에 있고, 긴 파일명은 줄여 쪽 폭 안에 든다
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
import test_fixtures as _fx
from viewer.pdf_font import text_font_file
from viewer.screenshot import export_pdf_from_meta

if not text_font_file():
    print("SKIP - 한글 글꼴 없음 — 머리말 글꼴 검사 불가")
    sys.stdout.flush(); os._exit(0)

root = Path(tempfile.mkdtemp(prefix="polypdf_shotfont_"))
src = root / "한글파일명_보고서.pdf"
shutil.copy(_fx.text_pdf(), src)

try:
    metas = [{"src_pdf": str(src), "src_page": i, "kind": "pdf"} for i in range(10)]
    out = export_pdf_from_meta(metas, root / "shots.pdf", show_filename=True, show_pageno=True)
    size = os.path.getsize(out)
    chk(size < 1_000_000, "① 파일명+순번 10쪽이 1MB 미만(종전 36MB 급)", f"({size:,} B)")

    d = fitz.open(out)
    t0, t9 = d[0].get_text(), d[9].get_text()
    chk("한글파일명_보고서" in t0 and "1 / 10" in t0 and "10 / 10" in t9, "② 한글 파일명·순번이 추출된다")
    hdr = [f for f in d[0].get_fonts() if f[4].startswith("krhdr")]
    chk(len(hdr) == 1 and "Malgun" in hdr[0][3] and hdr[0][3][6:7] == "+",
        "② 머리말 글꼴은 맑은 고딕 부분집합", str([f[3] for f in hdr]))

    # ④ 가운데 · 띠 안
    pw, ph = d[0].rect.width, d[0].rect.height
    spans = [(s["text"], s["bbox"]) for b in d[0].get_text("dict")["blocks"] for ln in b.get("lines", [])
             for s in ln["spans"] if s["text"] in ("한글파일명_보고서", "1 / 10")]
    top = next((bb for t, bb in spans if t == "한글파일명_보고서"), None)
    bot = next((bb for t, bb in spans if t == "1 / 10"), None)
    chk(top is not None and abs((top[0] + top[2]) / 2 - pw / 2) < 2 and top[3] <= 27,
        "④ 머리말이 위 띠 가운데", str(top))
    chk(bot is not None and abs((bot[0] + bot[2]) / 2 - pw / 2) < 2 and bot[1] >= ph - 25,
        "④ 꼬리말이 아래 띠 가운데", str(bot))
    d.close()

    longname = root / ("아주긴파일이름" * 12 + ".pdf")
    shutil.copy(_fx.text_pdf(), longname)
    o2 = export_pdf_from_meta([{"src_pdf": str(longname), "src_page": 0, "kind": "pdf"}],
                              root / "long.pdf", show_filename=True)
    d2 = fitz.open(o2)
    lb = [s["bbox"] for b in d2[0].get_text("dict")["blocks"] for ln in b.get("lines", [])
          for s in ln["spans"] if "아주긴파일이름" in s["text"]]
    chk(lb and lb[0][0] >= 0 and lb[0][2] <= d2[0].rect.width, "④ 긴 파일명은 줄여 쪽 폭 안에 든다", str(lb[:1]))
    d2.close()

    # ③ 다시 담기
    metas2 = [{"src_pdf": str(out), "src_page": i, "kind": "pdf"} for i in range(3)]
    out2 = export_pdf_from_meta(metas2, root / "again.pdf", show_filename=True, show_pageno=True)
    d3 = fitz.open(out2)
    names = sorted(f[4] for f in d3[0].get_fonts() if f[4].startswith("krhdr"))
    t = d3[0].get_text()
    chk("1 / 3" in t and "shots" in t, "③ 옛 스크린샷 PDF 를 다시 담아도 새 머리말·순번이 추출된다", repr(t[:40]))
    chk(names == ["krhdr", "krhdr2"], "③ 부분집합이 된 krhdr 는 비켜 간다", str(names))
    chk(os.path.getsize(out2) < 1_000_000, "③ 다시 담아도 작다", f"({os.path.getsize(out2):,} B)")
    d3.close()
except Exception as e:                                   # noqa: BLE001
    import traceback; traceback.print_exc()
    chk(False, f"예외: {e}")

print("ALL PASS" if not fails else f"FAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
