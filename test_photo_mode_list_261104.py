# -*- coding: utf-8 -*-
"""사진 모드 — 보기 종류·토글 단추·책갈피창 그림 목록 (사진 보기 SOT 4.1·4.3·4.8·4.10, 261104-2).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 보기 종류 'PDF 전용'(기본)이면 리본의 모드 토글 단추가 숨어 있고 모드를 켤 수 없다
B. '혼용' 이면 단추가 보이고, 누르면 사진 모드 — 책갈피창은 **그림 파일만**(PDF 없음), 이름에 확장자 없음, 형식 아이콘
C. 정렬에 '확장자 순' 이 사진 모드에서만 있고, 고르면 같은 형식끼리(.jpg·.jpeg 는 한 무리)
D. 다시 누르면 PDF 모드 — PDF 만, '확장자 순' 없음
E. 사진 모드인 채 'PDF 전용' 으로 바꾸면 곧바로 PDF 모드(단추 숨김)
F. 마지막 모드는 사진 묶음(`preferences` 안 `picture`)에 남는다 — 최상위 새 키를 만들지 않는다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_mode_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 모드 목록", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=10.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is None or cond():
            if cond is None and time.monotonic() - t < 0.2:
                time.sleep(0.01)
                continue
            return True
        time.sleep(0.01)
    return False


def names(bt):
    out = []
    for it in bt._iter_file_nodes():
        out.append((it.data(0, bt.DATA_BASELABEL) or it.text(0).split("   ")[0], it.data(0, bt.DATA_FILE)))
    return out


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_mode_"))
try:
    from PIL import Image
    import fitz
    for n, ext in (("가 사진", ".jpg"), ("나 사진", ".jpeg"), ("다 도면", ".png"), ("라 움짤", ".gif")):
        Image.new("RGB", (64, 48), (90, 120, 200)).save(tmp / (n + ext))
    d = fitz.open(); d.new_page(); d.save(str(tmp / "보고서.pdf")); d.close()

    from viewer.app import MainWindow
    from viewer.widgets.icons import file_kind_icon
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    bt.load_folder(tmp); pump(lambda: len(names(bt)) == 1)

    # A
    mw._prefs.setdefault("picture", {})["view_kind"] = "pdf"
    mw._photo_apply_view_kind()
    chk(not mw._photo_btn.isVisible(), "A PDF 전용이면 토글 단추 숨김")
    mw._set_photo_mode(True)
    chk(not mw._photo_mode, "A PDF 전용이면 사진 모드를 켤 수 없다")

    # B
    mw._prefs["picture"]["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    chk(mw._photo_btn.isVisible(), "B 혼용이면 토글 단추가 보인다")
    mw._photo_btn.click()
    chk(mw._photo_mode, "B 단추를 누르면 사진 모드")
    chk(pump(lambda: len(names(bt)) == 4), "B 책갈피창에 그림 4장", str(names(bt)))
    ns = names(bt)
    chk(all(not p.lower().endswith(".pdf") for _n, p in ns), "B PDF 는 목록에 없다")
    chk(all("." not in n for n, _p in ns), "B 이름에 확장자 없음", str([n for n, _ in ns]))
    it = next(bt._iter_file_nodes())
    chk(it.icon(0).cacheKey() == file_kind_icon(it.data(0, bt.DATA_FILE)).cacheKey(), "B 줄 앞 형식 아이콘")
    chk(str(bt._count_text).startswith("4"), "B 개수 글이 장 수", bt._count_text)

    # C
    c = bt._sort_combo
    chk(c.findData(bt.SORT_EXT) >= 0, "C 사진 모드에 '확장자 순'")
    bt.set_sort_mode(bt.SORT_EXT); pump(lambda: len(names(bt)) == 4)
    kinds = [Path(p).suffix.lower() for _n, p in names(bt)]
    chk(kinds == [".gif", ".jpg", ".jpeg", ".png"], "C 확장자 순 — GIF·JPG(.jpg·.jpeg 한 무리)·PNG", str(kinds))

    # D
    mw._photo_btn.click()
    chk(not mw._photo_mode, "D 다시 누르면 PDF 모드")
    chk(pump(lambda: [Path(p).name for _n, p in names(bt)] == ["보고서.pdf"]), "D PDF 만", str(names(bt)))
    chk(c.findData(bt.SORT_EXT) < 0, "D PDF 모드엔 '확장자 순' 없음")

    # E·F
    mw._photo_btn.click()
    chk(mw._photo_mode and mw._prefs["picture"].get("mode") == "photo", "F 마지막 모드가 사진 묶음에 남는다")
    mw._prefs["picture"]["view_kind"] = "pdf"
    mw._photo_apply_view_kind()
    chk(not mw._photo_mode and not mw._photo_btn.isVisible(), "E PDF 전용으로 바꾸면 곧바로 PDF 모드")
    chk(pump(lambda: [Path(p).name for _n, p in names(bt)] == ["보고서.pdf"]), "E 목록도 PDF 로")
    data = mw._build_settings_payload()
    chk(isinstance(mw._prefs.get("picture"), dict) and mw._prefs["picture"].get("view_kind") == "pdf",
        "F 사진 값은 preferences 안 picture 묶음")
    if isinstance(data, dict):
        chk("picture" not in data and data.get("preferences", {}).get("picture", {}).get("mode") == "pdf",
            "F 저장 내용에 최상위 picture 키가 없고 preferences 안에 있다", str(list(data)[:12]))
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
