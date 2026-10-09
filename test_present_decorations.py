# -*- coding: utf-8 -*-
"""261009-14: 발표 보기에도 본문 꾸밈(선·도형·글·사진)이 보인다 — 발표 SOT §2 · 마스터 §4.7.13 (사용자 지시).

설치본 화면 시험에서 본문에 그은 빨간 선이 발표 보기에는 보이지 않았다. 사용자 지시
"발표보기에서 본문에 그린 선이나 그림 도형이 보이도록해". 발표 창은 원본 PDF 를 그렸고, 꾸밈은 PDF 옆
사이드카(`page_meta.json`)에 있어 원본에 없다. 인쇄가 이미 쓰는 '원천을 한 번 굽기'(`_baked_src`)로 그린다.

A. 실제 `MainWindow._open_presentation`(F5 경로)으로 연 발표 창의 쪽 그림에 본문 꾸밈(빨간 선)이 보인다
B. 선을 더 그리고 다시 열면 새 선도 보인다 — 굽기 캐시가 PDF 수정 시각만 보지 않는다(꾸밈은 PDF 밖에 있다)
C. 크롭·숨김·회전·하이퍼링크의 열쇠는 여전히 원본 경로다(구운 임시 파일 경로가 아니다)
"""
import os, sys, time, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_present_deco_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(sec=0.4):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def color_at(pm, fx, fy):
    img = pm.toImage()
    c = img.pixelColor(int(img.width() * fx), int(img.height() * fy))
    return c.red(), c.green(), c.blue()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_pdeco_"))
try:
    import fitz
    pdf = tmp / "A.pdf"
    d = fitz.open(); d.new_page(width=400, height=600).insert_text((40, 80), "page one"); d.save(str(pdf)); d.close()

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.open_pdf(pdf); pump(0.8)
    try:
        mw.bookmark_tree.set_edit_mode(False)
    except Exception:
        pass
    st = mw._ensure_page_meta_store()
    st.set_drawings(str(pdf), 0, [{"color": "#ff0000", "width": 12, "alpha": 100,
                                   "points": [[0.05, 0.5], [0.95, 0.5]]}])
    st.save()

    # ── A ──
    mw._open_presentation(); pump(0.6)
    pres = getattr(mw, "_present", None)
    chk(pres is not None, "A 발표 창이 열린다")
    r, g, b = color_at(pres._render_pixmap(72, 0), 0.5, 0.5)
    chk(r > 200 and g < 90 and b < 90, "A 발표 보기에 본문의 빨간 선이 보인다", "RGB(%d,%d,%d)" % (r, g, b))

    # ── C ──
    chk(Path(str(pres._path)) == pdf, "C 크롭·숨김·회전·하이퍼링크의 열쇠는 원본 경로", str(pres._path))
    pres.close(); pump(0.3); mw._present = None

    # ── B ──
    st.set_drawings(str(pdf), 0, [{"color": "#ff0000", "width": 12, "alpha": 100, "points": [[0.05, 0.5], [0.95, 0.5]]},
                                  {"color": "#0000ff", "width": 12, "alpha": 100, "points": [[0.05, 0.3], [0.95, 0.3]]}])
    st.save()
    mw._open_presentation(); pump(0.6)
    pres = mw._present
    r, g, b = color_at(pres._render_pixmap(72, 0), 0.5, 0.3)
    chk(b > 200 and r < 90 and g < 90, "B 선을 더 그리면 다시 열 때 새 선도 보인다(굽기 캐시가 꾸밈을 본다)", "RGB(%d,%d,%d)" % (r, g, b))
    pres.close(); pump(0.3)
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(tmp), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
