# -*- coding: utf-8 -*-
"""사진 → Word·HWPX·텍스트 변환 (사진 보기 SOT 4.35, 261104-10 P4-b).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). OCR 낱말은 사진 한 장 OCR 과 같은 꼴로
study.db 에 직접 넣는다(Tesseract 없이 — 읽는 길은 test_photo_ocr_261104 가 본다).
261112-22: '변환' 은 변환 창(그림으로 저장 + 문서로, §4.46)을 먼저 연다 — 문서 길은 그 창의 [Word·HWPX·텍스트로] 단추로 간다.
검사도 그 길로(창의 exec 를 '문서로 단추 누름' 으로 바꾼다 — 단추가 없으면 문서 길에 못 닿아 실패).
A. 사진 모드에서 '변환...' 이 켜진다, 변환 창에 '문서로' 단추, 형식은 사진에 뜻 있는 것만
B. 읽지 않은 사진 — 알림만(파일을 만들지 않는다)
C. 텍스트 · Word(편집 가능) · Word(모양 그대로) · HWPX(편집 가능) — 사진 옆에 같은 이름으로, 글이 들어간다
D. 보기 회전 90° — 돈 판으로 구워 글 차례가 맞다
E. 덮어쓴 사진(낡은 OCR) — 알림만
F. zip 안 사진 — 알림만, 임시 PDF 는 남지 않는다
"""
import os, sys, tempfile, shutil, time, zipfile, io, glob
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_conv_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 변환", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_conv_"))
try:
    from PIL import Image
    from viewer.study import ocr as O
    from viewer.study.study_store import StudyStore, file_key_for
    a = tmp / "a 영수증.jpg"
    Image.new("RGB", (1200, 800), (250, 250, 250)).save(a, "JPEG")
    b = tmp / "b 안읽음.jpg"
    Image.new("RGB", (600, 400), (200, 200, 200)).save(b, "JPEG")

    def seed(path, lines):
        """사진 한 장 OCR 이 남기는 꼴 — 회전 0 판 px = pt, dpi 72, engine 끝에 photo_sig."""
        words = []
        for i, t in enumerate(lines):
            x = 100
            for wd in t.split():
                words.append({"surface": wd, "x0": x, "y0": 100 + i * 120, "x1": x + 40 * len(wd), "y1": 160 + i * 120, "conf": 95})
                x += 40 * len(wd) + 30
        st = StudyStore()
        k = file_key_for(str(path))
        st.save_page(k, 0, "\n".join(lines), dpi=72, engine="tesseract|" + O.photo_sig(path), source="ocr", conf=95,
                     words=words, lang="eng")
        st.set_meta(k, str(path), 1, "eng")
        st.close()
    seed(a, ["RECEIPT NUMBER 4821", "TOTAL AMOUNT 15000"])

    from viewer.app import MainWindow
    from viewer import convert
    from viewer.widgets import convert_dialog
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 2)

    notes, shown = [], []
    QMessageBox.information = staticmethod(lambda *a_, **k: notes.append(a_[2] if len(a_) > 2 else "") or 0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.No)
    pick = {"key": "txt"}

    class FakeDlg:
        DialogCode = convert_dialog.ConvertDialog.DialogCode

        def __init__(self, *a_, keys=None, **k):
            shown.append(tuple(keys) if keys is not None else None)
            self.keys = keys

        def exec(self):
            return self.DialogCode.Accepted

        def format_key(self):
            return pick["key"]
    convert_dialog.ConvertDialog = FakeDlg

    # 변환 창(§4.46) — 창을 띄우는 대신 [Word·HWPX·텍스트로] 를 누른다(실제 단추의 click → _doc → doc_fn)
    from viewer.widgets import image_tune_dialog
    tune_seen, doc_ok = [], []

    def _tune_exec(self):
        tune_seen.append(sorted(self.doc_buttons))
        b = self.doc_buttons.get("doc")
        if b is not None:
            b.click()
        return 0
    image_tune_dialog.ImageTuneDialog.exec = _tune_exec
    _orig_doc = mw._photo_convert_doc

    def _doc_spy(files, fmt=None):
        doc_ok.append(_orig_doc(files, fmt))
        return doc_ok[-1]
    mw._photo_convert_doc = _doc_spy

    def to_doc(files):
        n = len(doc_ok)
        mw.action_convert(files=files)
        pump(lambda: len(doc_ok) > n, timeout=5)
        return doc_ok[-1] if len(doc_ok) > n else None

    # A
    mw._on_bookmark_activated(str(a), 0); pump(timeout=0.5)
    act = mw._cmds.get("file.export")
    chk(act is not None and act.isEnabled(), "A 사진 모드에서 '변환...' 켜짐")

    # B
    to_doc([str(b)]); pump(timeout=0.3)
    chk(tune_seen and tune_seen[-1] == ["doc"], "A 변환 창에 '문서로' 단추", str(tune_seen[-1:]))
    chk(notes and "먼저" in notes[-1] and not list(tmp.glob("b 안읽음.*[!g]")), "B 읽지 않은 사진 — 알림만", str(notes[-1:]))

    # C
    def conv(key, path=a):
        pick["key"] = key
        before = set(os.listdir(tmp))
        ok = to_doc([str(path)])
        pump(timeout=0.3)
        new = sorted(set(os.listdir(tmp)) - before)
        return ok, new
    ok, new = conv("txt")
    chk(shown and set(shown[-1]) == set(convert.PHOTO_KEYS), "A 형식은 사진에 뜻 있는 것만", str(shown[-1:]))
    txt = (tmp / "a 영수증.txt")
    body = txt.read_text(encoding="utf-8") if txt.exists() else ""
    chk(ok and new == ["a 영수증.txt"] and "RECEIPT NUMBER 4821" in body and "TOTAL AMOUNT 15000" in body,
        "C 텍스트 — 사진 옆, 글이 들어간다", f"{new} {body[:80]!r}")
    ok, new = conv("docx_edit")
    import docx
    dtext = "\n".join(p.text for p in docx.Document(str(tmp / new[0])).paragraphs) if ok and new else ""
    chk(ok and new == ["a 영수증.docx"] and "4821" in dtext, "C Word(편집 가능)", f"{new} {dtext[:80]!r}")
    ok, new = conv("docx_shape")
    dtext = ""
    if ok and new:
        d = docx.Document(str(tmp / new[0]))
        dtext = "\n".join(p.text for p in d.paragraphs) + "".join(c.text for t in d.tables for r in t.rows for c in r.cells)
    chk(ok and new == ["a 영수증 (2).docx"] and "4821" in dtext, "C Word(모양 그대로)", f"{new} {dtext[:80]!r} {notes[-1:]}")
    ok, new = conv("hwpx_edit")
    htext = ""
    if ok and new:
        with zipfile.ZipFile(tmp / new[0]) as z:
            htext = "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    chk(ok and new == ["a 영수증.hwpx"] and "4821" in htext, "C HWPX(편집 가능)", str(new))

    # D — 보기 회전 90°
    c = tmp / "c 돌림.jpg"
    Image.new("RGB", (800, 1200), (250, 250, 250)).save(c, "JPEG")
    # 회전 0 판(800×1200)에서 글이 세로로 — 시계 방향 90° 로 돌려 보면 가로 줄 'LEFT RIGHT'
    st = StudyStore(); k = file_key_for(str(c))
    view = [{"surface": "LEFT", "x0": 100, "y0": 100, "x1": 300, "y1": 160, "conf": 95},
            {"surface": "RIGHT", "x0": 330, "y0": 100, "x1": 560, "y1": 160, "conf": 95}]
    rot0 = O.photo_words_view(view, 270, 1200, 800)          # 돈 판(1200×800) → 회전 0 판
    st.save_page(k, 0, "LEFT RIGHT", dpi=72, engine="tesseract|" + O.photo_sig(c), source="ocr", conf=95, words=rot0, lang="eng")
    st.close()
    mw._on_bookmark_activated(str(c), 0); pump(timeout=0.4)
    mw._photo_rotate(+90, path=str(c)); pump(timeout=0.3)
    ok, new = conv("txt", c)
    body = (tmp / "c 돌림.txt").read_text(encoding="utf-8") if (tmp / "c 돌림.txt").exists() else ""
    chk(ok and "LEFT RIGHT" in body, "D 보기 회전대로 — 글 차례가 맞다", repr(body[:60]))

    # E — 덮어쓴 사진
    time.sleep(0.05)
    Image.new("RGB", (1200, 800), (240, 240, 240)).save(a, "JPEG")
    n0 = len(notes)
    ok, new = conv("txt")
    chk(not ok and not new and len(notes) > n0, "E 덮어쓴 사진(낡은 OCR) — 알림만", str(new))

    # F — zip 안 사진
    zp = tmp / "묶음.zip"
    buf = io.BytesIO(); Image.new("RGB", (300, 200), (10, 10, 10)).save(buf, "JPEG")
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("안.jpg", buf.getvalue())
    from viewer import photo_zip
    inner = photo_zip.extract(zp)[0]
    n0 = len(notes)
    ok = to_doc([inner]); pump(timeout=0.3)
    chk(not ok and len(notes) > n0 and "PC 로 복사" in notes[-1], "F zip 안 사진 — 알림만", str(notes[-1:]))
    pick["key"] = "txt"; to_doc([str(c)]); pump(timeout=0.3)   # 다음 변환이 앞에 남은 것을 거둔다
    left = glob.glob(os.path.join(tempfile.gettempdir(), "polypdf_photosrc_*", "*.pdf"))
    chk(not left, "F 임시 PDF 는 남지 않는다", str(left[:3]))
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
