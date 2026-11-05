# -*- coding: utf-8 -*-
"""지도에서 위치 보기 — 고른 사진들을 한 지도에 (사진 보기 SOT 4.29, §5.1 F6·D18, 261104-7 B4·261105-17).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 브라우저 열기는 가짜로 바꿔 주소만 보고,
그 주소의 페이지는 이 검사가 직접 받아 본다(이 PC 안 서버).
A. 본문 우클릭 — GPS 있는 사진에만 '지도에서 위치 보기'
B. 여러 장 — 위치 없는·클라우드에만 있는 사진은 빼고 장수를 알린 뒤 묻는다(D18), '아니요' 면 열지 않는다
C. '예' 면 이 PC 안 서버(127.0.0.1)의 지도 페이지 — 위치·이름은 있고 파일 경로는 없다, OpenStreetMap 타일·출처
D. 서버 — Leaflet 동봉 파일·작은 사진(JPEG)·다른 Host 거절(403)·모르는 토큰(404)
E. 위치가 하나도 없으면 알림만(묻지 않고 열지 않는다)
F. 브라우저의 [PolyPDF 에서 고르기] → 책갈피창에서 그 사진들을 고름, 하나면 연다
G. 메뉴 — 책갈피창 사진 줄(한 장·'(N장)')·썸네일 줄 칸에 '지도에서 위치 보기'
H. 클라우드에만 있는 사진은 머리도 읽지 않는다(내려받지 않음, §4.37)
I. 400장 위치 읽기 — 메인 최장 공백 < 0.5초(배경)
J. 묶음 창 '7장 · 2026-11-04(2), 2026-10-23(5)' — 최근 날짜 순, 날짜는 책갈피창과 같은 값(촬영일, 없으면 파일 날짜),
   날짜 없음은 끝, 한 줄을 넘으면 '…'·전체는 툴팁 (261105-18). 페이지의 JS 를 node 로 돌려 본다(없으면 SKIP)
"""
import os, sys, tempfile, shutil, time, urllib.request, urllib.error
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, QTimer
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox
from PyQt6.QtGui import QDesktopServices
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_map_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "지도", echo=False)   # 마스터 §14.7.2 의 6
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


def http(url, host=None, data=None):
    """배경에서 받는 것처럼 — 서버가 메인 스레드를 쓰지 않으므로 여기서 바로 불러도 된다."""
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


menu_texts = []
menu_pick = {"v": None}
_orig_exec = QMenu.exec


def _fake_exec(self, *a, **k):
    menu_texts.clear()
    menu_texts.extend(x.text().split("\t")[0] if not x.isSeparator() else "-" for x in self.actions())
    want = menu_pick["v"]
    if want:
        for x in self.actions():
            if x.text().split("\t")[0] == want:
                x.trigger()          # 책갈피창 메뉴는 triggered 신호로 일한다
                return x
    return None


QMenu.exec = _fake_exec
asked, informed = [], []
answer = {"v": QMessageBox.StandardButton.No}
_orig_q, _orig_i = QMessageBox.question, QMessageBox.information
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), answer["v"])[-1])
QMessageBox.information = staticmethod(lambda *a, **k: (informed.append(a[2] if len(a) > 2 else ""), QMessageBox.StandardButton.Ok)[-1])
opened = []
_orig_open = QDesktopServices.openUrl
QDesktopServices.openUrl = staticmethod(lambda u: (opened.append(u.toString()), True)[-1])

tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_map_"))
try:
    from PIL import Image
    from viewer import photo_io, photo_map

    def gps_jpg(path, lat, lon, color=(30, 160, 60), taken="2026:11:05 10:20:30"):
        ex = Image.Exif()
        d = int(lat); m = (lat - d) * 60
        e = int(lon); n = (lon - e) * 60
        ex[0x8825] = {1: "N", 2: (float(d), float(m), 0.0), 3: "E", 4: (float(e), float(n), 0.0)}
        if taken:
            ex[0x8769] = {0x9003: taken}
        Image.new("RGB", (300, 200), color).save(path, "JPEG", exif=ex.tobytes())

    A = tmp / "a 위치.jpg"; gps_jpg(A, 37.5, 127.01)
    B = tmp / "b 없음.jpg"; Image.new("RGB", (300, 200), (60, 60, 200)).save(B, "JPEG")
    C = tmp / "c 위치.jpg"; gps_jpg(C, 35.1, 129.03, (200, 100, 30))
    K = tmp / "k 클라우드.jpg"; gps_jpg(K, 33.4, 126.5)

    # H — 클라우드에만 있는 사진(가짜 특성): 머리 읽기를 세어 본다
    _orig_cloud, _orig_info = photo_io.cloud_only, photo_io.photo_info
    read_paths = []
    photo_io.photo_info = lambda p, *a, **k: (read_paths.append(str(p)), _orig_info(p, *a, **k))[-1]
    _cloud_stats = set()
    photo_io.cloud_only = lambda st: (st.st_ino, st.st_dev) in _cloud_stats
    _st = os.stat(K); _cloud_stats.add((_st.st_ino, _st.st_dev))

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 4)

    def fnode(path):
        return next((n for n in bt._iter_file_nodes() if str(n.data(0, bt.DATA_FILE)) == str(path)), None)

    # A
    mw._on_bookmark_activated(str(B), 0)
    pump(lambda: (mw.__dict__.get("_photo_info") or {}).get("path") == str(B), timeout=5)
    mw._photo_context_menu(QPoint(5, 5))
    chk("지도에서 위치 보기" not in menu_texts, "A GPS 없는 사진의 본문 메뉴에는 지도 항목이 없다")
    mw._on_bookmark_activated(str(A), 0)
    pump(lambda: (mw.__dict__.get("_photo_info") or {}).get("gps") is not None, timeout=5)
    mw._photo_context_menu(QPoint(5, 5))
    chk("지도에서 위치 보기" in menu_texts, "A GPS 있는 사진의 본문 메뉴에 지도 항목", str(menu_texts))

    # B
    read_paths.clear()
    mw._photo_action("map", [str(A), str(B), str(C), str(K)])
    pump(lambda: asked or informed, timeout=15)
    chk(len(asked) == 1 and "2장" in asked[0] and "위치가 없는 사진 1장" in asked[0] and "클라우드" in asked[0]
        and "OpenStreetMap" in asked[0] and not opened, "B 여러 장 — 뺀 장수와 함께 묻고, '아니요' 면 열지 않는다", str(asked))
    # H
    chk(str(K) not in read_paths and str(A) in read_paths, "H 클라우드에만 있는 사진은 머리도 읽지 않는다", str(read_paths))

    # C
    answer["v"] = QMessageBox.StandardButton.Yes
    mw._photo_action("map", [str(A), str(B), str(C)])
    pump(lambda: len(asked) == 2 and opened, timeout=15)
    chk(len(asked) == 2, "C 누를 때마다 묻는다(D18)")
    url = opened[-1] if opened else ""
    chk(url.startswith("http://127.0.0.1:") and "/m/" in url, "C '예' 면 이 PC 안 서버의 지도 페이지", url)
    code, body, hdr = http(url)
    html = body.decode("utf-8", "replace")
    chk(code == 200 and "a 위치.jpg" in html and "c 위치.jpg" in html and "b 없음" not in html, "C 페이지에 위치 있는 사진 둘", str(code))
    chk("37.5" in html and "35.1" in html and "2026-11-05 10:20" in html, "C 위도·경도·촬영일")
    chk(str(tmp) not in html and str(tmp).replace("\\", "\\\\") not in html and str(tmp).replace("\\", "/") not in html,
        "C 파일 경로는 싣지 않는다")
    chk("tile.openstreetmap.org/{z}/{x}/{y}.png" in html and "OpenStreetMap" in html and "contributors" in html,
        "C OpenStreetMap 표준 타일·출처 표시")
    chk("strict-origin" in (hdr.get("Referrer-Policy") or ""), "C 타일 서버에 출처를 보내는 Referrer-Policy", str(hdr))
    chk("unpkg" not in html and "cdn" not in html.lower() and "/lib/leaflet.js" in html, "C Leaflet 은 동봉 파일(CDN 아님)")

    # D
    base = url.split("/m/")[0]
    code, body, _ = http(base + "/lib/leaflet.js")
    chk(code == 200 and b"Leaflet" in body[:400], "D 동봉 Leaflet 을 준다", str(code))
    code, body, _ = http(base + "/lib/leaflet.markercluster.js")
    chk(code == 200, "D 동봉 markercluster 를 준다", str(code))
    code, body, _ = http(url + "t/0.jpg")
    chk(code == 200 and body[:2] == b"\xff\xd8", "D 작은 사진 JPEG", str(code))
    code, body, _ = http(url + "b/1.jpg")
    chk(code == 200 and body[:2] == b"\xff\xd8", "D 큰 사진 JPEG", str(code))
    code, _, _ = http(url + "t/9.jpg")
    chk(code == 404, "D 없는 번호는 404", str(code))
    code, _, _ = http(url, host="evil.example:80")
    chk(code == 403, "D 다른 Host 는 거절(403)", str(code))
    code, _, _ = http(base + "/m/xxxxxxxx/")
    chk(code == 404, "D 모르는 토큰은 404", str(code))
    code, _, _ = http(base + "/lib/../../viewer/app.py")
    chk(code == 404, "D 동봉 목록 밖 파일은 404", str(code))

    # J — 묶음 창 날짜(장수)
    import re, json as _json, subprocess, datetime
    J = tmp / "jj"; J.mkdir()
    gps_jpg(J / "j1.jpg", 37.5, 127.01, taken="2026:10:23 09:00:00")
    gps_jpg(J / "j2.jpg", 37.5, 127.01, taken=None)                       # 촬영일 없음 → 파일 날짜
    n_open = len(opened)
    mw._photo_action("map", [str(A), str(J / "j1.jpg"), str(J / "j2.jpg")])
    pump(lambda: len(opened) > n_open, timeout=15)
    code, body, _ = http(opened[-1]) if len(opened) > n_open else (0, b"", {})
    html_j = body.decode("utf-8", "replace")
    m = re.search(r"const D = (\{.*?\});\n", html_j)
    dj = _json.loads(m.group(1)) if m else {"pts": []}
    days = {pt[2]: (pt[4] if len(pt) > 4 else None) for pt in dj["pts"]}
    today = datetime.date.fromtimestamp(os.path.getmtime(J / "j2.jpg")).isoformat()
    chk(days == {"a 위치.jpg": "2026-11-05", "j1.jpg": "2026-10-23", "j2.jpg": today},
        "J 페이지의 날짜 — 촬영일, 없으면 파일 날짜(책갈피창과 같은 값)", str(days))
    chk(all(photo_io.photo_when(str(pp))[0] == days.get(pp.name) for pp in (A, J / "j1.jpg", J / "j2.jpg")),
        "J 책갈피창 날짜(photo_io.photo_when)와 같다")
    chk(".days{" in html_j and "text-overflow:ellipsis" in html_j and "white-space:nowrap" in html_j and "s.title" in html_j,
        "J 한 줄을 넘으면 '…', 전체는 툴팁")
    fn = re.search(r"function daysText\(ids\)\{.*?\n\}", html_j, re.S)
    node = shutil.which("node")
    if not fn or not node:
        chk(bool(fn), "J daysText 가 페이지에 있다")
        print("SKIP - J 묶음 글 계산(daysText 또는 node 없음)")
    else:
        dd = {"pts": [[0, 0, "x", "", d] for d in
                      ["2026-10-23"] * 5 + ["2026-11-04"] * 2 + [""] + ["2025-01-02"]],
              "t": dj.get("t", {})}
        js = "const D = %s;\n%s\nconsole.log(daysText([0,1,2,3,4,5,6,7,8]));" % (_json.dumps(dd, ensure_ascii=False), fn.group(0))
        r = subprocess.run([node, "-e", js], capture_output=True, timeout=30)
        out = r.stdout.decode("utf-8", "replace").strip()
        chk(out == "9장 · 2026-11-04(2), 2026-10-23(5), 2025-01-02(1), 날짜 없음(1)",
            "J 묶음 글 — 총 장수 · 최근 날짜 순 날짜(장수), 날짜 없음은 끝", repr(out) + r.stderr.decode("utf-8", "replace")[:300])

    # E
    n_ask, n_open = len(asked), len(opened)
    informed.clear()
    mw._photo_action("map", [str(B)])
    pump(lambda: informed, timeout=15)
    chk(informed and "촬영 위치가 없습니다" in informed[0] and len(asked) == n_ask and len(opened) == n_open,
        "E 위치가 하나도 없으면 알림만", str(informed))

    # F — [PolyPDF 에서 고르기](두 장) · [PolyPDF 에서 열기](한 장)
    mw._on_bookmark_activated(str(B), 0); pump(timeout=0.5)
    bt.tree.clearSelection()
    code, _, _ = http(url + "pick", data=b"0,1")
    chk(code == 204, "F 고르기 요청 받음", str(code))
    sel = lambda: sorted(str(it.data(0, bt.DATA_FILE)) for it in bt.tree.selectedItems() if bt._is_file_node(it))
    pump(lambda: sel() == sorted([str(A), str(C)]), timeout=5)
    chk(sel() == sorted([str(A), str(C)]), "F 두 장 → 책갈피창에서 그 둘을 고른다", str(sel()))
    code, _, _ = http(url + "pick", data=b"1")
    pump(lambda: (mw.__dict__.get("_photo_info") or {}).get("path") == str(C), timeout=5)
    chk((mw.__dict__.get("_photo_info") or {}).get("path") == str(C), "F 한 장 → 그 사진을 연다")
    code, _, _ = http(url + "pick", data=b"0", host="evil.example:80")
    chk(code == 403, "F 다른 Host 의 고르기는 거절")

    # G — 메뉴
    an, cn = fnode(A), fnode(C)
    bt.tree.scrollToItem(an)
    bt._on_tree_context_menu(bt.tree.visualItemRect(an).center())
    chk("지도에서 위치 보기" in menu_texts, "G 책갈피창 사진 줄에 '지도에서 위치 보기'", str(menu_texts))
    bt.btn_edit.setChecked(True); pump(timeout=0.3)
    bt.tree.clearSelection(); an.setSelected(True); cn.setSelected(True)
    bt._on_tree_context_menu(bt.tree.visualItemRect(an).center())
    chk("지도에서 위치 보기 (2장)" in menu_texts, "G 두 장 고르면 '지도에서 위치 보기 (2장)'", str(menu_texts))
    n_ask = len(asked)
    an.setSelected(True); cn.setSelected(True)
    menu_pick["v"] = "지도에서 위치 보기 (2장)"
    bt._on_tree_context_menu(bt.tree.visualItemRect(an).center())
    menu_pick["v"] = None
    pump(lambda: len(asked) > n_ask, timeout=15)
    chk(len(asked) > n_ask and "2장" in asked[-1], "G 책갈피창 메뉴로 두 장 지도", str(asked[-1:]))
    bt.btn_edit.setChecked(False); pump(timeout=0.3)
    mw._photo_strip_menu(str(A), QPoint(5, 5))
    chk("지도에서 위치 보기" in menu_texts, "G 썸네일 줄 칸에 '지도에서 위치 보기'", str(menu_texts))

    # I — 400장, 메인 공백
    big = tmp / "big"; big.mkdir()
    for i in range(400):
        shutil.copyfile(A, big / ("p%03d.jpg" % i))
    gap, last = [0.0], [time.perf_counter()]

    def beat():
        now = time.perf_counter(); gap[0] = max(gap[0], now - last[0]); last[0] = now

    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat); hb.start()
    n_ask = len(asked)
    answer["v"] = QMessageBox.StandardButton.No
    t0 = time.perf_counter()
    last[0] = time.perf_counter()
    mw._photo_action("map", [str(big / ("p%03d.jpg" % i)) for i in range(400)])
    pump(lambda: len(asked) > n_ask, timeout=60)
    hb.stop()
    print("   I 400장 위치 읽기 %.2f초, 메인 최장 공백 %.3f초" % (time.perf_counter() - t0, gap[0]))
    chk(len(asked) > n_ask and "400장" in asked[-1], "I 400장 모두 표시 대상")
    chk(gap[0] < 0.5, "I 메인 최장 공백 < 0.5초(위치 읽기·페이지 만들기는 배경)", "%.3f" % gap[0])
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    QMessageBox.question = _orig_q
    QMessageBox.information = _orig_i
    QDesktopServices.openUrl = _orig_open
    try:
        photo_map.stop_server()
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
