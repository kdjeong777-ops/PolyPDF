# -*- coding: utf-8 -*-
"""환경설정 '일반 › 해시태그' 의 해시태그 내용 — 형식 낱말·별칭·사진 종류, [적용] 하면 곧바로 다시 붙인다 (태그 SOT §5.8, 디자인 SOT §2.14, 261107-10).

실제 MainWindow·SettingsDialog 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 해시태그 쪽에 형식 낱말 13개(켬)·별칭 표·사진 종류 4개가 있고, 지금 규칙 파일 값을 보인다
B. 바꾸면 [적용] 이 켜지고, [적용] 하면 tag_rules.json 이 바뀌고 이미 붙은 자동 태그가 곧바로 바뀐다
C. settings.json 에는 들어가지 않는다(규칙은 tag_rules.json 한 곳), 사진 자동 태그를 끄면 사진 종류 칸이 잠긴다
"""
import os, sys, tempfile, shutil, time, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_rules_settings_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "해시태그 설정", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tagset_"))
try:
    from viewer.settings_store import settings_dir
    from viewer.auto_tag import FORMAT_VOCAB
    rp = Path(settings_dir()) / "tag_rules.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"alias": {"공문": "공문서"}, "format_off": ["브로셔"], "mine": 1}, ensure_ascii=False), encoding="utf-8")
    from viewer.app import MainWindow
    from viewer.widgets.settings_dialog import SettingsDialog
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.show(); pump(lambda: False, 0.3)
    store = mw.bookmark_tree._tags
    A, B = str(tmp / "a.pdf"), str(tmp / "b.pdf")
    store.set_auto(A, ["공문서"]); store.set_auto(B, ["기사", "아스팔트"])
    dlg = SettingsDialog(mw._prefs, mw, host=mw, page="tags")
    pn = getattr(dlg, "tag_rules_panel", None)
    chk(pn is not None, "A 해시태그 쪽에 해시태그 내용이 붙었다")
    if pn is not None:
        page_w = dlg._scrolls["tags"].widget()
        chk(page_w.isAncestorOf(pn), "A '일반 › 해시태그' 쪽 안에 있다")
        chk(list(pn.fmt_chk) == list(FORMAT_VOCAB) and not pn.fmt_chk["브로셔"].isChecked() and pn.fmt_chk["기사"].isChecked(),
            "A 형식 낱말 13개 — 지금 규칙(브로셔 끔)")
        chk(pn.fmt_name["공문"].text() == "공문서", "A 형식 붙일 이름 — 지금 규칙", pn.fmt_name["공문"].text())
        chk(set(pn.photo_chk) == {"date", "region", "device", "screenshot"} and all(c.isChecked() for c in pn.photo_chk.values()),
            "A 사진 종류 4개 켬")
        chk(not dlg.btn_apply.isEnabled(), "B 바꾸기 전 [적용] 꺼짐")
        pn.fmt_chk["기사"].setChecked(False)
        pn._add_row("SamsungSM-S918N", "GalaxyS23")
        pn.fmt_name["공문"].setText("")
        chk(dlg.btn_apply.isEnabled(), "B 바꾸면 [적용] 켜짐")
        ends = []
        dlg.apply()
        job = mw.__dict__.get("_tag_rules_job")
        chk(job is not None, "B [적용] 하면 다시 붙이기가 시작된다")
        if job is not None:
            job.ended.connect(lambda n: ends.append(n))
            pump(lambda: bool(ends) or not job._workers, 20)
            pump(lambda: False, 0.3)
        saved = json.loads(rp.read_text(encoding="utf-8"))
        chk(sorted(saved.get("format_off") or []) == sorted(["기사", "브로셔"]) and saved.get("alias") == {"SamsungSM-S918N": "GalaxyS23"} and saved.get("mine") == 1,
            "B tag_rules.json — 형식 끄기·별칭, 손으로 넣은 다른 키는 남는다", str(saved))
        chk(store.get_auto(A) == ["공문"] and store.get_auto(B) == ["아스팔트"], "B 이미 붙은 자동 태그가 곧바로 — 이름 되돌림·끈 형식 뺌",
            f"{store.get_auto(A)} {store.get_auto(B)}")
        chk("tag_rules" not in mw._prefs, "C settings.json(설정)에는 넣지 않는다", str([k for k in mw._prefs if "tag" in k]))
        chk(not dlg.btn_apply.isEnabled(), "C [적용] 뒤 다시 꺼짐")
        dlg.chk_photo_tag.setChecked(False)
        chk(not any(c.isEnabled() for c in pn.photo_chk.values()), "C 사진 자동 태그를 끄면 사진 종류 칸이 잠긴다")
    dlg.reject()
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
os._exit(1 if fails else 0)
