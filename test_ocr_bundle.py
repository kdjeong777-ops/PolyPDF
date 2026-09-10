# -*- coding: utf-8 -*-
"""260910: OCR 자산이 **배포본에 실제로 들어가는가** (단어학습 SOT §14.13·§14.14).

사용자 보고: **"빌드된 것에 kor 관련이 없어 한국어 OCR 이 되지 않아."**

원인은 두 겹이었고, 둘 다 **빌드는 성공으로 끝나는** 형태였다.
  ① `tesseract/` 는 `.gitignore` 에 있어 CI 체크아웃에 없다 → `build_ci.bat` 의
     `if exist` 가 거짓이 되어 **아무것도 동봉하지 않고** 성공한다.
     개발 기계에는 그 폴더가 있으므로 **로컬 빌드로는 절대 드러나지 않는다.**
  ② `choco install tesseract` 기본 설치에는 **`eng` 만** 있다. `kor` 은 따로 받아야 한다.

이 검사는 **다음 사람이 그 장치를 지우면 잡는다.** 실제 파일이 아니라 *빌드 지시*를 본다 —
개발 기계에 자산이 있든 없든 같은 답을 내야 하기 때문이다.

검사 대상
  ① `release.yml` 이 `kor` traineddata 를 스스로 마련한다
  ② 마련되지 않으면 **배포를 멈춘다**(검증 단계가 `continue-on-error` 가 아니다)
  ③ `build_ci.bat` 이 무엇을 담았는지 남긴다
  ④ 런타임은 `kor` 이 든 tessdata 를 고른다(옛 설치본의 eng-only 폴더를 잡지 않게)
  ⑤ 단어장 생성이 텍스트 창과 같은 조건(언어 판정·워터마크)으로 읽는다
"""
import os, sys, inspect

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)
TAB = chr(9)
BS = chr(92)          # 경로 역슬래시는 상수로 — 리터럴에 쓰면 또 뭉개진다
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


yml = read(ROOT / ".github" / "workflows" / "release.yml")
bat = read(ROOT / "build_ci.bat")

print("=== ① CI 가 kor 을 스스로 마련한다 ===")
chk(bool(yml), "release.yml 을 읽었다")
chk("kor.traineddata" in yml or "kor" in yml and "tessdata_fast" in yml,
    "① kor traineddata 를 받는 단계가 있다")
chk("tessdata_fast" in yml, "① 공식 tessdata 저장소에서 받는다")
chk("choco install tesseract" in yml, "① Tesseract 엔진도 심는다")

print(NL + "=== ② 없으면 배포를 멈춘다 ===")
i = yml.find("Verify OCR bundle")
chk(i > 0, "② 검증 단계가 있다")
if i > 0:
    tail = yml[i:i + 1400]
    chk("continue-on-error" not in tail.split("- name:")[0],
        "② 검증 단계는 `continue-on-error` 가 아니다 — 실패하면 배포가 멈춘다")
    chk("throw" in tail, "② 없으면 예외를 던진다")
    chk("kor.traineddata" in tail or "$lang.traineddata" in tail,
        "② kor 이 있는지 확인한다")
    chk("tesseract.exe" in tail, "② 엔진이 있는지 확인한다")
    # 검증은 빌드보다 **앞**이라야 의미가 있다
    chk(i < yml.find("build_ci.bat"), "② 빌드 전에 확인한다")

print(NL + "=== ③ 빌드가 무엇을 담았는지 남긴다 ===")
chk("OCR 동봉 점검" in bat, "③ 동봉 여부를 화면에 남긴다")
chk("kor.traineddata" in bat, "③ kor 유무를 따로 알린다")
chk("TESS_ARG" in bat, "③ 동봉 인자를 쓴다")

# 260910-2: 진단이 **거짓말을 하지 않는가**. 실제로 겪은 사고 —
#   패치 스크립트가 `tesseract\tessdata` 의 역슬래시+t 를 **탭 문자**로 바꿔 넣어
#   `if exist` 가 영원히 거짓이 되었다. kor 은 동봉됐는데 "없음" 이라 찍혔다.
#   동봉 자체는 멀쩡하니 빌드는 성공하고, 화면만 반대로 말한다 — 가장 나쁜 형태다.
#   탭은 배치 경로에 쓸 일이 없으므로 **탭이 하나라도 있으면 그 사고**로 본다.
chk(TAB not in bat,
    "③ 배치에 탭 문자가 없다(경로의 역슬래시+t 가 탭으로 뭉개진 흔적)",
    "탭 %d 곳" % bat.count(TAB))
# 두 배치(layout)를 모두 본다: CI 는 tesseract+tessdata, 개발 기계(micromamba)는
#   tesseract+share+tessdata 에 둔다. 한쪽만 보면 다른 쪽에서 또 거짓말한다.
_CI_TD  = BS.join(["tesseract", "tessdata", "kor.traineddata"])
_DEV_TD = BS.join(["tesseract", "share", "tessdata", "kor.traineddata"])
chk(_CI_TD in bat,  "③ CI 배치를 본다", _CI_TD)
chk(_DEV_TD in bat, "③ 개발 배치를 본다", _DEV_TD)

print(NL + "=== ④ 런타임이 kor 이 든 폴더를 고른다 ===")
from viewer.study import ocr as so
src = inspect.getsource(so.ensure_tesseract)
chk("kor.traineddata" in src,
    "④ 후보가 둘이면 kor 이 **실제로 든** 쪽을 고른다(옛 eng-only 폴더 회피)")
chk("TESSDATA_PREFIX" in src, "④ tessdata 위치를 환경변수로 알린다")
chk(hasattr(so, "available_langs") and hasattr(so, "resolve_lang"),
    "④ 설치된 언어만 골라 쓴다(§14.8)")
chk(so.resolve_lang("kor+zzz") in ("kor", "kor+eng", "eng"),
    "④ 없는 언어를 요청해도 죽지 않는다", so.resolve_lang("kor+zzz"))

print(NL + "=== ⑤ 단어장 생성도 같은 조건으로 읽는다 (§14.14) ===")
from viewer.workers import StudyBuildWorker
run = inspect.getsource(StudyBuildWorker.run)
chk("drop_watermark_bg" in run, "⑤ 워터마크를 지우고 읽는다(§14.9)")
chk("detect_lang" in run or "resolve_lang" in run,
    "⑤ 언어를 고쳐진 판정으로 고른다(§14.8)")
chk("_detect_study_lang" not in run, "⑤ 옛 판정을 쓰지 않는다")
chk("clean_page_texts" in run, "⑤ 어휘는 정제된 글로 만든다(텍스트 창 §3.1.5)")
sig = inspect.signature(StudyBuildWorker.__init__)
chk("drop_watermark" in sig.parameters, "⑤ 워터마크는 끌 수 있다")
chk(sig.parameters["drop_watermark"].default is True, "⑤ 기본은 켬")
from viewer import study_controller as sc
csrc = inspect.getsource(sc)
chk("_detect_study_lang(path)" not in csrc.split("StudyBuildWorker(path, lang=")[1][:80]
    if "StudyBuildWorker(path, lang=" in csrc else True,
    "⑤ 부르는 쪽이 옛 판정을 넘기지 않는다")

print(NL + "=== ⑥ 이 기계의 트리와 진단이 어긋나지 않는다 ===")
tree = ROOT / "tesseract"
if not tree.exists():
    print("SKIP - 이 기계에는 tesseract 트리가 없다(CI 체크아웃과 같은 상태)")
else:
    hits = sorted(str(q.relative_to(ROOT)) for q in tree.rglob("kor.traineddata"))
    chk(bool(hits), "⑥ 트리에 kor.traineddata 가 있다", str(hits))
    for h in hits:
        chk(h.replace("/", BS) in bat,
            "⑥ 진단이 그 경로를 실제로 검사한다", h)

print(NL + "=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
