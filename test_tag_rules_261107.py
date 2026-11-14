# -*- coding: utf-8 -*-
"""해시태그 사용자 규칙 — 형식 낱말 켜고 끄기·이름 바꾸기·별칭·사진 태그 종류, 저장하면 곧바로 다시 붙이기 (태그 SOT §5.8, 261107-10).

사용자 지시: "해시테그 내용은 환경설정에서 설정할 수 있도록해". 사용자 결정: 낱말·별칭·사진 종류 / 저장하면 곧바로 다시 붙임.
실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 규칙 다듬기·옮기기 함수 — 옛 붙일 이름 → 원래 이름 → 새 이름, 끈 형식은 뺀다
B. 붙일 때 — 끈 형식은 형식 없음(classify_format), 끈 사진 종류는 만들지 않음(meta_tags)
C. 저장하면 곧바로 — 규칙 파일, 자동 태그 이름 바꾸기·끄기(사용자 태그는 그대로), 백업, 작업 창 한 줄, 사진 색인 글, 끝 알림
D. 되돌리면(별칭 지움) 원래 이름으로
E. 사진 종류를 끄면 사진 머리를 다시 읽어 그 태그가 빠진다(배경)
F. 응답성 — 2만 개 파일의 저장소 옮기기가 1초 안(응답성 SOT §5), 사진 다시 읽는 동안 메인 최장 공백 < 0.5초
"""
import os, sys, tempfile, shutil, time, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_rules_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "해시태그 규칙", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond, timeout=20.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def dms(v):
    d = int(v); m = int((v - d) * 60)
    return (float(d), float(m), round(((v - d) * 60 - m) * 60, 2))


def photo(path, gps=None, model="SM-S918N", make="samsung", taken="2026:11:05 10:20:30"):
    from PIL import Image
    im = Image.new("RGB", (640, 480), (30, 120, 200))
    ex = Image.Exif()
    ex[0x010F], ex[0x0110] = make, model
    ex[0x0132] = taken
    ex.get_ifd(0x8769)[0x9003] = taken
    if gps:
        g = ex.get_ifd(0x8825)
        g[1], g[2], g[3], g[4] = "N", dms(gps[0]), "E", dms(gps[1])
    im.save(path, "JPEG", exif=ex.tobytes(), quality=85)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tag_rules_"))
try:
    from viewer import auto_tag, photo_tags, photo_io, photo_index
    from viewer.settings_store import settings_dir
    try:
        from viewer import tag_rules as TR
    except ImportError:
        TR = None
    chk(TR is not None, "준비 — viewer.tag_rules 가 있다")

    # A
    if TR:
        old = {"alias": {"보고서": "외국보고서"}}
        new = {"alias": {"SamsungSM-S918N": "GalaxyS23"}, "format_off": ["논문", "기사", "없는형식"], "photo_off": ["region", "x"]}
        n = TR.normalize(new)
        chk(n["format_off"] == ["논문"] and n["photo_off"] == ["region"], "A 알 수 없는 항목(261113-10 에 뺀 기사 포함)·사진 종류는 걸러 낸다", str(n))
        fn = TR.remapper(old, new)
        chk(fn("외국보고서", "a.pdf") == "보고서" and fn("논문", "a.pdf") is None and fn("논문", "a.jpg") == "논문"
            and fn("SamsungSM-S918N", "a.jpg") == "GalaxyS23" and fn("가족", "a.pdf") == "가족",
            "A 옮기기 — 옛 붙일 이름 → 원래 이름, 끈 항목은 PDF 에서만 뺀다, 별칭, 관계없는 태그는 그대로",
            str([fn("외국보고서", "a.pdf"), fn("논문", "a.pdf"), fn("논문", "a.jpg"), fn("SamsungSM-S918N", "a.jpg"), fn("가족", "a.pdf")]))
        dd = TR.diff(old, new)
        chk(dd["names"] and dd["photo"] and dd["formats_on"] == [], "A 바뀐 것 — 이름·사진 종류", str(dd))
        chk(TR.diff({"format_off": ["논문"]}, {})["formats_on"] == ["논문"], "A 다시 켠 형식은 다시 판정 대상")

    # B
    f = auto_tag.Features(stem="2025 연차 보고서", page_count=30, toc_titles=["1장"], aspect=0.7)
    chk(auto_tag.classify_format(f, {}) == "보고서", "B 준비 — 보고서로 판정", str(auto_tag.classify_format(f, {})))
    chk(auto_tag.classify_format(f, {"format_off": ["보고서"]}) is None, "B 끈 형식은 형식 없음")
    chk(auto_tag.classify_format(f, {"alias": {"보고서": "외국보고서"}}) == "보고서", "B 형식 이름은 고정(261113-10)")
    P1 = tmp / "pix" / "IMG_0001.jpg"
    P1.parent.mkdir()
    photo(P1, gps=(37.6766, 126.7470))
    info = photo_io.photo_info(str(P1))
    chk(photo_tags.meta_tags(str(P1), info, {}) == ["2026-11-05", "고양시", "SamsungSM-S918N"], "B 준비 — 사진 머리 태그",
        str(photo_tags.meta_tags(str(P1), info, {})))
    chk(photo_tags.meta_tags(str(P1), info, {"photo_off": ["region", "date"]}) == ["SamsungSM-S918N"], "B 끈 사진 종류는 만들지 않는다",
        str(photo_tags.meta_tags(str(P1), info, {"photo_off": ["region", "date"]})))

    if TR:
        from viewer.app import MainWindow
        mw = MainWindow(); mw._skip_save_on_close = True
        mw.resize(1100, 700); mw.show(); pump(lambda: False, 0.3)
        store = mw.bookmark_tree._tags
        docs = tmp / "docs"; docs.mkdir()
        A, B, C = str(docs / "a.pdf"), str(docs / "b.pdf"), str(docs / "c.pdf")
        # 261113-10: 종전 규칙 파일(형식 이름 바꾸기·정리 표시 없음) — 적용하면 한 번 정리도 함께(§5.8 의 6)
        (Path(settings_dir()) / "tag_rules.json").write_text(json.dumps({"alias": {"보고서": "외국보고서"}}, ensure_ascii=False), encoding="utf-8")
        store.set_auto(A, ["외국보고서"]); store.set_auto(B, ["기사", "논문", "아스팔트"]); store.set(C, ["보고서"])
        store.set_auto_part(str(P1), "meta", ["2026-11-05", "고양시", "SamsungSM-S918N"])
        con = photo_index.connect()
        photo_index.upsert(con, os.path.normcase(str(P1)), str(P1), photo_index.norm_folder(P1.parent), P1.name, ".jpg",
                           P1.stat().st_size, P1.stat().st_mtime_ns, info, store.get(str(P1)))
        con.commit(); con.close()
        jobs_seen, ends = [], []
        real_add = mw.job_add
        mw.job_add = lambda jid, label, **k: (jobs_seen.append(label), real_add(jid, label, **k))[1]
        msgs = []
        mw.status.messageChanged.connect(lambda m: m and msgs.append(m))
        bak = Path(settings_dir()) / "file_tags.bak.json"
        try:
            bak.unlink()
        except OSError:
            pass

        # C
        rules = {"alias": {"보고서": "외국보고서", "SamsungSM-S918N": "GalaxyS23"}, "format_off": ["논문"]}
        job = TR.apply(mw, rules)
        job.ended.connect(lambda n: ends.append(n))
        chk(pump(lambda: bool(ends)), "C 저장하면 곧바로 — 끝났다")
        saved = json.loads((Path(settings_dir()) / "tag_rules.json").read_text(encoding="utf-8"))
        chk(saved.get("alias") == {"SamsungSM-S918N": "GalaxyS23"} and saved.get("format_off") == ["논문"] and saved.get("pdf_auto_v") == TR.PDF_AUTO_V,
            "C 규칙 파일 — 형식 이름 바꾸기는 버리고 정리 표시", str(saved))
        chk(auto_tag.load_rules().get("format_off") == ["논문"], "C 앱이 읽는 규칙도 같다")
        chk(store.get_auto(A) == ["보고서"], "C 종전 형식 이름 바꾸기는 원래 이름으로(261113-10)", str(store.get_auto(A)))
        chk(store.get_auto(B) == ["아스팔트"], "C 끈 형식·뺀 형식(기사)은 빠지고 다른 태그는 그대로", str(store.get_auto(B)))
        chk(store.get_manual(C) == ["보고서"], "C 사용자 태그는 그대로", str(store.get(C)))
        chk(store.get_auto_part(str(P1), "meta") == ["2026-11-05", "고양시", "GalaxyS23"], "C 사진 장비 별칭 — 부분째",
            str(store.get_auto_part(str(P1), "meta")))
        chk(bak.exists(), "C 바꾸기 전 file_tags.bak.json 백업")
        chk("해시태그 규칙 적용" in jobs_seen, "C 작업 창에 한 줄", str(jobs_seen))
        chk(any("해시태그 규칙 적용 시작" in m for m in msgs) and any("해시태그 규칙 적용 끝" in m for m in msgs), "C 시작·끝 알림", str(msgs[-3:]))
        names = lambda q: sorted(x["name"] for x in photo_index.search(q, folder=P1.parent))
        chk(pump(lambda: names("#GalaxyS23") == ["IMG_0001.jpg"], 10), "C 사진 모드 검색 글도 새 이름", str(names("#GalaxyS23")))

        # D 되돌리기
        ends.clear()
        TR.apply(mw, {})
        chk(pump(lambda: bool(ends)), "D 끝났다")
        chk(store.get_auto(A) == ["보고서"] and store.get_auto_part(str(P1), "meta")[-1] == "SamsungSM-S918N",
            "D 별칭을 지우면 원래 이름으로", f"{store.get_auto(A)} {store.get_auto_part(str(P1), 'meta')}")

        # E·F 사진 종류 끄기 — 머리 다시 읽기(배경), 메인 공백
        many = tmp / "many"; many.mkdir()
        raw = P1.read_bytes()
        con = photo_index.connect()
        for i in range(300):
            q = many / ("p%03d.jpg" % i)
            q.write_bytes(raw)
            photo_index.upsert(con, os.path.normcase(str(q)), str(q), photo_index.norm_folder(many), q.name, ".jpg",
                               q.stat().st_size, q.stat().st_mtime_ns, info, [])
        con.commit(); con.close()
        gap, last = [0.0], [time.perf_counter()]

        def beat():
            now = time.perf_counter(); gap[0] = max(gap[0], now - last[0]); last[0] = now
        hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat); hb.start()
        ends.clear()
        TR.apply(mw, {"photo_off": ["region"]})
        chk(pump(lambda: bool(ends), 60), "E 끝났다")
        hb.stop()
        chk(store.get_auto_part(str(P1), "meta") == ["2026-11-05", "SamsungSM-S918N"], "E 지역을 끄면 사진 머리를 다시 읽어 지역 태그가 빠진다",
            str(store.get_auto_part(str(P1), "meta")))
        chk(store.get_auto_part(str(many / "p150.jpg"), "meta") == ["2026-11-05", "SamsungSM-S918N"], "E 다른 폴더의 사진도",
            str(store.get_auto_part(str(many / "p150.jpg"), "meta")))
        print("   E 사진 301장 다시 읽기 — 메인 최장 공백 %.3f초" % gap[0])
        chk(gap[0] < 0.5, "F 사진 다시 읽는 동안 메인 최장 공백 < 0.5초", "%.3f" % gap[0])
        mw.close()

        # F 저장소 2만 개 옮기기
        from viewer.tag_store import TagStore
        big = TagStore(tmp / "big_tags.json")
        with big.bulk():
            for i in range(20000):
                big.set_auto(str(tmp / "z" / ("f%05d.pdf" % i)), ["보고서", "아스팔트"])
        t0 = time.perf_counter()
        ch = big.remap_auto(TR.remapper({}, {"format_off": ["보고서"]}))   # 261113-10: 형식 이름은 못 바꾼다 — 끄기로 모두 옮김
        dt = time.perf_counter() - t0
        print("   F 2만 개 옮기기 %.3f초" % dt)
        # 응답성 SOT §5 기준(최장 정지 < 1초) — 단독 0.28초, 검사 여럿을 함께 돌리면 0.6초까지(261107 실측)
        chk(len(ch) == 20000 and dt < 1.0, "F 2만 개 파일 옮기기 1초 안(메인, 응답성 SOT §5)", "%d %.3f" % (len(ch), dt))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
