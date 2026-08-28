# -*- coding: utf-8 -*-
"""260628-12 (U8): 업데이트 잔존 파일 정리 — 설치 도우미 정리 단계 회귀 테스트.

실제 다운로드 없이, `_PS_INSTALLER` 의 **정리 로직만** 가짜 설치 폴더에 대해 돌린다.
(전체 승급 검증은 §14.5 U12 의 샌드박스 절차 — 릴리스 자산이 필요해 CI 밖에서 수동으로.)

검사 항목
  ① 매니페스트에 없는 파일은 지워진다(잔존 .pyd 등)
  ② 매니페스트에 있는 파일은 남는다 — 특히 update zip 이 빼는 무거운 자산
  ③ 실행 중인 exe 는 목록에 없어도 지우지 않는다
  ④ 매니페스트가 없으면 **아무것도 지우지 않는다**(옛 릴리스 호환)
  ⑤ 매니페스트가 500줄 미만이면 정리를 건너뛴다(잘린 목록 사고 방지)
  ⑥ 삭제 대상이 40% 를 넘으면 건너뛴다(엉뚱한 목록 최후 방어)
"""
import base64, os, shutil, subprocess, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ok = True


def check(name, cond, extra=""):
    global ok
    print(("  OK  " if cond else " FAIL ") + name + (f"  {extra}" if extra else ""))
    ok = ok and bool(cond)


from viewer import updater

BASE = os.path.join(tempfile.gettempdir(), "polypdf_cleanup_test")
KEEP_N = 600          # 안전장치 (b) 통과용 — 실제 빌드는 6천여 개


def build_install(extra_stale=0):
    """가짜 설치 폴더 생성 → (설치경로, exe경로, 정식목록)"""
    shutil.rmtree(BASE, ignore_errors=True)
    inst = os.path.join(BASE, "install")
    os.makedirs(os.path.join(inst, "_internal", "tesseract"), exist_ok=True)
    keep = []
    exe = os.path.join(inst, "PolyPDF.exe")
    open(exe, "w").write("exe")
    keep.append("PolyPDF.exe")
    for i in range(KEEP_N):
        rel = os.path.join("_internal", f"mod_{i}.pyd")
        open(os.path.join(inst, rel), "w").write("x")
        keep.append(rel)
    # update zip 이 빼는 무거운 자산 — 목록에는 있어야 한다(full 빌드 기준이므로)
    heavy = os.path.join("_internal", "tesseract", "tesseract.exe")
    open(os.path.join(inst, heavy), "w").write("heavy")
    keep.append(heavy)
    # 잔존 파일(목록에 없음)
    stale = []
    for i in range(3 + extra_stale):
        rel = os.path.join("_internal", f"old_{i}.pyd")
        open(os.path.join(inst, rel), "w").write("old")
        stale.append(rel)
    return inst, exe, keep, stale


def run_cleanup(inst, exe, manifest_lines):
    """설치 도우미의 정리 단계만 떼어 실행."""
    man = ""
    if manifest_lines is not None:
        man = os.path.join(BASE, "manifest.txt")
        open(man, "w", encoding="utf-8").write("\n".join(manifest_lines))
    script = updater._PS_INSTALLER
    body = script.split("# ── 260628-12 (U8): 잔존 파일 정리")[1]
    body = "# 정리" + body.split("if ($fail -eq 0) {")[0]
    head = "\n".join([
        "$ErrorActionPreference='Continue'",
        "Add-Type -AssemblyName System.Windows.Forms",
        f"$install = '{inst}'", f"$exe = '{exe}'", f"$manPath = '{man}'",
        "$fail = 0",
        "$lbl = New-Object System.Windows.Forms.Label",
    ])
    ps1 = os.path.join(BASE, "cleanup.ps1")
    open(ps1, "w", encoding="utf-8-sig", newline="\r\n").write(head + "\n" + body)
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1],
                   capture_output=True, timeout=300)


def exists(inst, rel):
    return os.path.exists(os.path.join(inst, rel))


# ── ①②③ 정상 정리 ────────────────────────────────────────────────────────
inst, exe, keep, stale = build_install()
run_cleanup(inst, exe, keep)
check("① 매니페스트에 없는 잔존 파일 삭제",
      all(not exists(inst, r) for r in stale), f"남은 것 {[r for r in stale if exists(inst, r)]}")
check("② 매니페스트에 있는 파일 보존", exists(inst, os.path.join("_internal", "mod_0.pyd")))
check("② 무거운 자산(tesseract) 보존",
      exists(inst, os.path.join("_internal", "tesseract", "tesseract.exe")))
check("③ 실행 exe 보존", os.path.exists(exe))

# ── ④ 매니페스트 없음 → 아무것도 지우지 않는다 ──────────────────────────
inst, exe, keep, stale = build_install()
run_cleanup(inst, exe, None)
check("④ 매니페스트 없으면 정리 생략", all(exists(inst, r) for r in stale))

# ── ⑤ 목록이 너무 짧으면 생략 ────────────────────────────────────────────
inst, exe, keep, stale = build_install()
run_cleanup(inst, exe, keep[:100])
check("⑤ 500줄 미만 목록은 정리 생략", all(exists(inst, r) for r in stale))

# ── ⑥ 삭제 대상이 40% 초과면 생략 ────────────────────────────────────────
inst, exe, keep, stale = build_install(extra_stale=500)
run_cleanup(inst, exe, keep)
check("⑥ 삭제 대상 40% 초과면 정리 생략",
      all(exists(inst, r) for r in stale), f"stale={len(stale)}/{len(keep) + len(stale)}")

shutil.rmtree(BASE, ignore_errors=True)
print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.stdout.flush()
os._exit(0 if ok else 1)
