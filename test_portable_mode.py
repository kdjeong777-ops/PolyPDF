# -*- coding: utf-8 -*-
"""261009-22: 휴대용(무설치) 모드 — 마스터 §14.9.

exe(개발 실행은 main.py) 옆에 `PolyPDF.portable` 이 있으면 설정·색인·창 기록·QSettings 를 `<폴더>\\Data` 에 둔다.
A. 실제 `main.py` 를 표식과 함께 띄우면 데이터 폴더(`Data-<프로필>`)에 창 기록이 생기고, 사용자 폴더(%APPDATA%)에는 생기지 않는다
B. 표식이 없으면 종전대로 사용자 폴더(휴대용이 아님)
C. 데이터 폴더를 만들 수 없으면(같은 이름의 파일이 있음 등) 휴대용을 쓰지 않는다(None — 앱은 사용자 폴더로 물러서고 안내)
D. 휴대용은 설치본과 다른 '넘기기 통로' 를 쓴다(설치본 창에 PDF 를 넘기지 않게)
E. 앱 안 업데이트는 휴대용 zip 을 업데이트 자산으로 고르지 않는다(update zip 이 없을 때도 full zip)
"""
import os, sys, time, subprocess, shutil, tempfile
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


prof = "port%d" % os.getpid()
marker = Path(HERE) / "PolyPDF.portable"
data = Path(HERE) / ("Data-" + prof)
appdata = Path(os.environ["APPDATA"]) / "LocalTools" / ("PolyPDF-" + prof)
env = dict(os.environ, POLYPDF_PROFILE=prof, QT_QPA_PLATFORM="offscreen")
env.pop("POLYPDF_OPEN_GATHER_NAME", None)


def launch_and_wait(check_dir: Path, secs=40):
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "main.py")], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t0 = time.time()
        while time.time() - t0 < secs and not (check_dir / "instances").exists():
            time.sleep(0.5)
        time.sleep(1.5)
    finally:
        p.kill(); p.wait(10)


had_marker = marker.exists()
try:
    # ── A ──
    marker.write_text("portable\n", encoding="utf-8")
    launch_and_wait(data)
    chk((data / "instances").exists(), "A 표식이 있으면 창 기록이 exe 옆 데이터 폴더에 생긴다", str(data))
    chk(not appdata.exists(), "A 사용자 폴더(%APPDATA%)에는 이 실행의 폴더가 생기지 않는다", str(appdata))
    # ── B ──
    marker.unlink()
    shutil.rmtree(data, ignore_errors=True)
    launch_and_wait(appdata)
    chk((appdata / "instances").exists() and not data.exists(), "B 표식이 없으면 종전대로 사용자 폴더", str(appdata))
    # ── C ──
    from viewer import settings_store
    tmp = Path(tempfile.mkdtemp(prefix="polypdf_port_"))
    (tmp / settings_store.PORTABLE_MARKER).write_text("x", encoding="utf-8")
    (tmp / "Data").write_text("파일이 자리를 막는다", encoding="utf-8")
    chk(settings_store.portable_dir(tmp) is None, "C 데이터 폴더를 만들 수 없으면 휴대용을 쓰지 않는다")
    d_ok = settings_store.portable_dir(tmp, "x")
    chk(d_ok is not None and d_ok.name == "Data-x", "C 쓸 수 있으면 데이터 폴더(시험 프로필은 Data-<프로필>)", str(d_ok))
    shutil.rmtree(tmp, ignore_errors=True)
    # ── D ──
    os.environ.pop("POLYPDF_PROFILE", None)
    from viewer import open_gather
    n_inst = open_gather.server_name()
    settings_store._DIR_OVERRIDE, settings_store.PORTABLE = r"E:\USB\PolyPDF\Data", True
    n_port = open_gather.server_name()
    settings_store._DIR_OVERRIDE, settings_store.PORTABLE = None, False
    chk(n_inst != n_port, "D 휴대용은 설치본과 다른 넘기기 통로를 쓴다", "%s / %s" % (n_inst, n_port))
    # ── E ──
    from viewer import updater

    def rel(*names):
        return {"tag_name": "v0.45.0-beta.999", "assets": [
            {"name": n, "browser_download_url": "https://github.com/kdjeong777-ops/PolyPDF/releases/download/v/" + n} for n in names]}
    i1 = updater._to_info(rel("PolyPDF-v-win64-portable.zip", "PolyPDF-v-win64.zip", "PolyPDF-v-win64-update.zip"))
    i2 = updater._to_info(rel("PolyPDF-v-win64-portable.zip", "PolyPDF-v-win64.zip"))
    chk(i1 and "update" in str(i1.get("asset_name", "")), "E 업데이트는 update zip", str(i1 and i1.get("asset_name")))
    chk(i2 and i2.get("asset_name") and "portable" not in i2["asset_name"], "E update zip 이 없어도 휴대용 zip 은 고르지 않는다", str(i2 and i2.get("asset_name")))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    if not had_marker and marker.exists():
        marker.unlink()
    shutil.rmtree(data, ignore_errors=True)
    shutil.rmtree(appdata, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
