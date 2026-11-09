"""261109-3(릴리스 SOT §14.5 U16, 사용자 결정 A) — 자연 음성 모델을 설치본·휴대용에 넣는다.

A. `stage_voice` — components 자산 두 개를 고정 SHA-256 으로 확인하고 `voices\\supertonic-3-int8` 에 푼다(라이선스 사본 곁에),
   해시가 다르면(모델·라이선스 어느 쪽이든) 아무것도 쓰지 않는다 · 앱에 박은 값과 다른 가짜 묶음은 기본값으로 거절
B. `bundle_voice` — 모델 폴더 하나만 dist 로(받다 만 `.part`·숨김 폴더는 빼고), 원본이 없으면 3(경고)
C. CLI `python -m viewer.components check-voice` — 있으면 0, 없으면 1
D. 구성요소 창의 `install_voice` 도 같은 풀기(`_place_voice`)로 — file:// 묶음으로 실제 설치(개발 voices 를 건드리지 않게 자리를 바꾼다)
E. 배선 — build_ci.bat·build_exe.py 가 빌드 끝에 bundle-voice, release.yml 이 빌드 전 'Stage natural voice'(stage-voice) ·
   빌드 뒤 'Verify voice bundle'(check-voice, 실패해도 넘어가지 않음) · update zip 은 voices 를 뺀다
F. 같은 자리 — 구성요소 창이 받는 곳(`neural_tts.model_dir()`)이 `install_dir()\\voices\\supertonic-3-int8` 이고,
   설치본은 dist 를 통째로 {app} 에 넣는다(→ {app}\\voices)
"""
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, "" if cond else extra)
    if not cond:
        fails.append(msg)


def fake_archive(dst: Path, inner: str, files) -> Path:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as t:
        for n in files:
            data = ("fake " + n).encode()
            ti = tarfile.TarInfo(inner + "/" + n)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    dst.write_bytes(buf.getvalue())
    return dst


tmp = Path(tempfile.mkdtemp(prefix="polypdf_bundle_voice_"))
try:
    from viewer import components, updater
    from viewer.study import neural_tts as nt

    arc = fake_archive(tmp / nt.MODEL_ARCHIVE, nt.MODEL_INNER, nt.MODEL_FILES)
    lic = tmp / "LICENSE.txt"
    lic.write_bytes(b"OpenRAIL-M fake license text")
    h = hashlib.sha256(arc.read_bytes()).hexdigest()
    lh = hashlib.sha256(lic.read_bytes()).hexdigest()

    # ── A ──
    vo = tmp / "voices"
    ok, msg = components.stage_voice(arc, lic, vo, sha256=h, license_sha256=lh)
    d = vo / nt.MODEL_DIRNAME
    chk(ok and nt.model_ready(d) and (d / nt.LICENSE_LOCAL).read_bytes() == lic.read_bytes(),
        "A 맞는 해시 → voices\\supertonic-3-int8 에 모델 7개 + 라이선스 사본", msg)
    chk(components.check_voice(vo), "A check_voice 가 넣은 것을 알아본다")
    chk(not any(p.name.startswith(".") for p in vo.iterdir()), "A 임시·옛 폴더가 남지 않는다", str(list(vo.iterdir())))
    for label, kw in (("모델", dict(sha256="0" * 64, license_sha256=lh)), ("라이선스", dict(sha256=h, license_sha256="0" * 64))):
        vb = tmp / ("bad_" + label)
        ok, msg = components.stage_voice(arc, lic, vb, **kw)
        chk(not ok and not (vb / nt.MODEL_DIRNAME).exists(), "A %s 해시가 다르면 아무것도 쓰지 않는다" % label, msg)
    vb = tmp / "bad_default"
    ok, msg = components.stage_voice(arc, lic, vb)
    chk(not ok and not (vb / nt.MODEL_DIRNAME).exists(), "A 기본값은 앱에 박은 해시 — 가짜 묶음을 거절", msg)

    # ── B ──
    (d / "x.part").write_bytes(b"partial")
    (vo / ".unpack_junk").mkdir()
    dist = tmp / "dist" / "voices"
    rc = components.bundle_voice(vo, dist)
    chk(rc == 0 and components.check_voice(dist), "B 모델 폴더를 dist voices 로 복사", str(rc))
    chk(not (dist / nt.MODEL_DIRNAME / "x.part").exists() and not (dist / ".unpack_junk").exists(),
        "B 받다 만 .part·숨김 폴더는 넣지 않는다")
    chk(components.bundle_voice(tmp / "nowhere", tmp / "dist2") == 3 and not (tmp / "dist2").exists(),
        "B 원본이 없으면 3(경고) — 아무것도 만들지 않는다")

    # ── C ──
    def cli(*a):
        return subprocess.run([sys.executable, "-m", "viewer.components", *a], cwd=str(HERE),
                              capture_output=True, text=True, encoding="utf-8", errors="replace").returncode
    chk(cli("check-voice", str(dist)) == 0, "C check-voice 있으면 0")
    chk(cli("check-voice", str(tmp / "nowhere")) == 1, "C check-voice 없으면 1(CI 가 릴리스를 막는다)")
    chk(cli("stage-voice", str(arc), str(lic), str(tmp / "cli_v")) == 1 and not (tmp / "cli_v" / nt.MODEL_DIRNAME).exists(),
        "C stage-voice 는 앱에 박은 해시로 — 가짜 묶음이면 1")

    # ── D ──
    iv = tmp / "iv"
    orig = nt.voices_dir
    nt.voices_dir = lambda: iv
    try:
        ok, msg = components.install_voice(url=arc.as_uri(), sha256=h, license_url=lic.as_uri(), license_sha256=lh)
    finally:
        nt.voices_dir = orig
    chk(ok and components.check_voice(iv) and not any(p.name.startswith(".") for p in iv.iterdir())
        and not (iv / (nt.MODEL_ARCHIVE + ".part")).exists(),
        "D 구성요소 창 install_voice 도 같은 풀기 — 설치되고 받은 묶음·임시 폴더는 남지 않는다", msg)
    src = (HERE / "viewer" / "components.py").read_text(encoding="utf-8")
    body = src[src.index("def install_voice"):src.index("def _phase_fn")]
    chk("_place_voice(" in body and "extractall" not in body, "D install_voice 는 풀기를 _place_voice 한 길로")
    st = src[src.index("def stage_voice"):src.index("def bundle_voice")]
    chk("_place_voice(" in st, "D stage_voice 도 _place_voice")

    # ── E ──
    bat = (HERE / "build_ci.bat").read_text(encoding="utf-8")
    i_upx = bat.index("python scripts\\check_no_upx.py")
    i_bv = bat.find("python -m viewer.components bundle-voice voices dist\\PolyPDF\\voices")
    chk(i_bv > i_upx and i_bv < bat.index("BUILD SUCCESS"), "E build_ci.bat 가 빌드 끝(UPX 검사 뒤)에 bundle-voice")
    chk("bundle_voice(" in (HERE / "build_exe.py").read_text(encoding="utf-8"), "E build_exe.py 도 같은 bundle_voice")
    yml = (HERE / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def step(name):
        m = re.search(r"- name: %s.*?(?=\n      - name:|\Z)" % re.escape(name), yml, re.S)
        return m.group(0) if m else ""
    stg, ver = step("Stage natural voice"), step("Verify voice bundle")
    chk(stg and "stage-voice" in stg and "Supertonic-3-LICENSE.txt" in stg
        and yml.index("- name: Stage natural voice") < yml.index("- name: Build (PyInstaller"),
        "E release.yml 'Stage natural voice' 가 빌드 전에 stage-voice(고정 해시)")
    chk(ver and "check-voice dist\\PolyPDF\\voices" in ver and "continue-on-error" not in ver and "throw" in ver
        and yml.index("- name: Build (PyInstaller") < yml.index("- name: Verify voice bundle") < yml.index("- name: Package zips"),
        "E 'Verify voice bundle' — 빌드 뒤·묶기 전, 없으면 릴리스 실패")
    pkg = step("Package zips")
    chk('Remove-Item "$stage\\voices"' in pkg, "E update zip 은 voices 를 뺀다(휴대용은 덮어써 남는다)")
    port_i = pkg.index("$port = ")
    chk('Copy-Item "dist\\PolyPDF" "$pst\\PolyPDF" -Recurse' in pkg[port_i:], "E 휴대용 zip 은 dist 통째(voices 포함)")

    # ── F ──
    chk(nt.voices_dir() == updater.install_dir() / "voices" and nt.model_dir() == nt.voices_dir() / nt.MODEL_DIRNAME,
        "F 구성요소 창의 자리 = install_dir()\\voices\\supertonic-3-int8")
    iss = (HERE / "installer" / "PolyPDF.iss").read_text(encoding="utf-8-sig")
    chk('Source: "{#DistDir}\\*"; DestDir: "{app}"; Flags: recursesubdirs' in iss,
        "F 설치본은 dist 를 통째로 {app} 에 — dist\\PolyPDF\\voices → {app}\\voices(같은 자리)")
    chk('Type: filesandordirs; Name: "{app}"' in iss, "F 제거하면 {app} 과 함께 voices 도 지워진다")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(tmp), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
