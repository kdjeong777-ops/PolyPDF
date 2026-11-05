# -*- coding: utf-8 -*-
"""사진 자동 해시태그 — 촬영일·동·장비·스크린샷·종류 (태그 SOT §5.7, 검색 SOT §5.1, 사진 보기 SOT §4.42, 261105-6).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 사진은 검사가 만든다(EXIF·GPS 포함).
A. 규칙 — 촬영일·장비 이름 정리·스크린샷·종류 낱말 규칙
B. 행정동 — 동봉 자료로 국내 동 찾기, 해외·바다는 없음
C. 저장소 — 부분(meta·kind·ocr)끼리 지우지 않는다, 거절·사용자 태그·통째 교체(set_auto)
D. 사진 모드 폴더 열기 — 색인 훑기가 머리 태그를 붙인다(백업 먼저), 색인 글로 찾는다, 다시 열면 다시 읽지 않는다
E. 종류 — 글 있는 사진만 OCR 해 영수증·명함·서류, 그림 사진·스크린샷은 없음, 읽은 글은 색인에 넣지 않는다
F. OCR 확정(§4.36) — 형식 태그를 넣어도 머리 태그가 남는다(종전 set_auto 는 자동 칸을 통째로 바꿨다)
G. 거르기 — `#2026`·`#2026-11` 앞부분 일치, `#` 풀다운은 하루 태그 대신 해·달
H. 설정 끄면 붙이지 않는다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_autotag_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 자동 태그", echo=False)   # 마스터 §14.7.2 의 6
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


def wait(sec):
    pump(lambda: False, timeout=sec)


def dms(v):
    d = int(v)
    m = int((v - d) * 60)
    s = round(((v - d) * 60 - m) * 60, 2)
    return (float(d), float(m), float(s))


def photo(path, size=(1200, 900), color=(30, 120, 200), make=None, model=None, taken=None, gps=None, fmt="JPEG", desc=None, draw=None):
    from PIL import Image
    im = Image.new("RGB", size, color)
    if draw:
        draw(im)
    ex = Image.Exif()
    if make:
        ex[0x010F] = make
    if model:
        ex[0x0110] = model
    if desc:
        ex[0x010E] = desc
    if taken:
        ex[0x0132] = taken
        ex.get_ifd(0x8769)[0x9003] = taken
    if gps:
        g = ex.get_ifd(0x8825)
        g[1], g[2], g[3], g[4] = "N", dms(gps[0]), "E", dms(gps[1])
    if fmt == "PNG":
        im.save(path, "PNG")
    else:
        im.save(path, "JPEG", exif=ex.tobytes(), quality=90)


def text_img(lines, size=(1240, 1754), font=44):
    from PIL import ImageDraw, ImageFont
    def _d(im):
        d = ImageDraw.Draw(im)
        try:
            f = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", font)
        except Exception:
            f = ImageFont.load_default()
        y = 80
        for ln in lines:
            d.text((80, y), ln, fill=(0, 0, 0), font=f)
            y += int(font * 1.6)
    return _d


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_autotag_"))
try:
    from viewer import photo_tags as PT, kr_dong, photo_index
    from viewer.tag_store import TagStore

    # ── A 규칙 ──
    chk(PT.date_tag({"taken": "2026:11:05 10:20:30"}) == "2026-11-05", "A 촬영일 — 하루 태그")
    chk(PT.date_tag({"taken": ""}) is None and PT.date_tag({"taken": "0000:00:00 00:00:00"}) is None, "A 촬영 정보 없으면 만들지 않는다")
    dv = lambda mk, md: PT.device_tag({"exif": {"Make": mk, "Model": md}})
    chk(dv("Apple", "iPhone 15 Pro") == "iPhone15Pro", "A 장비 — 모델에 제품군이 있으면 모델만", dv("Apple", "iPhone 15 Pro"))
    chk(dv("samsung", "SM-S918N") == "SamsungSM-S918N", "A 장비 — 코드 모델은 회사 + 모델, 소문자 회사는 첫 글자 대문자", dv("samsung", "SM-S918N"))
    chk(dv("NIKON CORPORATION", "NIKON Z 6") == "NIKONZ6", "A 장비 — 회사 첫 낱말, 모델에 회사가 있으면 모델만", dv("NIKON CORPORATION", "NIKON Z 6"))
    chk(dv("Canon", "") is None, "A 장비 — 모델이 없으면 만들지 않는다")
    chk(PT.is_screenshot("x.png", {"format": "PNG", "width": 1179, "height": 2556, "exif": {}}), "A 스크린샷 — 카메라 없는 화면 크기 PNG")
    chk(not PT.is_screenshot("x.png", {"format": "PNG", "width": 1179, "height": 2556, "exif": {"Model": "iPhone 15 Pro"}}),
        "A 스크린샷 아님 — 카메라 정보가 있다")
    chk(PT.is_screenshot("Screenshot_20261105.jpg", {"format": "JPEG", "width": 800, "height": 600, "exif": {}}), "A 스크린샷 — 이름")
    chk(PT.classify_text("상호 대한마트 품목 수량 단가 합계 15,000 부가세 1,364 카드승인 승인번호 1234 감사합니다") == "영수증", "A 종류 — 영수증 낱말")
    chk(PT.classify_text("Hong Gildong Manager PolyPDF Inc Tel 02-1234-5678 M. 010-9876-5432 hong@example.com www.example.com") == "명함",
        "A 종류 — 명함(짧은 글 + 연락처)")
    chk(PT.classify_text(" ".join(["paragraph%d word text" % i for i in range(40)])) == "서류", "A 종류 — 서류(빽빽한 글)")
    chk(PT.classify_text("hello world") is None, "A 종류 — 글이 적으면 없음")
    chk(PT.date_groups({"2026-11-05": 2, "2026-11-01": 1, "2025-03-02": 1, "대화동": 3}) ==
        [("2026", 3), ("2026-11", 3), ("2025", 1), ("2025-03", 1)], "A '날짜' 묶음 — 해·달, 새 것부터")

    # ── B 행정동 ──
    chk(kr_dong.dong_name(37.6766, 126.7470) == "대화동", "B 고양 일산 → 행정동 대화동", str(kr_dong.lookup(37.6766, 126.7470)))
    # 261105-13(사용자 지시 '동은 너무 세분화'): 태그 값은 시·군·구 — 구가 있는 시는 시만, 특별·광역시는 자치구
    chk(kr_dong.region_name(37.6766, 126.7470) == "고양시", "B 지역 — 구가 있는 시는 시만(고양시일산서구 → 고양시)",
        str(kr_dong.region_name(37.6766, 126.7470)))
    chk(kr_dong.region_name(37.4979, 127.0276) == "서초구", "B 지역 — 특별시는 자치구(서초구)", str(kr_dong.region_name(37.4979, 127.0276)))
    chk(kr_dong.region_name(37.2636, 127.0286) == "수원시", "B 지역 — 수원시팔달구 → 수원시", str(kr_dong.region_name(37.2636, 127.0286)))
    chk(kr_dong.region_of("경기도 연천군 연천읍") == "연천군" and kr_dong.region_of("세종특별자치시 세종시 조치원읍") == "세종시"
        and kr_dong.region_of("부산광역시 중구 남포동") == "중구", "B 지역 — 군·세종시·광역시 자치구")
    chk(kr_dong.region_name(35.6762, 139.6503) is None, "B 해외(도쿄) — 없음")
    chk(kr_dong.region_name(34.0, 126.0) is None, "B 바다 — 없음")
    inf = kr_dong.info()
    chk(inf.get("ver") == "20261001" and inf.get("count", 0) > 3000 and "CC BY 4.0" in inf.get("source", ""),
        "B 자료 판·출처(CC BY 4.0)", str(inf))

    # ── C 저장소 ──
    ts = TagStore(tmp / "c_tags.json")
    p = str(tmp / "c.jpg")
    ts.set(p, ["가족"])
    ts.set_auto_part(p, "meta", ["2026-11-05", "대화동"])
    ts.set_auto_part(p, "ocr", ["영수증"])
    chk(ts.get(p) == ["가족", "2026-11-05", "대화동", "영수증"], "C 부분 합집합 — 사용자 태그 먼저", str(ts.get(p)))
    ts.set_auto_part(p, "ocr", [])
    chk(ts.get_auto(p) == ["2026-11-05", "대화동"], "C 한 부분을 비워도 다른 부분은 남는다", str(ts.get_auto(p)))
    ts.reject(p, ["대화동"])
    ts.set_auto_part(p, "meta", ["2026-11-05", "대화동"])
    chk("대화동" not in ts.get(p) and ts.get_auto_part(p, "meta") == ["2026-11-05"], "C 거절한 태그는 다시 붙지 않는다", str(ts.get(p)))
    ts.set_auto(p, ts.get_auto(p) + ["후보채택"])                      # 새 태그 후보 채택(tag_batch_dialog) 같은 통째 교체
    ts.set_auto_part(p, "meta", ["2026-11-06"])
    chk(ts.get_auto(p) == ["2026-11-06", "후보채택"], "C 통째 교체 뒤에도 부분이 제자리 — 옛 촬영일이 남지 않는다", str(ts.get_auto(p)))
    ts.clear_auto()
    chk(ts.get(p) == ["가족"] and not ts.get_auto_part(p, "meta"), "C 자동 태그 전체 삭제 — 부분도 지운다", str(ts.get(p)))
    q = str(tmp / "q.jpg")
    ts.set(q, ["손태그"])
    chk(ts.set_auto_part(q, "kind", []) is False and ts._data[TagStore._key(q)] == ["손태그"], "C 지울 것이 없으면 기록을 건드리지 않는다")

    # ── 사진 폴더 ──
    pix = tmp / "pix"
    pix.mkdir()
    A = pix / "IMG_1001.jpg"
    photo(A, make="Apple", model="iPhone 15 Pro", taken="2026:11:05 10:20:30", gps=(37.6766, 126.7470))
    Bx = pix / "IMG_1002.jpg"
    photo(Bx, make="samsung", model="SM-S918N", taken="2025:03:02 08:00:00", gps=(35.6762, 139.6503), color=(200, 60, 40))
    SS = pix / "IMG_1003.png"
    photo(SS, size=(1179, 2556), color=(240, 240, 245), fmt="PNG")
    R = pix / "IMG_1004.jpg"
    photo(R, color=(255, 255, 255), size=(1240, 1754), make="Apple", model="iPhone 15 Pro", taken="2026:11:04 12:00:00",
          draw=text_img(["MART RECEIPT", "Milk 2 x 1,500 3,000", "Bread 1 x 2,500 2,500", "SUBTOTAL 5,500",
                         "VAT 500", "TOTAL 6,000", "CASH 10,000", "CHANGE 4,000", "THANK YOU"], font=60))
    C = pix / "IMG_1005.jpg"
    photo(C, color=(255, 255, 255), size=(1600, 1000), make="Apple", model="iPhone 15 Pro", taken="2026:11:04 12:01:00",
          draw=text_img(["Hong Gildong", "Senior Manager", "Tel 02-1234-5678", "Mobile 010-9876-5432",
                         "hong@example.com", "www.example.com"], size=(1600, 1000), font=64))
    words = ("The committee reviewed the annual maintenance plan for the regional road network and agreed "
             "that pavement inspections should continue every spring with detailed reports submitted to "
             "the council before the end of each quarter including photographs measurements and cost estimates "
             "for every section of the network").split()
    lines = [" ".join(words[i:i + 6]) for i in range(0, len(words), 6)] * 2
    D = pix / "IMG_1006.jpg"
    photo(D, color=(255, 255, 255), size=(1240, 1754), make="Apple", model="iPhone 15 Pro", taken="2026:11:04 12:02:00",
          draw=text_img(lines, font=40))

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    chk(mw._prefs.get("photo_auto_tag") is True and mw._prefs.get("photo_kind_ocr") is True, "H 설정 기본 켬")
    idx_done, kind_done = [], []
    real_done = mw._photo_index_done
    mw._photo_index_done = lambda f, x, y, n: (idx_done.append(n), real_done(f, x, y, n))
    real_kind = mw._photo_kind_start

    def _kind_start(folder):
        real_kind(folder)
        w = mw.__dict__.get("_photo_kinder")
        if w is None:
            kind_done.append("none")
        else:
            w.finished.connect(lambda: kind_done.append("done"))
    mw._photo_kind_start = _kind_start
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(pix)
    chk(pump(lambda: bool(idx_done), timeout=30), "D 사진 색인 끝")
    wait(0.8)                                   # 태그 꼬리 다시 그리기(0.5초 모음)
    tags = bt._tags
    chk(tags.get_auto(str(A)) == ["2026-11-05", "고양시", "iPhone15Pro"], "D 촬영일·지역(시·군·구)·장비", str(tags.get_auto(str(A))))
    chk(tags.get_auto(str(Bx)) == ["2025-03-02", "SamsungSM-S918N"], "D 해외 위치 — 지역 태그 없음", str(tags.get_auto(str(Bx))))
    chk(tags.get_auto(str(SS)) == ["스크린샷"], "D 스크린샷", str(tags.get_auto(str(SS))))
    from viewer.settings_store import settings_dir
    chk((Path(settings_dir()) / "file_tags.bak.json").exists(), "D 붙이기 전에 file_tags.bak.json 백업(태그 SOT §6)")
    names = lambda qq: sorted(x["name"] for x in photo_index.search(qq, folder=pix))
    # 사진 정보 색인은 쓰는 워커(종류 판정)가 도는 동안 잠깐 못 읽을 수 있다(메인은 BUSY_MS_UI 만 기다리고 빈 결과) — 결과로 기다린다
    pump(lambda: names("#고양시") == ["IMG_1001.jpg"], timeout=10)
    chk(names("#고양시") == ["IMG_1001.jpg"], "D 사진 모드 검색 — 지역 태그", str(names("#고양시")))
    chk(names("#iPhone15Pro") == ["IMG_1001.jpg", "IMG_1004.jpg", "IMG_1005.jpg", "IMG_1006.jpg"], "D 사진 모드 검색 — 장비 태그",
        str(names("#iPhone15Pro")))
    lbl = None
    for it in bt._iter_file_nodes():
        if os.path.normcase(str(it.data(0, bt.DATA_FILE) or "")) == os.path.normcase(str(A)):
            lbl = it.text(0)
    chk(lbl is not None and "고양시" in lbl, "D 책갈피창 이름 꼬리에 자동 태그", str(lbl))

    # E 종류 — 종류 워커가 끝날 때까지
    chk(pump(lambda: bool(kind_done) and mw.__dict__.get("_photo_kinder") is None and mw.__dict__.get("_photo_indexer") is None,
             timeout=240), "E 종류 판정 끝(폴더 감시가 다시 띄운 훑기까지)", str(kind_done))
    wait(0.8)
    chk(tags.get_auto_part(str(R), "kind") == ["영수증"], "E 영수증", str(tags.get_auto(str(R))))
    chk(tags.get_auto_part(str(C), "kind") == ["명함"], "E 명함", str(tags.get_auto(str(C))))
    chk(tags.get_auto_part(str(D), "kind") == ["서류"], "E 서류", str(tags.get_auto(str(D))))
    chk(not tags.get_auto_part(str(A), "kind") and not tags.get_auto_part(str(SS), "kind"), "E 그림 사진·스크린샷은 종류 없음")
    chk(names("THANK") == [] and names("committee") == [], "E 읽은 글은 색인에 넣지 않는다(D15)", f"{names('THANK')} {names('committee')}")
    chk(names("#영수증") == ["IMG_1004.jpg"], "E 종류 태그로 찾는다", str(names("#영수증")))

    # D 다시 열기 — 바뀌지 않은 사진은 다시 읽지 않는다
    emitted = []
    from viewer import photo_controller as PC
    real_one = PC.PhotoIndexWorker._autotag_one
    PC.PhotoIndexWorker._autotag_one = lambda self_, *a_, **k_: (emitted.append(a_[3]), real_one(self_, *a_, **k_))[1]
    idx_done.clear(); kind_done.clear()
    mw._photo_index_start()
    chk(pump(lambda: bool(idx_done), timeout=30), "D 다시 훑기 끝")
    chk(emitted == [], "D 다시 훑기 — 판정한 사진은 다시 읽지 않는다", str(emitted))
    PC.PhotoIndexWorker._autotag_one = real_one
    pump(lambda: bool(kind_done), timeout=60)

    # K 261105-13 — 옛 판(1, 행정동)으로 붙은 사진: 판이 오르면 다시 훑기가 동 태그를 시·군·구로 바꾼다.
    #   사용자 태그·📌 고정한 태그는 그대로, 바꾸기 전 file_tags.bak.json
    tags.set_auto_part(str(A), "meta", ["2026-11-05", "대화동", "iPhone15Pro"])        # 옛 판의 자동 태그
    tags.set(str(A), ["가족"])
    tags.set_auto_part(str(Bx), "meta", ["2025-03-02", "서초2동", "SamsungSM-S918N"])
    tags.promote(str(Bx), ["서초2동"])                                                 # 사용자가 고정한 옛 동 태그
    import sqlite3
    _c = photo_index.connect()
    _c.execute("UPDATE photos SET at_ver=1 WHERE key IN (?, ?)", (os.path.normcase(str(A)), os.path.normcase(str(Bx))))
    _c.commit(); _c.close()
    bak = Path(settings_dir()) / "file_tags.bak.json"
    try:
        bak.unlink()
    except OSError:
        pass
    idx_done.clear(); kind_done.clear()
    mw._photo_index_start()
    chk(pump(lambda: bool(idx_done), timeout=30), "K 다시 훑기 끝")
    wait(0.8)
    chk(tags.get_auto(str(A)) == ["2026-11-05", "고양시", "iPhone15Pro"], "K 옛 동 태그 → 시·군·구", str(tags.get_auto(str(A))))
    chk(tags.get_manual(str(A)) == ["가족"], "K 사용자 태그는 그대로", str(tags.get_manual(str(A))))
    chk("서초2동" in tags.get_manual(str(Bx)) and tags.get_auto(str(Bx)) == ["2025-03-02", "SamsungSM-S918N"],
        "K 고정한 옛 동 태그는 그대로", f"{tags.get_manual(str(Bx))} {tags.get_auto(str(Bx))}")
    chk(bak.exists() and "대화동" in bak.read_text(encoding="utf-8"), "K 바꾸기 전 백업에 옛 태그가 있다")
    pump(lambda: names("#대화동") == [] and names("#고양시") == ["IMG_1001.jpg"], timeout=10)
    chk(names("#대화동") == [] and names("#고양시") == ["IMG_1001.jpg"], "K 사진 모드 검색 글도 새 지역으로", f"{names('#대화동')} {names('#고양시')}")
    pump(lambda: bool(kind_done), timeout=60)

    # F OCR 확정 — 머리 태그가 남는다
    mw._photo_ocr_committed([(str(A), "family picnic", None, [])])
    chk(tags.get_auto(str(A)) == ["2026-11-05", "고양시", "iPhone15Pro"], "F OCR 확정(형식 없음)이 머리 태그를 지우지 않는다", str(tags.get_auto(str(A))))
    mw._photo_ocr_committed([(str(R), "영수증 합계", "영수증", [])])
    chk(tags.get_auto(str(R)) == ["2026-11-04", "iPhone15Pro", "영수증"],
        "F OCR 확정 형식 — 다른 부분과 함께", str(tags.get_auto(str(R))))

    # G 거르기
    def visible():
        out = []
        for it in bt._iter_file_nodes():
            if not it.isHidden():
                out.append(Path(str(it.data(0, bt.DATA_FILE))).name)
        return sorted(out)
    bt.search_edit.setText("#2026-11"); wait(0.4)
    chk(visible() == ["IMG_1001.jpg", "IMG_1004.jpg", "IMG_1005.jpg", "IMG_1006.jpg"], "G #2026-11 — 그 달 사진", str(visible()))
    bt.search_edit.setText("#2025"); wait(0.4)
    chk(visible() == ["IMG_1002.jpg"], "G #2025 — 그 해 사진", str(visible()))
    bt.search_edit.setText(""); wait(0.3)
    from PyQt6.QtWidgets import QCheckBox, QWidgetAction
    bt._rebuild_tag_menu()
    texts = []
    for act in bt._tag_menu.actions():
        if isinstance(act, QWidgetAction) and act.defaultWidget() is not None:
            texts += [c.text().strip() for c in act.defaultWidget().findChildren(QCheckBox)]
    chk(any(t.startswith("#2026  (") for t in texts) and any(t.startswith("#2026-11  (") for t in texts),
        "G 풀다운 '날짜' — 해·달", str(texts))
    chk(not any(t.startswith("#2026-11-05") for t in texts), "G 풀다운에 하루 태그를 늘어놓지 않는다", str(texts))

    # I 응답성 — 사진 1500장(GPS·EXIF) + 글 있는 사진 5장 폴더를 열어 태그가 다 붙을 때까지 메인 최장 공백(응답성 SOT §5·§7)
    big = tmp / "many"
    big.mkdir()
    s0 = big / "p0000.jpg"
    photo(s0, size=(320, 240), make="Apple", model="iPhone 15 Pro", taken="2026:10:01 09:00:00", gps=(37.5759, 126.9769))
    raw = s0.read_bytes()
    for i in range(1, 1500):
        (big / ("p%04d.jpg" % i)).write_bytes(raw)
    rraw = R.read_bytes()
    for i in range(5):
        (big / ("r%02d.jpg" % i)).write_bytes(rraw)
    gap, last = [0.0], [time.perf_counter()]

    def beat():
        now = time.perf_counter(); gap[0] = max(gap[0], now - last[0]); last[0] = now
    from PyQt6.QtCore import QTimer
    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat); hb.start()
    idx_done.clear(); kind_done.clear()
    t0 = time.perf_counter()
    mw.open_folder(big)
    ok_meta = pump(lambda: bool(idx_done) and all(tags.get_auto(str(big / ("p%04d.jpg" % i)))[:2] == ["2026-10-01", "종로구"]
                                                   for i in (0, 750, 1499)), timeout=180)
    t_meta = time.perf_counter() - t0
    ok_kind = pump(lambda: all(tags.get_auto_part(str(big / ("r%02d.jpg" % i)), "kind") == ["영수증"] for i in range(5)), timeout=240)
    t_kind = time.perf_counter() - t0
    wait(0.8)
    hb.stop()
    print("   I 1505장: 머리 태그 %.1f초, 종류 %.1f초, 메인 최장 공백 %.3f초" % (t_meta, t_kind, gap[0]))
    chk(ok_meta, "I 1500장 모두 머리 태그")
    chk(ok_kind, "I 글 있는 사진 5장 — 영수증")
    chk(gap[0] < 0.5, "I 메인 최장 공백 < 0.5초 — 태그 꼬리는 바뀐 줄만 batch_rows 안에서(한 줄씩이면 2초+)", "%.3f" % gap[0])
    mw.open_folder(pix)
    pump(lambda: mw.__dict__.get("_photo_kinder") is None and mw.__dict__.get("_photo_indexer") is None, timeout=60)

    # J 같은 함정이 다른 곳에서 다시 나지 않게(CLAUDE.md §4 의 8) — 책갈피창 파일 줄을 반복문으로 돌며 글·아이콘을 바꾸면
    #   `batch_rows()`(또는 같은 일을 하는 setUpdatesEnabled(False)) 안이어야 한다. 한 줄만 고르는 `== path` 조건은 뺀다.
    import ast
    bad = []
    for f in (Path(__file__).resolve().parent / "viewer").rglob("*.py"):
        try:
            tree_ = ast.parse(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        par = {}
        for n in ast.walk(tree_):
            for c in ast.iter_child_nodes(n):
                par[c] = n
        for n in ast.walk(tree_):
            if not (isinstance(n, ast.For) and isinstance(n.iter, ast.Call) and getattr(n.iter.func, "attr", "") == "_iter_file_nodes"):
                continue
            calls = [c for c in ast.walk(n) if isinstance(c, ast.Call) and getattr(c.func, "attr", "") in ("_apply_tag_label", "setText", "setIcon")]
            if not calls:
                continue
            single = all(any(isinstance(a, ast.If) and isinstance(a.test, ast.Compare) and isinstance(a.test.ops[0], ast.Eq)
                             for a in ast.walk(n) if c in list(ast.walk(a)) and a is not n) for c in calls)
            p_, ok = par.get(n), single
            while p_ is not None and not ok:
                if isinstance(p_, ast.With) and any("batch_rows" in ast.unparse(i.context_expr) for i in p_.items):
                    ok = True
                if isinstance(p_, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    ok = ok or "setUpdatesEnabled(False)" in ast.unparse(p_)
                    break
                p_ = par.get(p_)
            if not ok:
                bad.append("%s:%d" % (f.name, n.lineno))
    chk(not bad, "J 책갈피창 줄을 반복해 바꾸는 곳은 batch_rows 안(응답성 SOT §4 ⑥)", str(bad))

    # H 끄면 붙이지 않는다
    E2 = pix / "IMG_1007.jpg"
    photo(E2, make="Apple", model="iPhone 15 Pro", taken="2026:11:05 11:00:00", gps=(37.6766, 126.7470))
    mw._prefs["photo_auto_tag"] = False
    idx_done.clear()
    mw._photo_index_start()
    chk(pump(lambda: bool(idx_done), timeout=30), "H 훑기 끝")
    wait(0.8)
    chk(not tags.get_auto(str(E2)), "H 설정을 끄면 붙이지 않는다", str(tags.get_auto(str(E2))))
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
