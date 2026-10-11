# -*- coding: utf-8 -*-
"""261011-2: 평탄화해서 내보내기 — 내용만 굽고 **자동 재서명** (보안 SOT §4.1).

A. 내 ID 서명 둘(회전한 쪽 포함) + 다른 사람 서명 하나 → [계속]·비밀번호 → 내보낸 파일의 서명 둘 모두 '유효·신뢰함'
   ('서명 후 변경됨' 없음), 같은 쪽·같은 자리, 다른 사람 서명은 없음, 꾸밈은 구워짐, 표식 링크는 남지 않음, 원본 서명 그대로
B. 비밀번호 창 취소 → 서명을 모두 뺀 파일(서명 칸·겉모양 없음 — 도장 그림만 남지 않음)
C. 다른 사람 서명이 있을 때 확인 창 [취소](기본) → 내보내지 않음
D. 내 인증 서명(P=2) → 내보낸 파일도 같은 수준의 인증
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["POLYPDF_FAKE_HELLO"] = ""
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QInputDialog

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_resign_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


PW, PW2 = "Resign-2026!", "Other-2026!"
RED = {"shape": "rect", "rect": [0.6, 0.85, 0.9, 0.95], "color": "#ff0000", "fill": "full", "width": 2, "alpha": 100}


def sig_rects(path):
    out = {}
    with fitz.open(str(path)) as d:
        for p in d:
            for w in p.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]) or []:
                if w.is_signed:
                    out[p.number] = fitz.Rect(w.rect)
    return out


tmp = Path(tempfile.mkdtemp(prefix="polypdf_resign_"))
try:
    from viewer.app import MainWindow
    from viewer import sign_core as sc, sign_store as st
    root = tmp / "folder"; root.mkdir()
    ap = sc.Appearance(font_path=sc.default_font())
    mine_pfx, mine = sc.create_id("홍길동", PW)
    st.add_id(mine_pfx, mine)                                  # 내 ID(Hello 보관 없음 → 비밀번호 창)
    other_pfx, other = sc.create_id("김철수", PW2)             # 다른 사람(내 ID 목록에 없음)

    src = root / "계약.pdf"
    d = fitz.open()
    for i in range(3):
        p = d.new_page(width=595, height=842); p.insert_text((72, 100), f"PAGE{i}", fontsize=20)
    d[1].set_rotation(90)
    d.save(str(src)); d.close()
    s1, s2 = root / "~1.tmp", root / "~2.tmp"
    sc.sign_pdf(str(src), str(s1), mine_pfx, PW, page_index=0, box_pdf=(100, 100, 300, 160), appearance=ap, reason="승인")
    with fitz.open(str(s1)) as dd:
        b1 = sc.page_box_to_pdf(dd[1], fitz.Rect(400, 300, 620, 380))     # 회전한 쪽(보이는 좌표)
    sc.sign_pdf(str(s1), str(s2), mine_pfx, PW, page_index=1, box_pdf=b1, appearance=ap)
    sc.sign_pdf(str(s2), str(src), other_pfx, PW2, page_index=2, box_pdf=(100, 100, 300, 160), appearance=ap)
    before = sig_rects(src)
    chk(len(before) == 3 and len(sc.verify_pdf(str(src), [mine.fp]).sigs) == 3, "준비 — 서명 셋(내 것 둘·다른 사람 하나)")

    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 820); mw.show(); spin(0.3)
    mw.open_folder(str(root)); spin(0.6)
    mw.open_pdfs([str(src)]); spin(1.0)
    ms = mw._ensure_page_meta_store()
    ms.set_drawings(str(src), 0, [dict(RED)]); ms.save()
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: print("   [warning]", a[1:3]))
    pick = {"text": "계속"}
    QMessageBox.exec = lambda self: (setattr(self, "_pick", next((b for b in self.buttons() if pick["text"] and pick["text"] == b.text()), None)), 0)[1]
    QMessageBox.clickedButton = lambda self: getattr(self, "_pick", None)
    pw_box = {"pw": PW, "asked": 0}

    def _get_text(*a, **k):
        pw_box["asked"] += 1
        return (pw_box["pw"], bool(pw_box["pw"]))
    QInputDialog.getText = staticmethod(_get_text)

    def export(name):
        out = root / name
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out), "PDF (*.pdf)"))
        mw._action_save_decorated_pdf(file_path=str(src)); spin(1.0)
        return out

    # ── A ──
    out = export("계약_평탄화.pdf")
    rep = sc.verify_pdf(str(out), [mine.fp])
    states = [s.state for s in rep.sigs]
    chk(out.exists() and len(rep.sigs) == 2 and all(x == sc.OK_TRUSTED for x in states),
        "A1 내 서명 둘을 다시 했다 — 둘 다 유효·신뢰함('서명 후 변경됨' 없음)", str(states))
    chk(pw_box["asked"] == 1, "A2 키 확인은 ID 마다 한 번", str(pw_box["asked"]))
    after = sig_rects(out)
    same = sorted(after) == [0, 1] and all(abs(after[k].x0 - before[k].x0) < 1 and abs(after[k].y1 - before[k].y1) < 1 for k in after)
    chk(same, "A3 같은 쪽·같은 자리(회전한 쪽 포함), 다른 사람 서명은 없다", str((before, after)))
    with fitz.open(str(out)) as o:
        uris = [l.get("uri", "") for p in o for l in p.get_links()]
        chk(not any(u.startswith("polypdf-resign:") for u in uris), "A4 표식 링크는 남지 않는다", str(uris))
        pix = o[0].get_pixmap(dpi=30)
        red = sum(1 for y in range(pix.height) for x in range(pix.width) if pix.pixel(x, y)[0] > 200 and pix.pixel(x, y)[1] < 90)
        chk(red > 10, "A5 꾸밈은 구워졌다")
    chk(len(sc.verify_pdf(str(src), [mine.fp]).sigs) == 3, "A6 원본의 서명 셋은 그대로")

    # ── B ── 비밀번호 창 취소 → 서명을 모두 뺀 파일
    pw_box["pw"] = ""
    out_b = export("계약_서명없음.pdf")
    with fitz.open(str(out_b)) as o:
        sigw = [w for p in o for w in (p.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]) or [])]
        txt = "".join(p.get_text() for p in o)
    chk(out_b.exists() and not sigw and not sc.verify_pdf(str(out_b), []).sigs and "홍길동" not in txt,
        "B1 취소하면 서명 칸·겉모양을 모두 뺀 파일(도장 그림만 남지 않음)", str((len(sigw), "홍길동" in txt)))

    # ── C ── 다른 사람 서명이 있을 때 확인 창 [취소]
    pick["text"] = "취소"
    pw_box["pw"] = PW
    out_c = export("계약_취소.pdf")
    chk(not out_c.exists(), "C1 확인 창 [취소] → 내보내지 않는다")
    pick["text"] = "계속"

    # ── D ── 내 인증 서명(P=2)
    csrc = root / "인증.pdf"
    d = fitz.open(); d.new_page().insert_text((72, 100), "CERT", fontsize=20); d.save(str(root / "~c.pdf")); d.close()
    sc.sign_pdf(str(root / "~c.pdf"), str(csrc), mine_pfx, PW, page_index=0, box_pdf=(100, 100, 300, 160), appearance=ap, certify=2)
    mw.open_pdfs([str(csrc)]); spin(1.0)
    ms.set_drawings(str(csrc), 0, [dict(RED)]); ms.save()
    out_d = root / "인증_평탄화.pdf"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out_d), "PDF (*.pdf)"))
    mw._action_save_decorated_pdf(file_path=str(csrc)); spin(1.0)
    rd = sc.verify_pdf(str(out_d), [mine.fp])
    chk(len(rd.sigs) == 1 and rd.sigs[0].certify == 2 and rd.worst == sc.OK_TRUSTED,
        "D1 내 인증 서명은 같은 수준(P=2)으로 다시 인증", str([(s.certify, s.state) for s in rd.sigs]))
    mw.close(); spin(0.2)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("=== ALL PASS ===" if not fails else "=== FAIL %d ===\n  " % len(fails) + "\n  ".join(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
