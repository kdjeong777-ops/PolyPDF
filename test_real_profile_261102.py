# -*- coding: utf-8 -*-
"""261102-1: 시험 도구는 사용자 실제 설정 폴더를 패키지 가상화 밖에서 읽는다 — 마스터 §14.2.1.

Claude 데스크톱(MSIX) 셸은 `%APPDATA%` 를 파일 단위로 복사본과 섞어 본다 — 낡은 복사본 index.db + 실제 -wal 을 함께 봐
'malformed' 가 났고, 빌드 시험 시드도 그 섞인 보기를 복사해 '손상' 으로 보였다(10-31 T4).
  A  `real_profile.admin_share` 가 드라이브를 관리 공유로 바꾼다
  B  관리 공유를 쓸 수 있으면 그 길로, 못 쓰면 `%APPDATA%` 그대로 — 패키지 복사본이 있으면 믿지 않는다(ok=False)
  C  실제 폴더를 읽는 도구(`probe_installed.seed`·`stable_check.REAL`)가 `real_profile` 을 쓴다 — `%APPDATA%` 를 바로 읽지 않는다
"""
import inspect, os, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


try:
    import real_profile
except ImportError as e:
    real_profile = None
    chk(False, "real_profile 모듈이 있다", e)

if real_profile is not None:
    chk(str(real_profile.admin_share(Path(r"C:\Users\u\AppData\Roaming\LocalTools\PolyPDF")))
        == r"\\localhost\C$\Users\u\AppData\Roaming\LocalTools\PolyPDF", "A 관리 공유 경로")
    p, ok = real_profile.real_dir()
    plain = Path(os.environ["APPDATA"]) / "LocalTools" / "PolyPDF"
    share = real_profile.admin_share(plain)
    if share.parent.is_dir():
        chk(p == share and ok, "B 관리 공유를 쓸 수 있으면 그 길로 읽는다", (p, ok))
    else:
        chk(p == plain and ok == (not real_profile.package_copies()), "B 관리 공유가 없으면 그대로 — 패키지 복사본이 있으면 믿지 않는다", (p, ok))
    # 실제로 섞여 보이는 기계(이 PC)라면: 관리 공유 쪽 index.db 가 셸 쪽과 다를 수 있다 — 관리 공유 쪽이 진짜
    cp = real_profile.package_copies()
    if cp and (cp[0] / "index.db").exists() and (share / "index.db").exists():
        chk(p == share, "B 복사본 index.db 가 있는 기계에서는 관리 공유로 읽는다(섞인 보기를 피한다)", p)

    import probe_installed, stable_check
    src = inspect.getsource(probe_installed.seed)
    chk("real_profile.real_dir" in src and "copytree(REAL," not in src, "C probe_installed.seed 가 real_profile 로 읽는다")
    chk(stable_check.REAL == real_profile.real_dir()[0], "C stable_check.REAL 이 real_profile 경로", stable_check.REAL)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
