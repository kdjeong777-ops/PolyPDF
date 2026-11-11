# -*- coding: utf-8 -*-
"""사진 정보 촬영 값 표기 (사진 보기 SOT 4.18 '촬영 값 표기', 261111-22 사용자 지시 '노출시간, 초점 거리 수정. 반올림 적용 검토'·
'노출시간은 1/60 등으로 표시 검토', 결정 '표준 셔터 값으로'·'방향은 글로 + 코드').

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 사용자 화면의 아이폰 15 Pro 값과 같은 EXIF
(노출 1/99 → 0.0101…, 조리개 2.2, 초점 거리 2.22 → 2.220000028611935, 35mm 환산 13, ISO 125, 방향 1)를 JPEG 에 써서 실제로 열고,
실제 세부 정보 창 표의 글을 본다.
A. 노출 시간 '1/100초'(표준 셔터 값) — 칸 툴팁에 기록 값 · 조리개 'f/2.2' · 초점 거리 '2.22 mm (35mm 환산 13 mm)' · ISO '125' · 방향 '정상 (1)'
B. 표의 어느 값에도 긴 소수(소수 다섯 자리 이상)가 없다 — 고도·노출 보정 포함
C. 표기 함수 경계 — 1/60·1/2·30초·표 밖(1/12000·45초)·1/2.5·방향 6·노출 보정 0 은 행 없음·읽을 수 없는 값은 그대로
"""
import os, sys, tempfile, shutil, time, re
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QDialog, QTableWidget
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_exifdisp_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "촬영 값", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=15.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_exifdisp_"))
try:
    from PIL import Image
    from PIL.TiffImagePlugin import IFDRational
    ex = Image.Exif()
    ex[0x010F] = "Apple"; ex[0x0110] = "iPhone 15 Pro"; ex[0x0112] = 1
    ex[0x8769] = {0x829A: IFDRational(1, 99), 0x829D: IFDRational(11, 5), 0x8827: 125,
                  0x920A: 2.220000028611935, 0xA405: 13, 0x9204: IFDRational(0, 1),
                  0xA434: "iPhone 15 Pro back triple camera 2.22mm f/2.2"}
    ex[0x8825] = {1: "N", 2: (37.0, 30.0, 0.0), 3: "E", 4: (127.0, 2.0, 0.0), 5: b"\x00", 6: 41.48127128}
    Image.new("RGB", (400, 300), (90, 120, 160)).save(tmp / "아이폰.jpg", "JPEG", exif=ex.tobytes())

    from viewer.app import MainWindow
    from viewer import photo_controller as pc
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 850); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 1), "사진 목록")
    lst = mw._photo_tree_list()
    mw._on_bookmark_activated(lst[0], 0)
    chk(pump(lambda: (getattr(mw, "_photo_info", None) or {}).get("exif"), timeout=10), "정보 읽음")
    raw = (mw._photo_info or {}).get("exif", {})
    chk("0.0101" in str(raw.get("ExposureTime")) and len(str(raw.get("FocalLength"))) > 8,
        "준비 — 기록 값은 사용자 화면처럼 긴 소수(정보는 기록 값 그대로 둔다)", str(raw))

    got = {}
    _orig = QDialog.exec

    def _exec(self, *a, **k):
        if type(self) is QDialog:
            t = self.findChild(QTableWidget)
            for i in range(t.rowCount()):
                got[t.item(i, 0).text()] = (t.item(i, 1).text(), t.item(i, 1).toolTip())
            return 0
        return _orig(self, *a, **k)
    QDialog.exec = _exec
    try:
        mw._photo_info_dialog()
    finally:
        QDialog.exec = _orig
    val = {k: v[0] for k, v in got.items()}

    # A
    chk(val.get("노출 시간") == "1/100초", "A 노출 시간 = 표준 셔터 값 '1/100초'", repr(val.get("노출 시간")))
    chk("0.010101" in got.get("노출 시간", ("", ""))[1], "A 노출 시간 툴팁 = 기록 값", repr(got.get("노출 시간")))
    chk(val.get("조리개") == "f/2.2", "A 조리개 'f/2.2'", repr(val.get("조리개")))
    chk(val.get("초점 거리") == "2.22 mm (35mm 환산 13 mm)", "A 초점 거리 '2.22 mm (35mm 환산 13 mm)'", repr(val.get("초점 거리")))
    chk(val.get("ISO") == "125", "A ISO '125'", repr(val.get("ISO")))
    chk(val.get("방향(EXIF)") == "정상 (1)", "A 방향 '정상 (1)'", repr(val.get("방향(EXIF)")))
    chk(val.get("고도") == "41.5 m", "A 고도 '41.5 m'", repr(val.get("고도")))
    chk("노출 보정" not in val, "A 노출 보정 0 은 행 없음", repr(val.get("노출 보정")))
    # B
    longs = {k: v for k, v in val.items() if k not in ("파일", "위치(GPS)") and re.search(r"\d\.\d{5,}", v)}
    chk(not longs, "B 표에 긴 소수가 없다", str(longs))

    # C
    def d(name, v, **more):
        return pc.exif_display(name, dict({name: v}, **more))
    cases = [(("ExposureTime", "0.016666666666666666"), "1/60초"), (("ExposureTime", "0.5"), "1/2초"),
             (("ExposureTime", "30.0"), "30초"), (("ExposureTime", "0.0000833"), "1/12005초"),
             (("ExposureTime", "45.0"), "45초"), (("ExposureTime", "0.4"), "1/2.5초"),
             (("ExposureTime", "0.0078125"), "1/125초"), (("FNumber", "8.0"), "f/8"),
             (("FocalLength", "6.86"), "6.86 mm"), (("FocalLength", "50.0"), "50 mm"),
             (("ISOSpeedRatings", "(125,)"), "125"), (("Orientation", "6"), "시계 방향 90° 회전 (6)"),
             (("Orientation", "9"), "9"), (("ExposureBiasValue", "-0.6666666666666666"), "-0.7 EV"),
             (("ExposureBiasValue", "0.0"), ""), (("ExposureTime", "abc"), "abc"), (("ExposureTime", "0"), "0"),
             (("GPSAltitude", "-3.25"), "-3.2 m")]
    for (n, v), want in cases:
        g = d(n, v)
        chk(g == want, "C %s %s → %r" % (n, v, want), repr(g))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
