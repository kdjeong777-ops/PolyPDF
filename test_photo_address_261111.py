# -*- coding: utf-8 -*-
"""사진 정보 주소 (사진 보기 SOT 4.18·D20, 261111-21 사용자 지시 '사진 정보에 위치정보를 이용하여 얻은 주소 추가').

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 사진을 실제로 열고(책갈피 활성화),
배경 `PhotoInfoWorker` 가 보낸 정보·주소로 실제 세부 정보 창(`_photo_info_dialog`)을 채워 본다. 네트워크는 가짜(`photo_address._fetch`).
A. 국내 위치 사진 — 배경에서 행정동 주소('서울특별시 강남구 …')가 정보에 들어오고 세부 정보 표에 '주소' 행. 정보 한 줄에는 넣지 않는다
B. 국외 위치 — '국외 …' 까닭 행 / 위치 없는 사진 — 주소 행·주소 단추 없음
C. 세부 정보 창 — [주소 복사] 가 행정동 주소를 클립보드에. [상세 주소 찾기(온라인)] 은 확인 '아니요' 면 보내지 않는다,
   '예' 면 한 번 보내 '상세 주소(온라인)' 행(국내는 큰 단위부터), 그 뒤 [주소 복사] 는 상세 주소. 같은 위치는 다시 보내지 않는다
D. 보내는 것은 위도·경도뿐 — 주소(URL)에 파일 이름·경로가 없고 User-Agent 는 앱 이름
E. 온라인 실패(방화벽) — '찾지 못했습니다' 행, 창은 그대로
F. 주소가 늦게 오면 창의 '찾는 중…' 이 그 주소로 바뀐다
G. 출처(261111-25) — 상세 주소가 보일 때만 창에 '© OpenStreetMap contributors'(칸 툴팁도), 정보 창 오픈소스 고지에 Nominatim
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QDialogButtonBox
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_address_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 주소", echo=False)   # 마스터 §14.7.2 의 6
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


def gps_jpg(path, lat, lon, color=(30, 160, 60)):
    from PIL import Image
    ex = Image.Exif()
    d = int(lat); m = (lat - d) * 60
    e = int(lon); n = (lon - e) * 60
    ex[0x8825] = {1: "N", 2: (float(d), float(m), 0.0), 3: "E", 4: (float(e), float(n), 0.0)}
    Image.new("RGB", (300, 200), color).save(path, "JPEG", exif=ex.tobytes())


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_addr_"))
try:
    from PIL import Image
    gps_jpg(tmp / "1 강남.jpg", 37.4979, 127.0276)
    gps_jpg(tmp / "2 파리.jpg", 48.8584, 2.2945, (200, 60, 60))
    Image.new("RGB", (300, 200), (60, 60, 200)).save(tmp / "3 없음.jpg", "JPEG")

    from viewer import kr_dong
    want = kr_dong.lookup(37.4979, 127.0276) or ""
    chk(want.startswith("서울특별시 ") and len(want.split()) == 3, "준비 — 동봉 행정동 자료로 강남역 = 서울특별시 ○○구 ○○동", repr(want))

    sent = []
    fake = {"fail": False}

    def fake_fetch(url, timeout):
        sent.append(url)
        if fake["fail"]:
            raise OSError("blocked")
        return {"display_name": "152, 테헤란로, 역삼동, 강남구, 서울, 06236, 대한민국",
                "address": {"house_number": "152", "road": "테헤란로", "quarter": "역삼동", "borough": "강남구",
                            "city": "서울특별시", "postcode": "06236", "country": "대한민국", "country_code": "kr"}}

    try:
        from viewer import photo_address
        photo_address._fetch = fake_fetch
    except ImportError:
        photo_address = None                          # 수정 전 코드 — 모듈 없음(아래 검사가 실패로 잡는다)

    from viewer.app import MainWindow
    from viewer import photo_controller as pc
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 850); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3), "사진 3장 목록")
    bt.set_sort_mode(bt.SORT_NAME); pump()
    lst = mw._photo_tree_list()

    def open_photo(p):
        mw._on_bookmark_activated(p, 0)
        pump(lambda: (getattr(mw, "_photo_info", None) or {}).get("path") == str(p), timeout=10)

    # A
    open_photo(lst[0])
    chk(pump(lambda: "address" in (mw._photo_info or {}), timeout=10), "A 배경에서 주소가 정보에 들어온다")
    chk((mw._photo_info or {}).get("address") == want, "A 주소 = 행정동 전체 이름", repr((mw._photo_info or {}).get("address")))
    rows = dict(pc.photo_info_rows(mw._photo_info))
    chk(rows.get("주소") == want, "A 세부 정보 표에 '주소' 행", str(rows))
    chk(want and want not in mw._photo_info_btn.text(), "A 정보 한 줄에는 주소를 넣지 않는다(사용자 결정)", repr(mw._photo_info_btn.text()))

    # B
    open_photo(lst[1])
    pump(lambda: "address" in (mw._photo_info or {}), timeout=10)
    rows = dict(pc.photo_info_rows(mw._photo_info))
    chk(rows.get("주소", "").startswith("국외"), "B 국외 위치 — '국외 …' 행", str(rows.get("주소")))
    open_photo(lst[2])
    pump(timeout=0.5)
    rows = dict(pc.photo_info_rows(mw._photo_info or {}))
    chk("주소" not in rows and "위치(GPS)" not in rows, "B 위치 없는 사진 — 주소 행 없음", str(rows))

    # C·D·E — 실제 세부 정보 창
    seen = {}
    answer = {"v": QMessageBox.StandardButton.No}
    QMessageBox.question = staticmethod(lambda *a, **k: (seen.setdefault("asked", []).append(a[2] if len(a) > 2 else ""),
                                                          answer["v"])[1])
    _orig_exec = QDialog.exec

    def table_rows(dlg):
        t = dlg._table if hasattr(dlg, "_table") else dlg.findChild(__import__("PyQt6.QtWidgets", fromlist=["QTableWidget"]).QTableWidget)
        return {t.item(i, 0).text(): t.item(i, 1).text() for i in range(t.rowCount())}

    def button(dlg, text):
        bb = dlg.findChild(QDialogButtonBox)
        for b in (bb.buttons() if bb else []):
            if b.text() == text:
                return b
        return None

    def run_dialog(inspect):
        def _exec(self, *a, **k):
            if type(self) is QDialog:
                try:
                    inspect(self)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    fails.append("창 검사 예외")
                return 0
            return _orig_exec(self, *a, **k)
        QDialog.exec = _exec
        try:
            mw._photo_info_dialog()
        finally:
            QDialog.exec = _orig_exec

    open_photo(lst[0])
    pump(lambda: "address" in (mw._photo_info or {}), timeout=10)

    def insp_c(dlg):
        from PyQt6.QtWidgets import QLabel as _QL
        _c0 = [w for w in dlg.findChildren(_QL) if "OpenStreetMap contributors" in w.text()]
        chk(all(w.isHidden() for w in _c0), "G 상세 주소 전에는 출처 줄을 보이지 않는다")
        r = table_rows(dlg)
        chk(r.get("주소") == want, "C 창에 주소 행", str(r))
        b_copy, b_on = button(dlg, "주소 복사"), button(dlg, "상세 주소 찾기(온라인)")
        chk(b_copy is not None and b_on is not None, "C 창에 [주소 복사]·[상세 주소 찾기(온라인)]")
        if b_copy is None or b_on is None:
            return
        QApplication.clipboard().setText("")
        b_copy.click(); pump(timeout=0.2)
        chk(QApplication.clipboard().text() == want, "C [주소 복사] = 행정동 주소", repr(QApplication.clipboard().text()))
        answer["v"] = QMessageBox.StandardButton.No
        b_on.click(); pump(timeout=0.5)
        chk(len(seen.get("asked", [])) == 1 and not sent, "C 확인 '아니요' — 묻기만 하고 보내지 않는다", "%s %s" % (seen, sent))
        chk("Nominatim" in (seen.get("asked") or [""])[0], "C 확인 글에 보내는 곳(Nominatim)", repr(seen.get("asked")))
        answer["v"] = QMessageBox.StandardButton.Yes
        b_on.click()
        ok = pump(lambda: table_rows(dlg).get("상세 주소(온라인)", "") not in ("", "찾는 중…"), timeout=10)
        r = table_rows(dlg)
        chk(ok and r.get("상세 주소(온라인)") == "서울특별시 강남구 역삼동 테헤란로 152",
            "C '예' — 상세 주소 행(국내는 큰 단위부터)", str(r))
        chk(len(sent) == 1, "C 한 번만 보냄", str(sent))
        from PyQt6.QtWidgets import QLabel as _QL
        _credit = [w for w in dlg.findChildren(_QL) if "OpenStreetMap contributors" in w.text()]
        chk(bool(_credit) and not _credit[0].isHidden(), "G 상세 주소 옆 출처 '© OpenStreetMap contributors'")
        _tp = dlg._table.findItems("서울특별시 강남구 역삼동 테헤란로 152", __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.MatchFlag.MatchExactly) if hasattr(dlg, "_table") else []
        chk(bool(_tp) and "OpenStreetMap" in _tp[0].toolTip(), "G 상세 주소 칸 툴팁에 출처")
        b_copy.click(); pump(timeout=0.2)
        chk(QApplication.clipboard().text() == "서울특별시 강남구 역삼동 테헤란로 152", "C 상세 주소가 있으면 [주소 복사] 는 상세 주소",
            repr(QApplication.clipboard().text()))
        b_on.click(); pump(timeout=1.0)
        chk(len(sent) == 1, "C 같은 위치는 다시 보내지 않는다(기억)", str(sent))
        # D
        u = sent[0] if sent else ""
        chk("lat=37.497900" in u and "lon=127.027600" in u and "1%20" not in u and "jpg" not in u.lower() and tmp.name not in u,
            "D 보내는 것은 위도·경도뿐(파일 이름·경로 없음)", u)
        chk(photo_address is not None and "PolyPDF" in photo_address._UA and "@" not in photo_address._UA, "D User-Agent 는 앱 이름만")

    run_dialog(insp_c)
    from viewer import about as _ab
    chk(any("Nominatim" in str(row[0]) for row in getattr(_ab, "OSS", []) or [] ) or "Nominatim" in open(_ab.__file__, encoding="utf-8").read(),
        "G 정보 창 오픈소스 고지에 Nominatim")

    # E
    open_photo(lst[1])
    pump(lambda: "address" in (mw._photo_info or {}), timeout=10)
    fake["fail"] = True
    answer["v"] = QMessageBox.StandardButton.Yes

    def insp_e(dlg):
        b_on = button(dlg, "상세 주소 찾기(온라인)")
        b_copy = button(dlg, "주소 복사")
        chk(b_copy is not None and not b_copy.isEnabled(), "E 국외·상세 없음 — [주소 복사] 꺼짐")
        if b_on is None:
            chk(False, "E 온라인 단추 없음")
            return
        b_on.click()
        ok = pump(lambda: table_rows(dlg).get("상세 주소(온라인)", "").startswith("찾지 못했습니다"), timeout=10)
        chk(ok, "E 실패 — '찾지 못했습니다' 행", str(table_rows(dlg)))

    run_dialog(insp_e)

    # F
    open_photo(lst[0])
    pump(lambda: "address" in (mw._photo_info or {}), timeout=10)

    def insp_f(dlg):
        mw._photo_info.pop("address", None)
        mw._photo_info_dlg_fill()
        chk(table_rows(dlg).get("주소") == "찾는 중…", "F 주소가 아직이면 '찾는 중…'", str(table_rows(dlg)))
        mw._photo_addr_done(mw._photo_info_gen, mw._photo_info["path"], want, "")
        chk(table_rows(dlg).get("주소") == want, "F 늦게 온 주소로 바뀐다", str(table_rows(dlg)))
        mw._photo_addr_done(mw._photo_info_gen - 1, mw._photo_info["path"], "엉뚱", "")
        chk(table_rows(dlg).get("주소") == want, "F 지난 세대 주소는 버린다")

    run_dialog(insp_f)
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
