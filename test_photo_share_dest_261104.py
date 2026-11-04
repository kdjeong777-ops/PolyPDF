# -*- coding: utf-8 -*-
"""공유용 사본 저장 자리 고르기 (사진 보기 SOT 4.22, 261104-18 사용자 지시·결정).

사용자 원문: "'공유용 사본' 저장시 사진을 1장 저장하면, 저장 위치를 선택하게 하고, 2장이상 사본으로 저장시 선택한 위치 폴더를 생성하여 저장할 수 있도록 수정."
사용자 결정: 새 폴더 이름은 'YYMMDD-사진사본' 을 미리 채워 고칠 수 있게, 겹치면 'YYMMDD-사진사본(2)', 창은 마지막으로 고른 위치에서.
실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 창은 바꿔 끼워 무엇을 묻는지 본다.
A. 1장 — 저장 창, 처음 이름 '<이름>_공유.jpg', 처음 위치는 사진 폴더 → 고른 자리·이름에 만든다(원본 그대로)
B. 2장 이상 — 위치 창 → 새 폴더 이름 창(처음 'YYMMDD-사진사본') → 그 안에 모두. 같은 이름이 있으면 '(2)'
C. 다음 창은 마지막으로 고른 위치에서 시작
D. 취소하면 아무것도 만들지 않는다 · 원본 자리를 고르면 만들지 않는다(알림)
E. 세 메뉴(책갈피창·썸네일 줄·본문)가 같은 길 — 메뉴로 불러도 창이 뜬다
F. '폴더 이름 자동 설정' 체크(261104-18 보완 사용자 지시) — 다음부터 이름 창 없이 'YYMMDD-사진사본(n)' 으로, Shift 를 누른 채면 다시 묻고 체크를 풀 수 있다
G. 실제 이름 창에 그 체크박스가 있고, 체크해 확인하면 켜진다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QFileDialog
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_sdest_%d" % os.getpid())
from PyQt6.QtWidgets import QDialog as _QD
_real_exec = _QD.exec                                 # G 는 실제 창을 띄워 안을 본다
import modal_guard
modal_guard.install(label=lambda: "공유용 사본 자리", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_sdest_"))
try:
    from PIL import Image
    src_dir = tmp / "사진"
    src_dir.mkdir()
    a, b = src_dir / "a.jpg", src_dir / "b.jpg"
    Image.new("RGB", (300, 200), (200, 50, 50)).save(a, "JPEG")
    Image.new("RGB", (300, 200), (50, 200, 50)).save(b, "JPEG")
    raw = {p: p.read_bytes() for p in (a, b)}
    out1, out2 = tmp / "보낼 곳", tmp / "다른 곳"
    out1.mkdir(); out2.mkdir()

    asked = {"save": [], "dir": [], "text": []}
    plan = {"save": None, "dir": None, "text": None, "auto": False}

    def fake_save(_w, title, path, *a_, **k_):
        asked["save"].append(path)
        return (plan["save"](path) if callable(plan["save"]) else (plan["save"] or ""), "")

    def fake_dir(_w, title, start, *a_, **k_):
        asked["dir"].append(start)
        return plan["dir"] or ""

    def fake_text(_self, text):
        asked["text"].append(text)
        return (plan["text"] if plan["text"] is not None else text, plan["text"] != "", plan["auto"])
    QFileDialog.getSaveFileName = staticmethod(fake_save)
    QFileDialog.getExistingDirectory = staticmethod(fake_dir)

    from viewer.app import MainWindow
    real_ask = MainWindow._photo_share_ask_name
    MainWindow._photo_share_ask_name = fake_text
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(src_dir)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 2)

    def share(paths, mode="gps"):
        mw._photo_share([str(p) for p in paths], mode)
        pump(lambda: not mw.__dict__.get("_photo_share_busy"), timeout=10); pump(timeout=0.3)

    # A — 1장
    plan["save"] = lambda path: str(out1 / "보낼 사진.jpg")
    share([a])
    chk(asked["save"] and Path(asked["save"][-1]).name == "a_공유.jpg" and Path(asked["save"][-1]).parent == src_dir,
        "A 1장 — 저장 창, 처음 이름 '<이름>_공유.jpg', 처음 위치는 사진 폴더", str(asked["save"][-1:]))
    chk((out1 / "보낼 사진.jpg").exists() and not (src_dir / "a_공유.jpg").exists(), "A 고른 자리·이름에 만든다", str(os.listdir(out1)))
    chk(not asked["dir"] and not asked["text"], "A 1장은 폴더를 만들지 않는다")

    # B — 2장
    import time as _t
    stamp = _t.strftime("%y%m%d")
    plan["dir"] = str(out2)
    share([a, b])
    chk(asked["dir"] and asked["text"] and asked["text"][-1] == stamp + "-사진사본", "B 2장 — 위치 창 → 이름 창(처음 'YYMMDD-사진사본')",
        str(asked["text"][-1:]))
    d1 = out2 / (stamp + "-사진사본")
    chk(d1.is_dir() and sorted(os.listdir(d1)) == ["a_공유.jpg", "b_공유.jpg"], "B 새 폴더 안에 모두", str(os.listdir(out2)))
    share([a, b])
    chk(asked["text"][-1] == stamp + "-사진사본(2)" and (out2 / (stamp + "-사진사본(2)")).is_dir(),
        "B 같은 이름이 있으면 '(2)'", str(asked["text"][-1:]) + str(os.listdir(out2)))
    plan["text"] = "여행 보낼 것"
    share([a, b])
    chk(sorted(os.listdir(out2 / "여행 보낼 것")) == ["a_공유.jpg", "b_공유.jpg"], "B 이름을 고쳐도 된다")
    plan["text"] = None

    # C — 마지막 위치
    plan["save"] = lambda path: path
    share([b])
    chk(Path(asked["save"][-1]).parent == out2, "C 다음 창은 마지막으로 고른 위치에서", str(asked["save"][-1:]))
    share([a, b])
    chk(asked["dir"][-1] == str(out2), "C 위치 창도 마지막 위치에서", str(asked["dir"][-1:]))

    # D — 취소·원본 자리
    before = {p: sorted(os.listdir(p)) for p in (src_dir, out1, out2)}
    plan["save"] = ""
    share([a])
    plan["dir"] = ""
    share([a, b])
    plan["dir"] = str(out1)
    plan["text"] = ""
    share([a, b])
    plan["text"] = None
    plan["save"] = lambda path: str(a)
    share([a])
    after = {p: sorted(os.listdir(p)) for p in (src_dir, out1, out2)}
    chk(before == after, "D 취소·원본 자리 — 아무것도 만들지 않는다", str(after))
    chk(all(p.read_bytes() == raw[p] for p in (a, b)), "D 원본은 그대로")

    # E — 메뉴 길
    n0 = len(asked["save"])
    plan["save"] = ""
    for kind in ("share_gps", "share_all"):
        mw._photo_action(kind, [str(a)]); pump(timeout=0.3)
    chk(len(asked["save"]) == n0 + 2, "E 메뉴(책갈피창·썸네일 줄·본문이 같은 _photo_action)로도 저장 창")

    # F — 폴더 이름 자동 설정
    out3 = tmp / "자동"
    out3.mkdir()
    plan["dir"] = str(out3)
    plan["auto"] = True
    share([a, b])                                   # 이번엔 묻고, 체크했다
    nt = len(asked["text"])
    plan["auto"] = False
    share([a, b])
    share([a, b])
    names = sorted(os.listdir(out3))
    chk(len(asked["text"]) == nt and names == [stamp + "-사진사본", stamp + "-사진사본(2)", stamp + "-사진사본(3)"]
        and all(sorted(os.listdir(out3 / x)) == ["a_공유.jpg", "b_공유.jpg"] for x in names),
        "F 체크하면 다음부터 이름 창 없이 'YYMMDD-사진사본(n)' 으로", str(names) + " asked=%d/%d" % (len(asked["text"]), nt))
    from PyQt6.QtCore import Qt
    QApplication.keyboardModifiers = staticmethod(lambda: Qt.KeyboardModifier.ShiftModifier)
    share([a, b])                                   # Shift — 다시 묻는다, 체크 풀고 확인
    QApplication.keyboardModifiers = staticmethod(lambda: Qt.KeyboardModifier.NoModifier)
    chk(len(asked["text"]) == nt + 1, "F Shift 를 누른 채면 다시 묻는다")
    share([a, b])
    chk(len(asked["text"]) == nt + 2, "F 체크를 풀면 다시 늘 묻는다")

    # G — 실제 이름 창
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QDialog, QCheckBox, QLineEdit
    seen = {}

    def answer():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible() and w.findChild(QCheckBox):
                seen["name"] = w.findChild(QLineEdit).text()
                w.findChild(QCheckBox).setChecked(True)
                w.accept()
                return
        QTimer.singleShot(50, answer)
    QTimer.singleShot(50, answer)
    QDialog.exec = lambda self, *a_: _real_exec(self, *a_)   # 내장 함수는 묶이지 않아 감싼다
    got = real_ask(mw, "261105-사진사본")
    chk(seen.get("name") == "261105-사진사본" and got == ("261105-사진사본", True, True),
        "G 실제 이름 창 — 처음 이름·'폴더 이름 자동 설정' 체크박스", str(got) + str(seen))
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
