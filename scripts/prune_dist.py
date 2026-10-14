# -*- coding: utf-8 -*-
"""빌드 결과에서 앱이 쓰지 않는 묶음을 뺀다 (마스터 §14.5 U23, 261014-27 — 개선 로드맵 P3-9 설치 크기).

`build_ci.bat` 의 `--collect-all PyQt6` 는 Qt 전체(Quick·QML·3D·Designer·블루투스…)를 싣고, wordfreq 는 40여 언어 사전을 싣는다.
앱이 쓰는 것은 QtCore·Gui·Widgets·Network·Multimedia(+Widgets)·PrintSupport·Svg 와 영어·한국어 사전뿐이다.

    python scripts\\prune_dist.py [dist\\PolyPDF] [--dry-run]

순서: ① `REMOVE` 목록을 지운다 ② 남은 Qt 플러그인 중 **지운 DLL 을 부르는 것**을 함께 지운다(되풀이)
③ 남은 모든 .dll/.pyd 의 가져오기(PE import)가 묶음 안·시스템에서 풀리는지 확인 — 못 풀리면 **실패(종료 코드 1)**.
지우는 목록은 '쓰지 않는다' 는 근거가 있는 것만 둔다. 새 Qt 모듈을 쓰게 되면 여기서 빼야 한다(검사 `test_prune_dist_261014.py`).
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import sys
from pathlib import Path

# _internal 기준 경로 패턴. 이름 근거: 코드에서 import 하지 않음(검사가 확인 — USED_QT 밖).
REMOVE = [
    # PyQt6 확장(.pyd) — 쓰지 않는 Qt 모듈
    *[f"PyQt6/{m}.pyd" for m in (
        "QAxContainer", "QtBluetooth", "QtDesigner", "QtHelp", "QtNfc", "QtPdf", "QtPdfWidgets", "QtPositioning",
        "QtQml", "QtQuick", "QtQuick3D", "QtQuickWidgets", "QtRemoteObjects", "QtSensors", "QtSerialPort",
        "QtSpatialAudio", "QtSql", "QtStateMachine", "QtTest", "QtTextToSpeech", "QtWebChannel", "QtWebSockets",
        "QtXml")],
    # Qt DLL
    *[f"PyQt6/Qt6/bin/{p}" for p in (
        "Qt6Bluetooth.dll", "Qt6Designer*.dll", "Qt6Help.dll", "Qt6Labs*.dll", "Qt6Nfc.dll", "Qt6Pdf*.dll",
        "Qt6Positioning*.dll", "Qt6Qml*.dll", "Qt6Quick*.dll", "Qt6RemoteObjects*.dll", "Qt6Sensors*.dll",
        "Qt6SerialPort.dll", "Qt6ShaderTools.dll", "Qt6SpatialAudio.dll", "Qt6Sql.dll", "Qt6StateMachine*.dll",
        "Qt6Test.dll", "Qt6TextToSpeech.dll", "Qt6WebChannel*.dll", "Qt6WebSockets.dll", "Qt6MultimediaQuick.dll",
        "Qt6Scxml*.dll", "Qt6VirtualKeyboard*.dll", "Qt6Charts*.dll", "Qt6DataVisualization*.dll", "Qt6Graphs*.dll",
        "Qt6Quick3D*.dll", "Qt6Location*.dll", "Qt6WebView*.dll", "Qt6Uitools.dll")],
    "PyQt6/Qt6/qml",
    "PyQt6/Qt6/qsci",
    *[f"PyQt6/Qt6/plugins/{d}" for d in (
        "assetimporters", "designer", "geometryloaders", "help", "position", "qmllint", "qmlls", "qmltooling",
        "renderers", "sceneparsers", "scxmldatamodel", "sensors", "sqldrivers", "texttospeech", "webview")],
    # Qt 번역 — 앱이 싣는 것은 qtbase_* (i18n.py). 나머지 모듈 번역은 뺀다(아래 KEEP_QT_TR 밖)
    # wordfreq — 영어·한국어만(viewer/study 의 zipf_frequency(…, "en"|"ko"))
    # tkinter(약 9MB)는 남긴다 — 빼면 PyInstaller 의 실행 훅(pyi_rth__tkinter)이 `_tcl_data` 를 못 찾아 exe 가 시작하자마자 끝난다(실측)
]
KEEP_QT_TR = ("qtbase_*", "qt_*", "qtmultimedia_*")
KEEP_WORDFREQ_LANG = ("en", "ko")


def _wordfreq_drop(internal: Path) -> list:
    d = internal / "wordfreq" / "data"
    if not d.is_dir():
        return []
    out = []
    for f in d.iterdir():
        n = f.name
        if n.startswith(("large_", "small_")):
            lang = n.split("_", 1)[1].split(".", 1)[0]
            if lang not in KEEP_WORDFREQ_LANG:
                out.append(f)
        elif n.startswith(("jieba_", "_chinese_")):        # 중국어 낱말 나누기
            out.append(f)
    return out


def _qt_tr_drop(internal: Path) -> list:
    d = internal / "PyQt6" / "Qt6" / "translations"
    if not d.is_dir():
        return []
    return [f for f in d.iterdir() if not any(fnmatch.fnmatch(f.name, p) for p in KEEP_QT_TR)]


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _imports(path: Path) -> list:
    import pefile
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        names = [e.dll.decode("ascii", "replace").lower() for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]
        pe.close()
        return names
    except Exception:
        return []


def _system_has(name: str) -> bool:
    if name.startswith(("api-ms-win-", "ext-ms-")):
        return True
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    return (Path(windir) / "System32" / name).exists()


def _binaries(root: Path):
    for f in root.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".dll", ".pyd", ".exe"):
            yield f


def missing_imports(root: Path) -> dict:
    """{바이너리: [못 푸는 DLL]} — 묶음 안(이름) 또는 시스템에 없으면 못 푼다."""
    have = {f.name.lower() for f in _binaries(root)}
    out = {}
    for f in _binaries(root):
        miss = [n for n in _imports(f) if n not in have and not _system_has(n)]
        if miss:
            out[f] = miss
    return out


def prune(dist: Path, dry_run: bool = False) -> dict:
    internal = dist / "_internal"
    if not internal.is_dir():
        raise SystemExit(f"없음: {internal}")
    before_missing = set(missing_imports(dist))          # 지우기 전부터 못 풀던 것(시스템에만 있는 DLL 등)은 따지지 않는다
    targets = []
    for pat in REMOVE:
        targets += sorted(internal.glob(pat))
    targets += _wordfreq_drop(internal) + _qt_tr_drop(internal)
    freed = 0
    removed = []
    for t in targets:
        if not t.exists():
            continue
        freed += _size(t)
        removed.append(t)
        if not dry_run:
            shutil.rmtree(t) if t.is_dir() else t.unlink()
    # 지운 DLL 을 부르는 플러그인은 함께(되풀이)
    plugins = internal / "PyQt6" / "Qt6" / "plugins"
    while not dry_run:
        broken = [f for f in missing_imports(dist) if f not in before_missing]
        extra = [f for f in broken if plugins in f.parents]
        if not extra:
            break
        for f in extra:
            freed += f.stat().st_size
            removed.append(f)
            f.unlink()
    broken = {} if dry_run else {f: m for f, m in missing_imports(dist).items() if f not in before_missing}
    return {"removed": removed, "freed": freed, "broken": broken}


def main(argv) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = [a for a in argv if not a.startswith("--")]
    dist = Path(args[0]) if args else Path(__file__).resolve().parent.parent / "dist" / "PolyPDF"
    r = prune(dist, dry_run="--dry-run" in argv)
    print(f"[prune] {len(r['removed'])}개 · {r['freed'] / 1048576:.1f} MB" + (" (dry-run)" if "--dry-run" in argv else ""))
    for f, m in r["broken"].items():
        print(f"[prune] 깨짐: {f.relative_to(dist)} → {', '.join(m)}")
    return 1 if r["broken"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
