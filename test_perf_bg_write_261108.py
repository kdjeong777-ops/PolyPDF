# -*- coding: utf-8 -*-
"""설정·사이드카·태그·고친 글을 메인 스레드에서 쓰지 않는다 — 배경 쓰기 줄 하나(`bg_write`) (261108-15, 응답성 SOT §6).

백신 실시간 검사는 새로 만든·바꿔 끼운 파일을 붙든다(메인 `os.replace` 21.4초 정지 이력). 종전에는 저장소 다섯이 메인에서
tmp 쓰기 + `os.replace`(설정은 fsync 까지)를 했고, 사진 OCR 확정은 사진마다 태그 JSON 전체를 두 번씩 다시 썼다.

M. 메인 스레드에서 `PageMetaStore.save`·`save_photo_rotation`·`HyperlinkStore.save`·`TagStore`(태그 바꾸기)·`TextFixStore.save`·
   `settings_store.save` 를 불러도 메인의 파일 쓰기(`open` 쓰기 모드·`os.replace`·`os.fsync`) 0번(수정 전 코드는 실패)
L. `flush()` 뒤 디스크 = 마지막 값 · 잇단 저장 20번은 디스크 쓰기 몇 번으로 모인다
R. 쓰기가 끝나기 전에 같은 파일을 새 저장소로 읽어도 새 값(같은 프로세스 안 순서)
X. 프로세스 끝: 정상 종료(atexit) · `flush()` 뒤 `os._exit`(main.py 길) · `flush` 없이 `DELAY_S` 넘게 지난 뒤 `os._exit`(크래시 흉내) — 모두 마지막 값이 디스크에
   · main.py 는 `os._exit` 앞에서 `bg_write.flush()` 를 부른다
F. 사진 OCR 확정(`_photo_ocr_committed`) 사진 10장 — 태그 파일 저장 1번(수정 전 코드는 사진마다 → 실패)
E. 쓰기가 실패하면 `on_error(경로, 까닭)` 이 불린다
"""
import builtins, json, os, subprocess, sys, tempfile, threading, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"          # 검사 작성 SOT §14.7
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)             # 검사 작성 SOT §14.7.2 의 3

tmp = tempfile.mkdtemp(prefix="polypdf_bgw_")
from viewer import settings_store
settings_store._DIR_OVERRIDE = os.path.join(tmp, "cfg")     # 실제 설정 폴더를 쓰지 않는다
os.makedirs(settings_store._DIR_OVERRIDE, exist_ok=True)

try:
    from viewer import bg_write
except ImportError:
    bg_write = None
from viewer.page_meta import PageMetaStore
from viewer.hyperlinks import HyperlinkStore
from viewer.tag_store import TagStore
from viewer.text_fix_store import TextFixStore

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def flush():
    if bg_write is not None:
        bg_write.flush()


# ── 메인 스레드 파일 쓰기 감시 ─────────────────────────────────────
main_writes = []
_open, _replace, _fsync = builtins.open, os.replace, os.fsync


def _is_main():
    return threading.current_thread() is threading.main_thread()


def _spy_open(file, mode="r", *a, **k):
    if _is_main() and any(c in str(mode) for c in "wax+"):
        main_writes.append(("open", str(file)))
    return _open(file, mode, *a, **k)


def _spy_replace(src, dst, *a, **k):
    if _is_main():
        main_writes.append(("replace", str(dst)))
    return _replace(src, dst, *a, **k)


def _spy_fsync(fd):
    if _is_main():
        main_writes.append(("fsync", fd))
    return _fsync(fd)


folder = os.path.join(tmp, "docs")
os.makedirs(folder)
pdf = os.path.join(folder, "a.pdf")
with _open(pdf, "wb") as fh:
    fh.write(b"%PDF-1.4\n%%EOF\n")
pm_path = os.path.join(folder, "page_meta.json")
hl_path = os.path.join(folder, "hyperlinks.json")
tag_path = os.path.join(tmp, "cfg", "file_tags.json")
tf_path = os.path.join(tmp, "cfg", "text_fix.json")
set_path = str(settings_store.settings_path())

# M
pm, hl = PageMetaStore(folder), HyperlinkStore(folder)
tags, tf = TagStore(tag_path), TextFixStore(tf_path)
builtins.open, os.replace, os.fsync = _spy_open, _spy_replace, _spy_fsync
try:
    pm.rotate_pages(pdf, [0], 90)
    pm.save()
    pm.set_photo_rotation(pdf, 90)
    pm.save_photo_rotation()
    hl.add_url_link(pdf, 0, "v", "https://www.youtube.com/watch?v=1")
    hl.save()
    tags.set(pdf, ["보고서"])
    tf.set_fix(pdf, 0, 1, "고친 글")
    tf.save()
    settings_store.save({"preferences": {"bgw_probe": 1}})
finally:
    builtins.open, os.replace, os.fsync = _open, _replace, _fsync
chk(not main_writes, "M 저장소 다섯의 저장이 메인에서 파일을 쓰지 않는다", "%d번 %s" % (len(main_writes), main_writes[:6]))

# R — 디스크에 쓰기 전에 새 저장소로 읽어도 새 값
chk(PageMetaStore(folder).get_rotation(pdf, 0) == 90, "R 쓰기 전에 새 PageMetaStore 가 새 회전을 읽는다")
chk(len(HyperlinkStore(folder).links_for(pdf, 0)) == 1, "R 쓰기 전에 새 HyperlinkStore 가 새 링크를 읽는다")
chk((settings_store.load().get("preferences") or {}).get("bgw_probe") == 1, "R 쓰기 전에 settings_store.load 가 새 값")
chk(settings_store.peek_pref("bgw_probe") == 1, "R 쓰기 전에 peek_pref 가 새 값")

# L
flush()
d = json.loads(_open(pm_path, encoding="utf-8").read())
chk(d["files"].get("a.pdf", {}).get("rotation", {}).get("0") == 90 and d.get("photo_rot"), "L flush 뒤 page_meta.json = 마지막 값", str(d)[:200])
chk(json.loads(_open(set_path, encoding="utf-8").read())["preferences"]["bgw_probe"] == 1, "L flush 뒤 settings.json = 마지막 값")
w0 = bg_write.stats["writes"] if bg_write else 0
for i in range(20):
    settings_store.save({"preferences": {"bgw_probe": i}})
flush()
w1 = bg_write.stats["writes"] if bg_write else 99
chk(json.loads(_open(set_path, encoding="utf-8").read())["preferences"]["bgw_probe"] == 19, "L 잇단 저장 20번 뒤 디스크 = 마지막(19)")
chk(w1 - w0 <= 3, "L 잇단 저장 20번이 디스크 쓰기 몇 번으로 모인다", "쓰기 %d번" % (w1 - w0))

# X — 프로세스 끝
child = r'''
import os, sys, time
sys.path.insert(0, %r)
from viewer import settings_store, bg_write
settings_store._DIR_OVERRIDE = %r
settings_store.save({"preferences": {"exit_mode": sys.argv[1]}})
m = sys.argv[1]
if m == "flush_exit":
    bg_write.flush(); os._exit(0)
elif m == "late_kill":
    time.sleep(bg_write.DELAY_S + 0.7); os._exit(0)
''' % (HERE, None)
for mode in ("normal", "flush_exit", "late_kill"):
    cdir = os.path.join(tmp, "child_" + mode)
    os.makedirs(cdir)
    code = child.replace("settings_store._DIR_OVERRIDE = None", "settings_store._DIR_OVERRIDE = %r" % cdir)
    subprocess.run([sys.executable, "-I", "-c", code, mode], cwd=HERE, timeout=60)
    f = os.path.join(cdir, "settings.json")
    got = json.loads(_open(f, encoding="utf-8").read())["preferences"].get("exit_mode") if os.path.exists(f) else None
    chk(got == mode, "X 프로세스 끝(%s) — 마지막 값이 디스크에" % mode, str(got))
src = _open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
tail = src[src.rfind("code = app.exec()"):]
chk("bg_write.flush()" in tail and tail.find("bg_write.flush()") < tail.find("os._exit(code)"),
    "X main.py 는 os._exit 앞에서 bg_write.flush()")

# F — 사진 OCR 확정은 태그 파일을 한 번만 저장
from viewer import photo_controller
saves = []
_orig_save = TagStore._save


def _count_save(self):
    if self._bulk_depth == 0:
        saves.append(1)
    return _orig_save(self)


class _BT:
    pass


class _Fake:
    pass


fake = _Fake()
fake.bookmark_tree = _BT()
fake.bookmark_tree._tags = TagStore(os.path.join(tmp, "cfg", "tags_f.json"))
mix = photo_controller.PhotoMixin
for name in ("_photo_ocr_committed", "_photo_ocr_commit_rows"):
    if hasattr(mix, name):
        setattr(fake, name, getattr(mix, name).__get__(fake))
found = [(os.path.join(folder, "p%02d.jpg" % i), "글 %d" % i, "영수증", ["낱말%d" % i]) for i in range(10)]
TagStore._save = _count_save
try:
    fake._photo_ocr_committed(found)
finally:
    TagStore._save = _orig_save
chk(len(saves) <= 1, "F 사진 10장 OCR 확정 — 태그 파일 저장 1번", "%d번" % len(saves))

# E — 쓰기 실패 알림
if bg_write is not None:
    errs = []
    keep = bg_write.on_error
    bg_write.on_error = lambda p, why: errs.append((p, why))
    blocker = os.path.join(tmp, "blocker")
    with _open(blocker, "w") as fh:
        fh.write("x")
    bg_write.submit(os.path.join(blocker, "sub", "x.json"), "{}", delay=0)    # 부모가 파일이라 폴더를 못 만든다
    bg_write.flush()
    bg_write.on_error = keep
    chk(errs and errs[0][0].endswith("x.json"), "E 쓰기 실패 → on_error(경로, 까닭)", str(errs))
else:
    chk(False, "E 쓰기 실패 → on_error(경로, 까닭)", "bg_write 없음")

print()
print("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
