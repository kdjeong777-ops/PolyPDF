# -*- coding: utf-8 -*-
"""261108-11·-12·-13(릴리스 SOT §14.2·§14.5 U16·U24): 백신 오인 줄이기 — 빌드·내려받기·업데이트 설치 길.

기획 `_review/기획/백신 오인·멈춤 줄이기.md` F2·F3·F4. 실제 설치본 실행·내려받기는 하지 않는다(사용자 설치를 바꾸므로) —
명령줄 조립·해시 확인·실패 대체를 실제 함수와 실제 MainWindow 업데이트 길로 본다.

A. -11 UPX: build_ci.bat·build_exe.py 의 PyInstaller 에 --noupx, 빌드 끝 check_no_upx 가 UPX 구획을 잡고 깨끗한 PE 는 통과
B. -12 구성요소: 고정 SHA-256 과 다르면 아무것도 쓰지 않고 실패, 같으면 설치 · CI 도 같은 값으로 확인
C. -13 설치본 길: 릴리스 자산에서 설치본·해시를 고르고, 설치본으로 깐 판만 'setup' · 명령줄 · 실행 직전 해시 확인
D. -13 실제 MainWindow 길: 받기(해시 필수) → 다른 창 닫기 → 설치본 실행 → 창 닫힘 / 다른 창이 남아 '아니오' 면 실행 안 함
E. -13 설치본(.iss): 앱이 끝나기를 기다린 뒤 taskkill, 조용한 업데이트는 원래 사용자 권한으로 다시 띄움 · release.yml 이 설치본 .sha256 을 올린다
F. 받아 둔 옛 업데이트 파일 정리
"""
import os, sys, re, struct, hashlib, tempfile, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
faulthandler.dump_traceback_later(240, exit=True)

from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_av_heuristics_%d" % os.getpid())     # 검사 작성 SOT §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
import modal_guard
modal_guard.install(label=lambda: "백신 오인", echo=False)                         # §14.7.2 의 6 — 검사가 필요한 답은 아래에서 다시 끼운다
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def read(rel):
    with open(os.path.join(HERE, rel), encoding="utf-8-sig") as f:
        return f.read()


def fake_pe(path, names):
    """MZ + PE 머리 + 구획 머리(이름만 의미 있음)."""
    b = bytearray(0x40)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x40)
    b += b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664, len(names), 0, 0, 0, 0, 0)
    for n in names:
        b += n.encode("latin-1").ljust(8, b"\0") + b"\0" * 32
    with open(path, "wb") as f:
        f.write(bytes(b))


try:
    tmp = tempfile.mkdtemp(prefix="polypdf_av_")

    # ── A ──
    bat = read("build_ci.bat")
    cmd = bat[bat.index("python -m PyInstaller"):bat.index("main.py", bat.index("python -m PyInstaller"))]
    chk("--noupx" in cmd, "A build_ci.bat PyInstaller 명령에 --noupx")
    chk("--noupx" in read("build_exe.py"), "A build_exe.py 에도 --noupx")
    i_chk = bat.find("python scripts\\check_no_upx.py")
    chk(i_chk > bat.index("python -m PyInstaller") and "errorlevel 1" in bat[i_chk:i_chk + 200],
        "A 빌드 끝에 check_no_upx — 실패하면 빌드 실패")
    sys.path.insert(0, os.path.join(HERE, "scripts"))
    import check_no_upx as cnu
    d = os.path.join(tmp, "dist"); os.makedirs(os.path.join(d, "_internal"))
    fake_pe(os.path.join(d, "PolyPDF.exe"), [".text", ".rdata", ".rsrc"])
    fake_pe(os.path.join(d, "_internal", "ok.pyd"), [".text"])
    chk(cnu.main(["x", d]) == 0, "A 깨끗한 PE 는 통과")
    fake_pe(os.path.join(d, "_internal", "packed.dll"), ["UPX0", "UPX1", ".rsrc"])
    chk([p.name for p in cnu.find_upx(d)] == ["packed.dll"] and cnu.main(["x", d]) == 1,
        "A UPX 구획(UPX0·UPX1)이 있는 dll 을 잡는다")

    # ── B ──
    from viewer import components as comp
    comp.install_dir = lambda: __import__("pathlib").Path(tmp)
    comp._assets = lambda repo, timeout=8.0: {"ffmpeg.exe": "https://github.com/x/f", "tesseract.zip": "https://github.com/x/t"}
    chk(set(comp.PINNED_SHA256) == {"ffmpeg.exe", "tesseract.zip"}
        and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in comp.PINNED_SHA256.values()),
        "B 두 구성요소의 고정 SHA-256")
    good = b"FFMPEG" * 1000
    comp._download = lambda url, progress=None, timeout=60.0: good
    ok, msg = comp.install_ffmpeg()
    chk(not ok and not os.path.exists(os.path.join(tmp, "ffmpeg.exe")) and not os.path.exists(os.path.join(tmp, "ffmpeg.exe.part")),
        "B 고정 해시와 다르면 실패하고 아무것도 쓰지 않는다", msg)
    real_pin = dict(comp.PINNED_SHA256)
    comp.PINNED_SHA256["ffmpeg.exe"] = hashlib.sha256(good).hexdigest()
    ok, msg = comp.install_ffmpeg()
    chk(ok and open(os.path.join(tmp, "ffmpeg.exe"), "rb").read() == good, "B 같으면 설치한다", msg)
    import io, zipfile
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("tesseract/Library/bin/tesseract.exe", b"x")
    comp._download = lambda url, progress=None, timeout=60.0: zb.getvalue()
    ok, msg = comp.install_tesseract()
    chk(not ok and not os.path.exists(os.path.join(tmp, "tesseract")), "B tesseract.zip 도 풀기 전에 확인 — 다르면 풀지 않는다", msg)
    comp.PINNED_SHA256.clear(); comp.PINNED_SHA256.update(real_pin)
    rel = read(".github/workflows/release.yml")
    chk(rel.count("python -m viewer.components verify") >= 2, "B CI 의 구성요소 마련도 같은 고정 해시로 확인")

    # ── C ──
    from viewer import updater
    gh = "https://github.com/kdjeong777-ops/PolyPDF/releases/download/v9.0.0/"
    names = ["PolyPDF-v9.0.0-win64-update.zip", "PolyPDF-v9.0.0-win64-update.zip.sha256",
             "PolyPDF-Setup-v9.0.0.exe", "PolyPDF-Setup-v9.0.0.exe.sha256"]
    relj = {"tag_name": "v9.0.0", "assets": [{"name": n, "browser_download_url": gh + n} for n in names]}
    info = updater._to_info(relj)
    chk(info["setup_url"] == gh + "PolyPDF-Setup-v9.0.0.exe" and info["setup_sha_url"].endswith(".exe.sha256")
        and info["asset_url"].endswith("update.zip"), "C 설치본·그 해시 자산을 고른다(zip 은 그대로)", str(info))
    info_nosha = updater._to_info({"tag_name": "v9.0.0", "assets": [a for a in relj["assets"] if a["name"] != names[3]]})
    chk(info_nosha["setup_url"] and not info_nosha["setup_sha_url"], "C 해시가 없으면 setup_sha_url 이 빈다")
    evil = updater._to_info({"tag_name": "v9.0.0", "assets": [{"name": "PolyPDF-Setup-v9.0.0.exe", "browser_download_url": "https://evil.example/s.exe"}]})
    chk(not evil["setup_url"], "C GitHub 밖 설치본은 버린다(U6)")
    real_ibs = updater.installed_by_setup
    updater.installed_by_setup = lambda inst=None: True
    chk(updater.update_kind(info) == "setup", "C 설치본으로 깐 판 + 설치본·해시 → setup")
    chk(updater.update_kind(info_nosha) == "zip", "C 설치본 해시가 없으면 종전 zip 길")
    updater.installed_by_setup = lambda inst=None: False
    chk(updater.update_kind(info) == "zip", "C 휴대용·zip 으로 깐 판은 종전 zip 길")
    updater.installed_by_setup = real_ibs
    # installed_by_setup — 휴대용 표식이 있으면 레지스트리와 무관하게 False
    pdir = os.path.join(tmp, "portable"); os.makedirs(pdir)
    open(os.path.join(pdir, "PolyPDF.portable"), "w").close()
    real_loc = updater.setup_install_location
    updater.setup_install_location = lambda: pdir + "\\"
    chk(not updater.installed_by_setup(pdir), "C 휴대용 표식이 있으면 설치본 길이 아니다")
    os.remove(os.path.join(pdir, "PolyPDF.portable"))
    chk(updater.installed_by_setup(pdir), "C Uninstall 항목의 설치 폴더 = 이 폴더(끝 \\ 무관)")
    chk(not updater.installed_by_setup(tmp), "C 다른 폴더면 아니다")
    updater.setup_install_location = real_loc
    a = updater.setup_args("en", 4242, r"C:\T\l.log")
    chk(a[:1] == ["/SILENT"] and "/NORESTART" in a and "/RELAUNCH=1" in a and "/WAITPID=4242" in a
        and "/APPLANG=en" in a and "/SUPPRESSMSGBOXES" not in a and "/VERYSILENT" not in a and a[-1] == r"/LOG=C:\T\l.log",
        "C 명령줄 — 진행 창만·끝나면 다시 띄움·이 앱을 기다림·언어 유지·기록", str(a))
    chk(not any(x.startswith("/APPLANG") for x in updater.setup_args('ko" /DIR=C:\\x', 1)), "C 언어 값이 이상하면 넣지 않는다")
    launched = []
    updater._launch_setup = lambda p, args: launched.append((p, list(args)))
    sp = os.path.join(tmp, "PolyPDF-update-setup.exe")
    open(sp, "wb").write(b"SETUP")
    h = hashlib.sha256(b"SETUP").hexdigest()
    chk(not updater.apply_setup(sp, "") and not launched, "C 해시가 없으면 실행하지 않는다")
    chk(not updater.apply_setup(sp, "0" * 64) and not launched and not os.path.exists(sp),
        "C 해시가 다르면(실행 직전 바꿔치기) 실행하지 않고 지운다")
    open(sp, "wb").write(b"SETUP")
    chk(updater.apply_setup(sp, h, "en") and launched and launched[0][0] == sp and "/APPLANG=en" in launched[0][1]
        and any(x == "/WAITPID=%d" % os.getpid() for x in launched[0][1]), "C 해시가 맞으면 실행 — 이 앱 pid 를 넘긴다", str(launched))

    # ── D 실제 MainWindow 길 ──
    from viewer.app import MainWindow
    from viewer.widgets import update_dialog as _ud
    log = []
    payload = b"NEW-SETUP" * 100
    hp = hashlib.sha256(payload).hexdigest()

    def fake_download(u, progress=None, timeout=30.0, expect_sha256=""):
        log.append(("download", u.rsplit("/", 1)[-1], expect_sha256))
        p = os.path.join(tempfile.mkdtemp(dir=tmp), "dl.bin")
        open(p, "wb").write(payload)
        if expect_sha256 and hashlib.sha256(payload).hexdigest() != expect_sha256:
            os.remove(p); return None
        return p

    updater.download_asset = fake_download
    sha_state = {"v": hp}
    updater.fetch_sha256 = lambda url, timeout=10.0: sha_state["v"] if url.endswith(".exe.sha256") else ""
    updater.fetch_expected_sha256 = lambda info, timeout=10.0: ""
    updater.fetch_manifest = lambda info, timeout=20.0: ""
    updater.apply_update = lambda **kw: (log.append(("ps-apply",)), True)[1]
    updater.installed_by_setup = lambda inst=None: True
    updater.is_frozen = lambda: True
    wins_state = {"v": {}}
    updater.other_windows = lambda exe="": dict(wins_state["v"])
    updater.request_close = lambda w: log.append(("close-req", sorted(w)))
    launched.clear()
    QMessageBox.warning = staticmethod(lambda *a, **k: (log.append(("warn", str(a[2])[:30] if len(a) > 2 else "")),
                                                        QMessageBox.StandardButton.No)[1])
    QMessageBox.information = staticmethod(lambda *a, **k: log.append(("info", str(a[2])[:20] if len(a) > 2 else "")))
    _ud.UpdateDialog.exec = lambda self: (setattr(self, "choice", "update"), 1)[1]

    def reset_pending():
        for kind in ("zip", "setup"):
            p = updater.pending_path(kind)
            for f in (p, p.with_suffix(".ver"), p.with_suffix(".sha256")):
                try:
                    os.remove(f)
                except OSError:
                    pass

    reset_pending()
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.show(); app.processEvents()
    mw._pending_update = info
    mw._on_update_result(info, True)
    app.processEvents()
    dl = [x for x in log if x[0] == "download"]
    chk(dl and dl[0][1] == "PolyPDF-Setup-v9.0.0.exe" and dl[0][2] == hp, "D 설치본을 해시와 함께 받는다", str(log))
    chk(launched and launched[0][0] == str(updater.pending_path("setup")) and ("ps-apply",) not in log,
        "D 받은 설치본을 실행 — PowerShell 도우미는 돌지 않는다", str(launched) + str(log))
    chk(not mw.isVisible(), "D 그 뒤 창이 닫힌다")

    # D2 — 설치본 해시 자산을 못 읽으면 받지도 실행하지도 않고, 창은 닫지 않는다
    log.clear(); launched.clear(); reset_pending(); sha_state["v"] = ""
    mw2 = MainWindow(); mw2._skip_save_on_close = True
    mw2.show(); app.processEvents()
    mw2._pending_update = info
    mw2._on_update_result(info, True)
    app.processEvents()
    chk(not launched and not any(x[0] == "download" for x in log) and mw2.isVisible(),
        "D2 설치본 해시가 없으면 받지 않고 창을 닫지 않는다", str(log))

    # D3 — 다른 창이 남고 '아니오' → 설치본을 실행하지 않고 '실패' 경고도 띄우지 않는다
    log.clear(); launched.clear(); reset_pending(); sha_state["v"] = hp
    wins_state["v"] = {999999: [1]}
    mw2._OTHER_WIN_WAIT_S = 0.6
    mw2._update_kind_cache = None
    mw2._upgrade_requested = False
    mw2.close()
    app.processEvents()
    chk(("close-req", [999999]) in log, "D3 다른 창에 먼저 닫기 요청", str(log))
    chk(any(x[0] == "warn" and "다른 PolyPinax 창" in x[1] for x in log) and not launched,
        "D3 남으면 묻고, '아니오' 면 설치본을 실행하지 않는다", str(log))
    chk(not any(x[0] == "warn" and "업그레이드 시작" in x[1] for x in log), "D3 거절은 '시작 실패' 경고가 아니다", str(log))

    # ── E ──
    iss = read("installer/PolyPDF.iss")
    pti = iss[iss.index("function PrepareToInstall"):]
    chk(0 <= pti.find("WaitForCaller();") < pti.find("taskkill"), "E 설치본은 앱이 끝나기를 기다린 뒤 taskkill")
    chk("{param:WAITPID|0}" in iss and "WaitForSingleObject" in iss, "E /WAITPID 로 그 프로세스를 기다린다")
    run = [l for l in iss.splitlines() if "ShouldRelaunch" in l and l.startswith("Filename")]
    chk(run and "runasoriginaluser" in run[0] and "nowait" in run[0], "E 조용한 업데이트 뒤 원래 사용자 권한으로 다시 띄운다", str(run))
    chk("{param:RELAUNCH|0}" in iss and "WizardSilent()" in iss[iss.index("function ShouldRelaunch"):], "E 다시 띄우기는 조용한 설치 + /RELAUNCH=1 일 때만")
    chk("setupsha" in rel and "$setup.sha256" in rel, "E release.yml 이 설치본 .sha256 을 만들어 올린다")

    # ── F ──
    reset_pending()
    for kind, ver in (("zip", "1.0.0"), ("setup", "99.0.0")):
        p = updater.pending_path(kind)
        p.write_bytes(b"x"); p.with_suffix(".ver").write_text(ver, encoding="utf-8"); p.with_suffix(".sha256").write_text("h", encoding="utf-8")
    n = updater.cleanup_pending("1.1.0")
    chk(n == 3 and not updater.pending_path("zip").exists() and updater.pending_path("setup").exists(),
        "F 지금 판보다 새롭지 않은 받아 둔 파일만 지운다", str(n))
    reset_pending()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
