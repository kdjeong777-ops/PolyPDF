# -*- coding: utf-8 -*-
"""보기설정 — 사진 모드 줄 표기 스타일 (사진 보기 SOT 4.38, 261104-13 사용자 지시).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 구문 잇기 — 값이 없는 조각은 옆 구분자와 함께 빠진다
B. 책갈피창·썸네일창 우클릭 메뉴 끝에 '보기설정...'(사진 모드)
C. 대화상자에서 조각으로 구문을 만들고 [적용] — 책갈피창·썸네일 칸이 그대로 보인다(태그 꼬리는 그대로)
D. 이름 붙인 스타일 — 저장·고르기·지우기, 기본 스타일로 돌아가기
E. 설정은 preferences 의 picture 묶음 안(최상위 새 키 없음)
F. 사진 1,500장 — 스타일을 바꿔 다시 그리는 데 0.5초 안(값은 기억한 것 — 다시 읽지 않는다)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_lstyle_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "보기설정", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_lstyle_"))
try:
    from viewer import photo_label as PL
    # A
    v = PL.values("x/가 해변.jpg", "2025-06-10", 640, 480, 2 * 1024 * 1024)
    chk(PL.render("{date} {name}", v) == "2025-06-10 가 해변", "A 기본 구문")
    chk(PL.render("{name}.{ext} · {size} · {bytes}", v) == "가 해변.JPG · 640×480 · 2.0MB", "A 조각 다섯", PL.render("{name}.{ext} · {size} · {bytes}", v))
    v2 = PL.values("x/나.png", "", 0, 0, 0)
    chk(PL.render("{date} · {name} · {size} · {bytes}", v2) == "나", "A 값이 없는 조각은 구분자와 함께 빠진다", repr(PL.render("{date} · {name} · {size} · {bytes}", v2)))

    from PIL import Image
    a = tmp / "가 해변.jpg"
    im = Image.new("RGB", (640, 480), (40, 120, 200))
    ex = im.getexif()
    ex.get_ifd(0x8769)[0x9003] = "2025:06:10 09:30:00"
    im.save(a, "JPEG", exif=ex.tobytes())
    b = tmp / "나 캡처.png"
    Image.new("RGB", (300, 200), (200, 200, 200)).save(b, "PNG")

    from viewer.app import MainWindow
    from viewer.widgets import photo_label_dialog as PLD
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    labels = lambda: {Path(str(it.data(0, bt.DATA_FILE))).name: it.text(0) for it in bt._iter_file_nodes()}
    pump(lambda: labels().get("가 해변.jpg", "").startswith("2025-06-10"), timeout=10)
    mw._on_bookmark_activated(str(a), 0)
    strip = mw._photo_strip
    pump(lambda: str(a) in strip._done and str(b) in strip._done, timeout=10)

    # B — 메뉴 끝
    seen = {}
    real_exec = QMenu.exec

    def fake_exec(self, *a_, **k_):
        acts = [x.text() for x in self.actions() if not x.isSeparator()]
        seen.setdefault("menus", []).append(acts)
        return None
    QMenu.exec = fake_exec
    node = next(it for it in bt._iter_file_nodes() if Path(str(it.data(0, bt.DATA_FILE))).name == "가 해변.jpg")
    bt._on_tree_context_menu(bt.tree.visualItemRect(node).center())
    mw._photo_strip_menu(str(a), strip.mapToGlobal(strip.rect().center()))
    QMenu.exec = real_exec
    ms = seen.get("menus", [])
    chk(len(ms) >= 2 and ms[0][-1] == "보기설정..." and ms[-1][-1] == "보기설정...", "B 두 창 메뉴 끝에 '보기설정...'",
        str([m[-3:] for m in ms]))

    # C — 대화상자로 구문 만들고 적용(책갈피창)
    bt._tags.set(str(a), ["가족"])
    bt._apply_tag_label(node, str(a))
    pic = mw._photo_prefs()
    applied = []
    sample = mw._photo_label_values(str(a))
    dlg = PLD.PhotoLabelDialog(mw, pic, "tree", sample, on_apply=lambda: (applied.append(1), mw._photo_labels_apply(None)))
    dlg.eds[0].setText("")
    for key in ("name",):
        dlg.findChild(type(dlg.b_new), "tok_" + key).click()
    dlg.eds[0].insert(".")
    dlg.findChild(type(dlg.b_new), "tok_ext").click()
    dlg.cb_sep.setCurrentIndex(dlg.cb_sep.findData(" · "))
    dlg.findChild(type(dlg.b_new), "tok_sep").click()
    dlg.findChild(type(dlg.b_new), "tok_size").click()
    chk(dlg.eds[0].text() == "{name}.{ext} · {size}", "C 조각 단추로 구문", dlg.eds[0].text())
    chk(dlg.lbl_prev.text() == "가 해변.JPG · 640×480", "C 미리보기", dlg.lbl_prev.text())
    dlg.findChild(type(dlg.b_new), "tok_back").click()
    chk(dlg.eds[0].text() == "{name}.{ext} · ", "C 마지막 조각 지우기", dlg.eds[0].text())
    dlg.findChild(type(dlg.b_new), "tok_size").click()
    dlg.apply()
    chk(applied and labels()["가 해변.jpg"].startswith("가 해변.JPG · 640×480") and "#가족" in labels()["가 해변.jpg"],
        "C 적용 — 책갈피창이 그대로(태그 꼬리 그대로)", labels()["가 해변.jpg"])
    chk(labels()["나 캡처.png"].startswith("나 캡처.PNG · 300×200"), "C 다른 줄도", labels()["나 캡처.png"])

    # 썸네일창
    dlgs = PLD.PhotoLabelDialog(mw, pic, "strip", sample, on_apply=lambda: strip.set_label_style(mw._photo_strip_style()))
    dlgs.eds[0].setText("{date}")
    dlgs.eds[1].setText("{size} · {bytes}")
    dlgs.apply()
    t = strip._items[str(a)].text().split("\n")
    chk(t[0] == "2025-06-10" and t[1].startswith("640×480 · ") and t[1].endswith("MB"), "C 썸네일 칸 윗줄·아랫줄", str(t))

    # D — 이름 붙인 스타일
    import viewer.widgets.photo_label_dialog as _m
    _m.QInputDialog.getText = staticmethod(lambda *a_, **k_: ("내 스타일", True))
    dlg._new()
    chk("내 스타일" in PL.styles(pic, "tree") and PL.current_name(pic, "tree") == "내 스타일", "D 새 스타일 저장·고름")
    dlg.cb.setCurrentIndex(dlg.cb.findData("이름만"))
    dlg.apply()
    chk(labels()["가 해변.jpg"].startswith("가 해변") and not labels()["가 해변.jpg"].startswith("2025"), "D 기본 스타일 '이름만' 고르기", labels()["가 해변.jpg"])
    dlg.cb.setCurrentIndex(dlg.cb.findData("내 스타일"))
    _m.QMessageBox.question = staticmethod(lambda *a_, **k_: _m.QMessageBox.StandardButton.Yes)
    dlg._delete()
    chk("내 스타일" not in PL.styles(pic, "tree"), "D 사용자 스타일 지우기")
    dlg.cb.setCurrentIndex(dlg.cb.findData("기본"))
    dlg._delete()                                    # 기본값으로
    dlg.apply()
    chk(PL.current(pic, "tree") == PL.BUILTIN_TREE["기본"] and labels()["가 해변.jpg"].startswith("2025-06-10 가 해변"),
        "D '기본값으로' — 기본 스타일 그대로", labels()["가 해변.jpg"])

    # E — 설정 자리
    payload = mw._build_settings_payload()
    chk("label_styles" in (payload["preferences"].get("picture") or {}) and "label_styles" not in payload
        and "label_styles" not in payload["preferences"], "E 설정은 picture 묶음 안", str(list(payload["preferences"].get("picture", {}).keys())))

    # F — 1,500장 다시 그리기
    big = tmp / "많이"; big.mkdir()
    raw = a.read_bytes()
    for i in range(1500):
        (big / ("p%04d.jpg" % i)).write_bytes(raw)
    mw.open_folder(big)
    pump(lambda: sum(1 for it in bt._iter_file_nodes() if it.text(0).startswith("2025-06-10")) == 1500, timeout=60)
    PL.select(pic, "tree", "상세")
    t0 = time.perf_counter()
    mw._photo_labels_apply(None)
    dt = time.perf_counter() - t0
    print("   F 1,500장 다시 그리기 %.3f초" % dt)
    chk(dt < 0.5 and all("640×480" in it.text(0) for it in bt._iter_file_nodes()), "F 1,500장 스타일 바꿔 다시 그리기 0.5초 안", "%.3f" % dt)
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
