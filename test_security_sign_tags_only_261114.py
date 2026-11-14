# -*- coding: utf-8 -*-
"""서명 사전 점검 — PDF 에 아직 안 들어간 것이 태그뿐이면 묻지 않는다 (보안 SOT §3.5, 태그 SOT, 261114-22).

결함: 자동 태그가 기본 켬(261113-10)이라 연 PDF 마다 태그가 붙고, 서명 사전 점검(`_sign_preflight`)이 그것을
'PDF 에 아직 안 들어간 태그' 로 보아 거의 매번 '저장하고 서명' 확인 창을 띄웠다. 사용자 결정 '태그만이면 묻지 않기'.
실제 MainWindow·`_sign_preflight`(서명 단추·[서명 확정]·빈 칸 만들기가 모두 지나는 길)로, 자동 태그는 켠 채(오프스크린,
실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 처음 보는 PDF 에 자동 태그만 → 묻지 않고 통과(수정 전: 확인 창)
B. '저장' 으로 태그가 /Keywords 에 들어간 뒤 태그를 하나 더 → 묻지 않고 통과(지문을 PDF 의 태그로 다시 셈)
C. 꾸밈이 섞이면 → 종전대로 묻는다(가짜 exec 가 취소 → 멈춤)
D. 태그는 앱 기록에 그대로(서명 결과 파일로 옮기지 않는다)
"""
import os, sys, time, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_sign_tags_only_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "서명 사전 점검", echo=False)
import test_fixtures as TF
fails = []
DECO = {"text_box": True, "rect": [0.1, 0.1, 0.4, 0.16], "text": "DECO", "size_pt": 12}


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def spin(sec):
    t = time.monotonic()
    while time.monotonic() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def asked():
    return [s for s in guard.seen if "저장하지 않은 편집" in s[2]]


root = Path(tempfile.mkdtemp(prefix="polypdf_signtags_"))
try:
    folder = root / "folder"
    folder.mkdir()
    doc_path = folder / "계약서.pdf"
    shutil.copyfile(TF.text_pdf(), str(doc_path))
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 900); mw.show(); spin(0.3)
    chk(mw._prefs.get("auto_tag_enabled", True) is True, "준비 — 자동 태그는 켠 채")
    mw.open_folder(str(folder)); spin(0.8)
    mw.open_pdfs([str(doc_path)]); spin(0.5)
    TF.wait_main_open(mw)
    # 배경 태그 계산(폴더를 열면 3초 뒤 시작)이 끝나기를 기다린다 — 도중에 자동 태그를 바꾸면 아래 판정이 흔들린다
    t0 = time.monotonic()
    while mw.__dict__.get("_autotag_worker") is None and time.monotonic() - t0 < 8:
        spin(0.1)
    t0 = time.monotonic()
    while (mw.__dict__.get("_autotag_worker") is not None
           or (mw.__dict__.get("_light") or {}).get("worker") is not None) and time.monotonic() - t0 < 60:
        spin(0.1)
    spin(0.3)
    store = mw.bookmark_tree._tags
    p = str(doc_path)

    # A
    store.set_auto(p, ["보고서", "한글"])
    guard.seen.clear()
    ok = mw._sign_preflight(p)
    chk(ok and not asked(), "A 태그뿐이면 묻지 않고 서명으로 간다", "%s %s" % (ok, guard.report()))
    chk(mw._mirror_need_kind(p) == "tags", "A 판정 = 태그뿐", mw._mirror_need_kind(p))

    # B — '저장' 으로 태그를 /Keywords 에 넣은 뒤 하나 더
    chk(mw._mirror_to_pdf(p), "B '저장' 이 태그 사본을 PDF 에 넣는다")
    spin(1.0)
    chk(mw._mirror_need_kind(p) != "other", "B 넣은 뒤에는 꾸밈 등 할 것이 없다(저장 뒤 자동 태그가 다시 붙으면 태그뿐)", mw._mirror_need_kind(p))
    store.set(p, ["가족"])
    guard.seen.clear()
    ok = mw._sign_preflight(p)
    chk(ok and not asked(), "B 넣은 뒤 태그를 더해도 묻지 않는다(PDF 의 태그로 지문을 다시 셈)", "%s %s" % (ok, guard.report()))

    # C — 꾸밈이 섞이면 종전대로 묻는다
    bt = mw.bookmark_tree
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)
    st = mw._ensure_page_meta_store()
    mv = mw.main_view
    mv.go_to_page(0); spin(0.2)
    mv._page_strokes = [dict(DECO)]
    mv._save_page_strokes(); st.save(); spin(0.1)
    chk(mw._mirror_need_kind(p) == "other", "C 판정 = 다른 것이 섞임", mw._mirror_need_kind(p))
    guard.seen.clear()
    ok = mw._sign_preflight(p)
    chk(not ok and len(asked()) == 1, "C 꾸밈이 섞이면 '저장하고 서명' 을 묻는다(취소 → 멈춤)", "%s %s" % (ok, guard.report()))

    # D
    chk("가족" in store.get(p) and "보고서" in store.get(p), "D 태그는 원본의 앱 기록에 그대로", str(store.get(p)))
    mw._confirm_close_edit = lambda: True
    mw.close(); spin(0.2)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
