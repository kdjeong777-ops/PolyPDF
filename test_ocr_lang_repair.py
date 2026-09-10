# -*- coding: utf-8 -*-
"""260910-6: 업데이트가 OCR 언어 자료를 건너뛰던 것과 그 자리 복구 (단어학습 SOT §14.17).

사용자 보고: **"배포본 설치시 아직도 OCR 시 kor 가 없다고 나와. 확실히 해결해."**

배포본에는 들어 있었다(zip 파일목록·설치본 압축 기록 모두 확인). 그런데 **앱의 자동
업데이트가 `tesseract` 폴더를 통째로 건너뛴다** — '무거운 자산은 안 바뀐다' 는 가정이었고
`kor` 은 beta.142 에서 새로 들어온 파일이라 그 가정이 깨졌다. 한 번이라도 앱 안에서
업데이트한 설치본은 새 배포본을 내도 영영 `kor` 을 못 받는다.

검사 대상
  (1) 업데이트 zip 이 `tessdata` 를 **남긴다**(엔진은 계속 뺀다)
  (2) 후보가 여럿이면 **필요한 언어를 더 많이 가진** 폴더를 쓴다
  (3) 쓰기 권한이 있는 사용자 폴더를 안다
  (4) 망가진 설치본을 **그 자리에서** 고친다(있는 것을 옮기고 모자란 것만 받는다)
  (5) 창이 알리는 데서 그치지 않고 **고칠 길**을 준다
"""
import os, sys, inspect, tempfile, shutil

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


def read(p):
    try:
        return Path(p).read_text(encoding="utf-8")
    except Exception:
        return ""


print("=== (1) 업데이트 zip 이 tessdata 를 남긴다 (§14.17 고침 1) ===")
yml = read(ROOT / ".github" / "workflows" / "release.yml")
chk(bool(yml), "(1) release.yml 을 읽었다")
i = yml.find("polypdf_upd")
tail = yml[i:i + 2200] if i > 0 else ""
chk('"tesseract"' not in tail.split("foreach")[1].split("}")[0] if "foreach" in tail else False,
    "(1) 더는 tesseract 를 통째로 지우지 않는다")
chk("tessdata" in tail and "-ne " in tail,
    "(1) tessdata 만 남기고 나머지를 지운다")
chk("ffmpeg.exe" in tail and "kiwipiepy_model" in tail,
    "(1) 무거운 나머지는 그대로 뺀다(업데이트가 무거워지지 않게)")

print()
print("=== (2)(3) 어느 tessdata 를 쓰나 ===")
from viewer.study import ocr as so
chk(hasattr(so, "user_tessdata_dir"), "(3) 쓰기 권한 폴더를 안다")
chk(hasattr(so, "repair_langs"), "(4) 고치는 길이 있다")
chk("LOCALAPPDATA" in inspect.getsource(so.user_tessdata_dir),
    "(3) 사용자 폴더는 LOCALAPPDATA 아래다")

tmp = Path(tempfile.mkdtemp(prefix="polypdf_td_"))
try:
    a = tmp / "few"; a.mkdir()
    (a / "eng.traineddata").write_bytes(b"x")
    b = tmp / "many"; b.mkdir()
    (b / "eng.traineddata").write_bytes(b"x")
    (b / "kor.traineddata").write_bytes(b"x")
    chk(so._pick_tessdata([a, b]) == b,
        "(2) 언어를 더 많이 가진 쪽을 고른다", str(so._pick_tessdata([a, b])))
    chk(so._pick_tessdata([b, a]) == b, "(2) 차례가 바뀌어도 같은 답")
    chk(so._pick_tessdata([b, tmp / "none"]) == b, "(2) 없는 폴더는 건너뛴다")
    # 같은 점수면 앞엣것(동봉본)
    c = tmp / "same"; c.mkdir()
    (c / "eng.traineddata").write_bytes(b"x")
    chk(so._pick_tessdata([a, c]) == a, "(2) 같으면 앞엣것(동봉본)을 쓴다")
    chk(so._langs_in(b) == {"eng", "kor"}, "(2) 폴더의 언어를 파일로 읽는다",
        str(sorted(so._langs_in(b))))

    print()
    print("=== (4) 망가진 설치본을 그 자리에서 고친다 ===")
    # 업데이트로 뒤처진 설치본 재현: eng 만 있다
    broken = tmp / "installed"; broken.mkdir()
    (broken / "eng.traineddata").write_bytes(b"ENG")
    user = tmp / "userdata"
    os.environ["POLYPDF_TESSDATA_DIR"] = str(user)
    os.environ["TESSDATA_PREFIX"] = str(broken)
    chk(so.user_tessdata_dir() == user, "(4) 우회로로 사용자 폴더를 정할 수 있다")
    # 받을 필요가 없도록 미리 넣어 둔다 — 네트워크 없이 '옮기기' 규칙만 본다
    user.mkdir(parents=True, exist_ok=True)
    (user / "kor.traineddata").write_bytes(b"KOR")
    ok, msg = so.repair_langs(["kor"])
    chk(ok, "(4) 이미 있으면 받지 않고 성공한다", str(msg)[:40])
    chk((user / "eng.traineddata").exists(),
        "(4) 있던 eng 를 함께 옮긴다 — 한 폴더만 보므로 두면 eng 를 잃는다")
    chk((user / "eng.traineddata").read_bytes() == b"ENG",
        "(4) 옮긴 내용이 그대로다")
    src = inspect.getsource(so.repair_langs)
    chk(".part" in src and "os.replace" in src,
        "(4) 받다 만 파일이 남지 않는다(.part 로 받고 바꿔 끼운다)")
    chk("reset_cache" in src, "(4) 고친 뒤 다시 고르게 만든다")
    chk("tessdata_fast" in so.TESSDATA_URL, "(4) 공식 저장소에서 받는다")
finally:
    os.environ.pop("POLYPDF_TESSDATA_DIR", None)
    os.environ.pop("TESSDATA_PREFIX", None)
    so.reset_cache()
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("=== (5) 창이 고칠 길을 준다 ===")
from viewer.app import MainWindow
w = inspect.getsource(MainWindow._start_text_ocr)
chk("_offer_ocr_lang_repair" in w, "(5) 알리기 전에 고칠지 먼저 묻는다")
o = inspect.getsource(MainWindow._offer_ocr_lang_repair)
chk("지금 내려받기" in o, "(5) 받을 수 있다")
chk("있는 언어로 진행" in o, "(5) 그냥 진행할 수도 있다")
chk("OcrLangRepairWorker" in o, "(5) 내려받기는 워커에서(응답성 §4 ①)")
chk("QProgressDialog" in o and "request_cancel" in o, "(5) 진행과 취소가 있다")
from viewer.workers import OcrLangRepairWorker
chk(hasattr(OcrLangRepairWorker, "request_cancel"), "(5) 워커를 멈출 수 있다")
r = inspect.getsource(OcrLangRepairWorker.run)
chk("repair_langs" in r, "(5) 워커가 그 고침을 부른다")
chk("self.done.emit" in r, "(5) 결과를 돌려준다")

print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
