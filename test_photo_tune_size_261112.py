# -*- coding: utf-8 -*-
"""변환·다듬기 창 크기 — 오른쪽 칸이 잘리지 않고 [닫기]까지 보인다 (디자인 SOT §2.22, 사진 보기 SOT §4.46, 261112-15 덧붙임 사용자 보고).

사용자 보고(100% 배율): 오른쪽 설정 칸이 잘려 가로 스크롤 막대가 생기고 [닫기] 가 반쯤 가려졌다.
실제 창(오프스크린 MainWindow, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3)을 **1920×1080 화면에서 100% 와 150%(QT_SCALE_FACTOR, 자식 실행)·밝은·어두운 테마**로 띄워:
A. 오른쪽 칸에 가로 스크롤 막대가 없다(가로로 넘치는 것이 없다)
B. [닫기]·[새 파일로 저장]·[클립보드로 복사](스크롤 칸 밖 아래 줄)·오른쪽 끝 단추([지우기]·[없애기])가 창 안에 다 보인다
C. 창은 화면(사용 가능 영역) 안 — 좁은 화면이면 미리보기를 줄이고 오른쪽 칸은 그대로
그림은 `_review\\261112-15\\size_<배율>_<테마>_<종류>.png` 로 남긴다(눈으로 확인용).
"""
import os, sys, subprocess, tempfile, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
if "--child" not in sys.argv:
    import json
    rc = 0
    # 오프스크린 기본 화면은 800×800 — 실제 모니터(1920×1080)를 흉내 낸다. 설정 파일 경로는 상대로(드라이브 콜론이 플랫폼 인자를 끊는다)
    cfg_dir = tempfile.mkdtemp(prefix="polypdf_scr_")
    json.dump({"screens": [{"name": "s1", "x": 0, "y": 0, "width": 1920, "height": 1080,
                            "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}, open(os.path.join(cfg_dir, "scr.json"), "w"))
    for scale in ("1", "1.5"):
        env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM="offscreen:configfile=scr.json")
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", scale], env=env, cwd=cfg_dir)
        rc = rc or r.returncode
    shutil.rmtree(cfg_dir, ignore_errors=True)
    print()
    print("ALL PASS" if rc == 0 else "FAILURES")
    sys.exit(rc)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, HERE)
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tune_size_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "변환 창 크기", echo=False)   # 마스터 §14.7.2 의 6
SCALE = sys.argv[-1]
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", "[%s배]" % SCALE, msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(t=0.4):
    end = time.monotonic() + t
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def shown_in(w, dlg) -> bool:
    """위젯이 창 안에서 통째로 보이나 — 스크롤 칸이 자르면 visibleRegion 이 줄어든다."""
    if not w.isVisible():
        return False
    full = w.rect()
    vis = w.visibleRegion().boundingRect()
    tl = w.mapTo(dlg, QPoint(0, 0))
    inside = tl.x() >= 0 and tl.y() >= 0 and tl.x() + w.width() <= dlg.width() and tl.y() + w.height() <= dlg.height()
    return inside and vis.width() >= full.width() - 1 and vis.height() >= full.height() - 1


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tune_size_"))
out_dir = Path(HERE).parent / "_review" / "261112-15"
try:
    from PIL import Image
    Image.new("RGB", (1600, 1000), (220, 220, 210)).save(tmp / "넓은 사진 이름이 아주 긴 경우.jpg", "JPEG")
    src = str(tmp / "넓은 사진 이름이 아주 긴 경우.jpg")
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    from viewer.widgets.image_tune_dialog import ImageTuneDialog
    for theme in ("light", "dark"):
        try:
            mw.apply_theme(theme)
        except Exception as e:
            print("테마", theme, e)
        pump()
        for kind in ("photo", "shot"):
            dlg = ImageTuneDialog(mw, [src], kind=kind, doc_fn=(lambda: None) if kind == "photo" else None)
            dlg.show(); pump(0.8)
            from PyQt6.QtWidgets import QScrollArea, QPushButton
            sc = dlg.findChildren(QScrollArea)[0]                     # 실제 위젯으로 찾는다(수정 전 코드도 같은 길)
            side = sc.widget()
            hb = sc.horizontalScrollBar()
            tag = "%s·%s" % (theme, kind)
            chk(not hb.isVisible() and side.width() >= side.sizeHint().width() - 1,
                "A %s 오른쪽 칸 가로 스크롤 없음·제 폭" % tag, "%s %s %s" % (hb.isVisible(), side.width(), side.sizeHint().width()))
            close = next((b for b in dlg.findChildren(QPushButton) if b.text() == "닫기"), None)
            for name, b in (("닫기", close), ("새 파일로 저장", dlg.btn_save), ("클립보드로 복사", dlg.btn_copy),
                            ("지우기", dlg.btn_bg_clear), ("없애기", dlg.btn_sw_clear)):
                chk(b is not None and shown_in(b, dlg), "B %s [%s] 다 보임" % (tag, name),
                    str(b.visibleRegion().boundingRect() if b is not None else None))
            scr = dlg.screen().availableGeometry()
            chk(dlg.width() <= scr.width() and dlg.height() <= scr.height(), "C %s 창이 화면 안" % tag,
                "%sx%s / %sx%s" % (dlg.width(), dlg.height(), scr.width(), scr.height()))
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                dlg.grab().save(str(out_dir / ("size_%s_%s_%s.png" % (SCALE, theme, kind))))
            except Exception:
                pass
            dlg.close(); dlg.deleteLater(); pump(0.2)
    # C — 좁은 화면: 미리보기부터 줄이고 오른쪽 칸은 그대로
    dlg = ImageTuneDialog(mw, [src], kind="shot")
    if not hasattr(dlg, "_fit_size"):
        raise AssertionError("C 창 크기 맞추기(_fit_size) 없음")
    side_w = dlg._sc.minimumWidth()
    from PyQt6.QtCore import QRect
    import viewer.widgets.image_tune_dialog as itd

    class _Scr:
        def availableGeometry(self):
            return QRect(0, 0, side_w + 360, 700)
    dlg.screen = lambda: _Scr()
    dlg._fit_size()
    chk(dlg.width() <= side_w + 360 and dlg._sc.minimumWidth() == side_w and dlg.preview.minimumWidth() >= itd.PREVIEW_MIN,
        "C 좁은 화면 — 미리보기를 줄이고 오른쪽 칸 폭은 그대로", "%s %s %s" % (dlg.width(), side_w, dlg.preview.minimumWidth()))
    dlg.deleteLater()
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("child", SCALE, "ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
