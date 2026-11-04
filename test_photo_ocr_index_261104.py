# -*- coding: utf-8 -*-
"""OCR 확정 사진 — 사진 정보 색인·자동 태그 (사진 보기 SOT 4.36, 태그 SOT §5.3, 261104-10 P4-c, D15).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 보류 저장소를 켠다(단어학습 SOT §14.21).
OCR 결과는 사진 한 장 OCR 과 같은 꼴로 보류 저장소에 직접 넣는다(Tesseract 없이 — 읽는 길은 test_photo_ocr_261104).
A. 확정 전 — 사진 모드 검색이 OCR 글로 찾지 않는다, 자동 태그 없음
B. 확정('저장 안 한 OCR' 저장) — 사진 정보 색인 그 행의 글로 찾는다
C. 자동 태그 — 영수증 글이면 형식 '영수증'·키워드, 사용자 태그는 그대로
D. 영수증이 아닌 사진 — 형식 태그 없음(사진은 영수증만)
E. PDF 색인은 걸지 않는다(G2)
F. 색인 다시 훑기 — 확정 글을 함께 넣고, 덮어써 낡은 글·보류 글은 넣지 않는다
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
QCoreApplication.setApplicationName("polypdf_photo_ocrix_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 OCR 색인", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_ocrix_"))
try:
    from PIL import Image
    from viewer.study import study_store, ocr as O
    from viewer.study.study_store import StudyStore, file_key_for
    study_store.enable_pending(True)
    a = tmp / "IMG_0001.jpg"
    b = tmp / "IMG_0002.jpg"
    for p, c in ((a, (250, 250, 250)), (b, (200, 220, 240))):
        Image.new("RGB", (900, 600), c).save(p, "JPEG")
    RECEIPT = ("영수증 사업자등록번호 123-45-67890 상호 대한건설 공급가액 13,636 부가세 1,364 합계 15,000 "
               "asphalt mixture sample delivery asphalt binder")

    def seed(path, text):
        words = [{"surface": w, "x0": 10 + i * 60, "y0": 20, "x1": 60 + i * 60, "y1": 50, "conf": 95}
                 for i, w in enumerate(text.split())]
        st = StudyStore()
        k = file_key_for(str(path))
        st.save_page(k, 0, text, dpi=72, engine="tesseract|" + O.photo_sig(path), source="ocr", conf=95, words=words, lang="kor+eng")
        st.set_meta(k, str(path), 1, "kor+eng")
        st.close()
        return k
    ka = seed(a, RECEIPT)
    kb = seed(b, "family picnic at the lake summer holiday")

    from viewer.app import MainWindow
    from viewer import photo_index
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    idx_done = []
    real_done = mw._photo_index_done
    mw._photo_index_done = lambda f, x, y, n: (idx_done.append(n), real_done(f, x, y, n))
    pdf_ix = []
    real_single = mw._index_single_file
    mw._index_single_file = lambda p, *a_, **k_: (pdf_ix.append(str(p)), real_single(p, *a_, **k_))
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: bool(idx_done), timeout=15), "사진 색인 끝")
    names = lambda q: sorted(x["name"] for x in photo_index.search(q, folder=tmp))
    tags = bt._tags
    tags.set(str(a), ["가족"])                      # 사용자 태그

    # A
    chk(names("공급가액") == [] and names("picnic") == [], "A 확정 전 — OCR 글로 찾지 않는다", str(names("공급가액")))
    chk(not tags.get_auto(str(a)), "A 확정 전 — 자동 태그 없음", str(tags.get_auto(str(a))))

    # B·C·D·E
    mw._pending_apply([ka, kb], True); pump(timeout=0.5)
    chk(names("공급가액") == ["IMG_0001.jpg"] and names("picnic") == ["IMG_0002.jpg"], "B 확정 — 사진 속 글로 찾는다",
        f"{names('공급가액')} {names('picnic')}")
    chk(tags.get_auto(str(a)) == ["영수증"], "C 영수증 글 — 형식 '영수증'", str(tags.get_auto(str(a))))
    kw = tags.get_keywords(str(a)) or []
    chk(kw and all(all(part in RECEIPT for part in k.split()) for k in kw) and any("asphalt" in k for k in kw),
        "C 키워드 — 확정 글에서", str(kw))
    chk("가족" in tags.get_manual(str(a)), "C 사용자 태그는 그대로", str(tags.get_manual(str(a))))
    chk(names("영수증") and "IMG_0001.jpg" in names("영수증"), "C 태그도 사진 색인 글에", str(names("영수증")))
    chk(not tags.get_auto(str(b)), "D 영수증이 아닌 사진 — 형식 태그 없음", str(tags.get_auto(str(b))))
    chk(not any(Path(p).suffix.lower() == ".jpg" for p in pdf_ix), "E PDF 색인은 걸지 않는다", str(pdf_ix))

    # F — 다시 훑기
    c = tmp / "IMG_0003.jpg"
    Image.new("RGB", (900, 600), (120, 120, 120)).save(c, "JPEG")
    kc = seed(c, "invoice number 778 crushed stone")
    mw._pending_apply([kc], True); pump(timeout=0.3)    # 확정 — 아직 색인에 행이 없다(다음 훑기가 넣는다)
    d = tmp / "IMG_0004.jpg"
    Image.new("RGB", (900, 600), (60, 60, 60)).save(d, "JPEG")
    seed(d, "pending words only")                        # 보류 — 확정 안 함
    time.sleep(0.05)
    Image.new("RGB", (900, 600), (10, 200, 10)).save(b, "JPEG")   # 덮어쓰기 — b 의 확정 글은 낡았다
    idx_done.clear()
    mw._photo_index_start()
    pump(lambda: names("crushed") == ["IMG_0003.jpg"] and names("picnic") == [], timeout=15)   # 폴더 감시가 띄운 훑기와 겹칠 수 있다 — 결과로 기다린다
    chk(names("crushed") == ["IMG_0003.jpg"], "F 훑기가 확정 글을 넣는다", str(names("crushed")))
    chk(names("pending") == [], "F 보류 글은 넣지 않는다", str(names("pending")))
    chk(names("picnic") == [], "F 덮어써 낡은 글은 빠진다", str(names("picnic")))
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
