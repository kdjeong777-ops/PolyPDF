# -*- coding: utf-8 -*-
"""260906-9: 환경설정 값이 조용히 사라지지 않는다 — 허용목록 함정(마스터 SOT §14.2).

`MainWindow._apply_prefs` 는 **허용목록**이다. 환경설정 창이 내보내는 키가 거기 없으면
사용자가 고른 값이 **오류 없이 사라진다**. 이 함정은 SOT 에 적혀 있는데도 두 번 재발했다
(260906-3 `startup_mode`, 260906-9 `open_edit_mode` — 후자는 260822 도입 후 줄곧 유실).

사람이 기억해서 막을 일이 아니므로 검사로 고정한다.

검사 대상:
  ① 환경설정 창이 내보내는 모든 키가 `_apply_prefs` 를 통과한다
  ② 통과한 값이 실제로 저장 페이로드까지 간다(왕복)
"""
import os, sys, io, json, re
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
# 261025-7: 사용자 실제 설정 폴더(색인·settings.json)를 쓰지 않는다 — 마스터 §14.7.2 의 3
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_prefs_allowlist_%d" % os.getpid())

from viewer import settings_store
from viewer.app import MainWindow

SPATH = settings_store.settings_path("settings.json")
ORIG = io.open(SPATH, encoding="utf-8").read() if SPATH.exists() else None

# 환경설정 창이 내보내는 키 목록 — `result_prefs` 본문에서 뽑는다.
src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "viewer", "widgets", "settings_dialog.py"),
              encoding="utf-8").read()
seg = src[src.index("def result_prefs"):]
seg = seg[:seg.index("\n    def ", 10)] if "\n    def " in seg[10:] else seg
KEYS = sorted(set(re.findall(r'"([a-z0-9_]+)"\s*:', seg))
              | set(re.findall(r'out\["([a-z0-9_]+)"\]', seg)))

try:
    mw = MainWindow()
    mw._skip_save_on_close = True

    # ── ① 허용목록 통과 ──────────────────────────────────────────────────
    #   현재 값과 **다른 값**을 넣어 통과 여부를 본다(같으면 유실을 못 잡는다).
    probe = {}
    for k in KEYS:
        cur = mw._prefs.get(k)
        if isinstance(cur, list):
            probe[k] = ["_probe1", "_probe2"]     # 목록형은 목록으로(형 변환 주의)
        elif isinstance(cur, bool) or cur is None:
            probe[k] = not bool(cur)
        elif isinstance(cur, (int, float)):
            probe[k] = type(cur)(cur) + 1
        else:
            probe[k] = str(cur) + "_x"
    before = dict(mw._prefs)
    mw._apply_prefs({**before, **probe})
    lost = [k for k in KEYS if mw._prefs.get(k) != probe[k]]
    chk(not lost, "① 환경설정 창이 내보내는 키가 모두 _apply_prefs 를 통과한다",
        f"{len(KEYS)}개 중 유실 {len(lost)}: {lost}")

    # ── ② 저장 페이로드까지 간다 ─────────────────────────────────────────
    payload = mw._build_settings_payload()
    saved = payload.get("preferences") or {}
    gone = [k for k in KEYS if k not in saved]
    chk(not gone, "② 통과한 값이 settings.json 페이로드까지 간다", f"누락 {gone}")

    # ── ③ 알려진 재발 키는 이름으로도 못 박는다 ─────────────────────────
    for k in ("startup_mode", "startup_path", "open_edit_mode",
              "start_view_single", "auto_tag_enabled"):
        chk(k in saved, f"③ '{k}' 가 저장된다(과거 유실 이력)", "")

    # ── ④ 환경설정 창이 **모르는** 키도 남는다(261017-15, 점검) ─────────────
    #   기능이 스스로 `self._prefs["키"] = …` 로 넣는 값(가상 프린터·크롭 스타일 …)은 환경설정 창 [확인]·다시 시작의
    #   `_apply_prefs` 를 지나도 남아야 한다. 종전 검사는 ①(창이 내보내는 키)만 봐 이것을 못 잡았다.
    root = os.path.dirname(os.path.abspath(__file__))
    own = set()
    for dp, _dn, fns in os.walk(os.path.join(root, "viewer")):
        for fn in fns:
            if fn.endswith(".py"):
                t = io.open(os.path.join(dp, fn), encoding="utf-8").read()
                own |= set(re.findall(r'self\._prefs\["([a-z0-9_]+)"\]\s*=(?!=)', t))
    own.add("vprinter")                                 # `self._prefs[PREF_KEY] = …`(vprinter_controller)
    own -= set(KEYS)
    probe4 = {}
    for k in sorted(own):
        cur = mw._prefs.get(k)                          # 값 모양은 지금 값을 따른다(①과 같게 — 형 변환하는 키가 있다)
        if cur is None or isinstance(cur, dict):
            probe4[k] = {"_probe": k}
        elif isinstance(cur, list):
            probe4[k] = ["_probe"]
        elif isinstance(cur, bool):
            probe4[k] = not cur
        elif isinstance(cur, (int, float)):
            probe4[k] = type(cur)(cur) + 1
        else:
            probe4[k] = str(cur) + "_x"
        mw._prefs[k] = probe4[k]
    mw._apply_prefs({})                                 # 창이 이 키들을 모르는 경우
    lost4 = sorted(k for k in own if mw._prefs.get(k) != probe4[k])
    chk(not lost4, "④ 기능이 넣은 설정 키가 _apply_prefs 를 지나도 남는다", f"{len(own)}개 중 유실 {lost4}")
finally:
    if ORIG is None:
        if SPATH.exists():
            SPATH.unlink()
    else:
        io.open(SPATH, "w", encoding="utf-8", newline="\n").write(ORIG)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
