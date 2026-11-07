# -*- coding: utf-8 -*-
"""zip 압축 풀기 — 책갈피창·썸네일 줄·본문 (사진 보기 SOT §4.24.1, 261106-5 사용자 지시·결정 '두 모드 모두'·'펼쳐서 보기').

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 풀기 모듈 — 한글 이름(UTF-8 표시 없는 cp949 zip), 경로 탈출 이름은 빼고, 있는 파일은 덮어쓰지 않고 'name (1)',
   부풀림이 큰 항목(압축 폭탄 꼴)은 뺀다, '여기에 풀기' 폴더 이름은 겹치지 않게 'name (2)'
B. PDF 모드 — PDF 가 든 zip 만 목록에(사진 zip·전달 묶음 .polypdf.zip 은 아님), 펼치면 안의 PDF 줄, 그 줄을 누르면 캐시 사본이 본문에,
   zip 줄을 눌러도 본문에 zip 을 열지 않는다, 우클릭 = 풀기 메뉴(PDF 저장 묶음 없음)
C. '여기에 풀기' — zip 옆 zip 이름 폴더에 모두(글 파일 포함), 다시 하면 'name (2)', 배경·작업 창, 끝나면 목록에 새 PDF
D. 고른 줄만 '고른 n개 풀기...' — 고른 폴더에 그것만
E. 사진 모드 — zip 줄 우클릭 맨 위 풀기, zip 을 연 뒤 썸네일 줄에서 고른 사진만 풀기(폴더 없이 한 곳에), 본문 우클릭에도
F. 푸는 동안 메인 하트비트 공백 < 0.5초(응답성 SOT §5)
"""
import os, sys, tempfile, shutil, time, zipfile, struct
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu, QFileDialog
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_zip_unpack_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "zip 풀기", echo=False)   # 마스터 §14.7.2 의 6
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


def pdf_bytes(text="x"):
    import fitz
    d = fitz.open()
    d.new_page().insert_text((72, 72), text)
    b = d.tobytes()
    d.close()
    return b


def cp949_zip(path, entries):
    """UTF-8 표시 없이 cp949 이름을 넣은 zip(윈도우 탐색기 꼴)."""
    class CpInfo(zipfile.ZipInfo):
        def _encodeFilenameFlags(self):              # 파이썬은 ASCII 밖 이름을 UTF-8(0x800)로 쓴다 — cp949 그대로, 표시 없이
            return self.filename.encode("cp437"), self.flag_bits & ~0x800
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            zi = CpInfo(name.encode("cp949").decode("cp437"), date_time=(2026, 1, 2, 3, 4, 6))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_zip_unpack_"))
out = Path(str(tmp) + "_out")
out.mkdir(exist_ok=True)
try:
    from viewer import zip_unpack as zu

    # A
    za = tmp / "a_test.zip"
    cp949_zip(za, [("한글 문서.txt", b"hello"), ("하위/보고서.pdf", pdf_bytes()), ("../evil.txt", b"x"),
                   ("C:/evil2.txt", b"x"), ("zeros.bin", b"\0" * (16 * 1024 * 1024))])
    names = [s for _r, s in zu.members(za)]
    chk("한글 문서.txt" in names and "하위/보고서.pdf" in names, "A cp949 zip 의 한글 이름을 바로 읽는다", str(names))
    chk("zeros.bin" not in names, "A 부풀림이 큰 항목(폭탄 꼴)은 뺀다", str(names))
    a_dest = tmp / "a_dest"
    w, sk, st = zu.unpack(za, a_dest)
    rel = sorted(os.path.relpath(p, a_dest) for p in w)
    chk(rel == sorted(["evil.txt", "evil2.txt", "한글 문서.txt", os.path.join("하위", "보고서.pdf")]),
        "A 탈출 이름은 dest 안으로만(.. ·드라이브 뺌) — 밖에 쓰지 않는다", str(rel))
    chk(not (tmp / "evil.txt").exists() and not Path("C:/evil2.txt").exists(), "A dest 밖에는 아무것도 없다")
    w2, _s, _t = zu.unpack(za, a_dest, names=[r for r, s in zu.members(za) if s == "한글 문서.txt"])
    chk(len(w2) == 1 and Path(w2[0]).name == "한글 문서 (1).txt" and (a_dest / "한글 문서.txt").read_bytes() == b"hello",
        "A 있는 파일은 덮어쓰지 않고 'name (1)'", str(w2))
    chk(zu.target_dir(za).name == "a_test", "A '여기에 풀기' 폴더 = zip 이름")
    (tmp / "a_test").mkdir()
    chk(zu.target_dir(za).name == "a_test (2)", "A 이미 있으면 'name (2)'", zu.target_dir(za).name)
    (tmp / "a_test").rmdir()
    za.unlink()
    shutil.rmtree(a_dest)

    # 준비 — PDF zip · 사진 zip · 전달 묶음 · PDF 한 개
    from PIL import Image
    (tmp / "plain.pdf").write_bytes(pdf_bytes("plain"))
    zd = tmp / "docs.zip"
    with zipfile.ZipFile(zd, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc1.pdf", pdf_bytes("one"))
        z.writestr("sub/doc2.pdf", pdf_bytes("two"))
        z.writestr("readme.txt", b"read me")
        z.writestr("big.bin", os.urandom(24 * 1024 * 1024))     # 하트비트용(압축 안 되는 24 MB)
    zp = tmp / "pics.zip"
    import io
    with zipfile.ZipFile(zp, "w") as z:
        for i in range(3):
            b = io.BytesIO(); Image.new("RGB", (64, 48), (40 * i, 90, 160)).save(b, "JPEG")
            z.writestr("p%d.jpg" % i, b.getvalue())
    with zipfile.ZipFile(tmp / "share.polypdf.zip", "w") as z:
        z.writestr("x.pdf", pdf_bytes())

    from viewer.app import MainWindow
    from viewer import photo_zip
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw.open_folder(tmp)

    def listed():
        return sorted(Path(it.data(0, bt.DATA_FILE)).name for it in bt._iter_file_nodes())
    pump(lambda: "docs.zip" in listed(), timeout=20)

    # B
    L = listed()
    chk("docs.zip" in L and "plain.pdf" in L and "pics.zip" not in L and "share.polypdf.zip" not in L,
        "B PDF 모드 목록 — PDF 든 zip 만(사진 zip·전달 묶음 아님)", str(L))
    node = next(it for it in bt._iter_file_nodes() if it.data(0, bt.DATA_FILE).endswith("docs.zip"))
    node.setExpanded(True); pump(timeout=0.3)
    kids = [node.child(i) for i in range(node.childCount())]
    chk(sorted(k.text(0) for k in kids) == ["doc1", "doc2"] and all(k.data(0, bt.DATA_ZIP_MEMBER) for k in kids),
        "B 펼치면 안의 PDF 줄", str([k.text(0) for k in kids]))
    before = mw.main_view.current_file()
    bt._on_activated(node, 0); pump(timeout=0.5)
    chk(mw.main_view.current_file() == before, "B zip 줄을 눌러도 본문에 zip 을 열지 않는다")
    k1 = next(k for k in kids if k.text(0) == "doc1")
    bt._on_activated(k1, 0)
    ok = pump(lambda: (mw.main_view.current_file() or "") and photo_zip.is_cached(mw.main_view.current_file()), timeout=10)
    chk(ok and Path(mw.main_view.current_file()).name == "doc1.pdf", "B 안 PDF 줄을 누르면 캐시 사본이 본문에",
        str(mw.main_view.current_file()))
    chk((mw.main_view.doc.page_count if getattr(mw.main_view, "doc", None) is not None else 1) >= 1, "B 사본 PDF 가 열린다")
    _exec = QMenu.exec
    menus = []

    def cap(self, *a, **k):
        menus.append([x.text() for x in self.actions() if not x.isSeparator()])
        return None
    QMenu.exec = cap
    rect = bt.tree.visualItemRect(node)
    bt._on_tree_context_menu(rect.center())
    node.setExpanded(True); pump(timeout=0.3)          # 앞에서 zip 줄을 눌러 접혔다
    rect = bt.tree.visualItemRect(k1)
    bt._on_tree_context_menu(rect.center())
    QMenu.exec = _exec
    m0 = menus[0] if menus else []
    chk(m0[:2] == ["여기에 풀기", "다른 폴더에 풀기"] and not any("저장" in t for t in m0), "B zip 줄 우클릭 = 풀기 메뉴(저장 묶음 없음)", str(m0))
    chk(len(menus) > 1 and menus[1][0] == "고른 1개 풀기", "B 안 줄 우클릭 = '고른 1개 풀기' 먼저", str(menus[1:] and menus[1]))

    # C — 여기에 풀기 + 하트비트
    gaps = []
    last = [time.monotonic()]

    def beat():
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(beat)
    jobs_seen = []
    _ja = mw.job_add
    mw.job_add = lambda jid, label, cancel=None, discard=None: (jobs_seen.append(label), _ja(jid, label, cancel, discard))[1]
    hb.start(); last[0] = time.monotonic()
    bt.zipUnpackRequested.emit(str(zd), None, "here")
    done = pump(lambda: (tmp / "docs" / "readme.txt").exists() and not mw._jobs, timeout=60)
    hb.stop()
    chk(done and sorted(os.listdir(tmp / "docs")) == ["big.bin", "doc1.pdf", "readme.txt", "sub"]
        and (tmp / "docs" / "sub" / "doc2.pdf").exists(), "C 여기에 풀기 — zip 옆 'docs' 폴더에 모두(폴더 구조 그대로)",
        str(os.listdir(tmp / "docs") if (tmp / "docs").exists() else None))
    chk(jobs_seen and "docs.zip" in jobs_seen[0], "C 작업 창에 오른다(중단할 수 있다)", str(jobs_seen))
    chk(gaps and max(gaps) < 0.5, "F 푸는 동안 메인 하트비트 공백 < 0.5초", "%.2f" % (max(gaps) if gaps else -1))
    ok = pump(lambda: any(n == "doc1.pdf" for n in listed()), timeout=20)
    chk(ok, "C 끝나면 책갈피창에 새로 푼 PDF", str(listed()))
    bt.zipUnpackRequested.emit(str(zd), None, "here")
    chk(pump(lambda: (tmp / "docs (2)" / "readme.txt").exists() and not mw._jobs, timeout=60), "C 다시 풀면 'docs (2)'")

    # D — 고른 것만
    _gd = QFileDialog.getExistingDirectory
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(out / "d"))
    (out / "d").mkdir()
    bt.zipUnpackRequested.emit(str(zd), ["sub/doc2.pdf"], "pick")
    chk(pump(lambda: (out / "d" / "sub" / "doc2.pdf").exists() and not mw._jobs, timeout=30)
        and sorted(os.listdir(out / "d")) == ["sub"], "D 고른 것만 고른 폴더에", str(os.listdir(out / "d")))

    # E — 사진 모드
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump()
    mw.open_folder(tmp)
    pump(lambda: "pics.zip" in listed(), timeout=20)
    chk("pics.zip" in listed() and "docs.zip" not in listed(), "E 사진 모드 목록 — 사진 zip 만", str(listed()))
    pnode = next(it for it in bt._iter_file_nodes() if it.data(0, bt.DATA_FILE).endswith("pics.zip"))
    menus.clear()
    QMenu.exec = cap
    bt._on_tree_context_menu(bt.tree.visualItemRect(pnode).center())
    QMenu.exec = _exec
    chk(menus and menus[0][:2] == ["여기에 풀기", "다른 폴더에 풀기"], "E 사진 zip 줄 우클릭 맨 위 = 풀기", str(menus[:1]))
    mw._on_bookmark_activated(str(tmp / "pics.zip"), 0)
    strip = mw._photo_strip_widget()
    pump(lambda: len(strip.paths()) == 3, timeout=20)
    sel = strip.paths()[:2]
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(out / "e"))
    (out / "e").mkdir()
    menus.clear()
    m = QMenu()
    a = mw._zip_pick_action(m, sel)
    chk(a is not None and a.text() == "고른 2장 풀기", "E 썸네일 줄 우클릭 — '고른 2장 풀기'", a.text() if a else "")
    mw._zip_unpack_cached(sel)
    chk(pump(lambda: len(os.listdir(out / "e")) == 2 and not mw._jobs, timeout=30)
        and sorted(os.listdir(out / "e")) == sorted(Path(p).name for p in sel), "E 고른 사진만 고른 폴더에", str(os.listdir(out / "e")))
    m1 = QMenu()
    a1 = mw._zip_pick_action(m1, [strip.paths()[0]])
    chk(a1 is not None and a1.text() == "이 사진 풀기", "E 본문(사진 한 장) 우클릭 — '이 사진 풀기'")
    m2 = QMenu()
    chk(mw._zip_pick_action(m2, [str(tmp / "plain.pdf")]) is None, "E zip 밖 파일에는 풀기가 없다")
    QFileDialog.getExistingDirectory = _gd
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
