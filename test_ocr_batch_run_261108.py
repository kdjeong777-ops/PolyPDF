# -*- coding: utf-8 -*-
"""261108-18: OCR 이 자리마다 tesseract.exe 를 띄우지 않는다 — 여러 그림을 한 번에, 임시 파일 없이 (단어학습 SOT §14.24).

사용자 지시: "백신에서 오인하여 멈추지 않도록 전반적인 개선 방안을 계획하고 진행해. 이때 속도 관련된 문제도 같이 검토해".
종전: pytesseract 로 한 자리(psm 7)마다 tesseract 하나 + %TEMP% 그림·결과 파일, `resolve_lang` 마다 `--list-langs` 한 번 더 — 쪽당 3~28번.
  A  `tess_run.data`·`boxes` 가 그림 여러 장을 한 번에 읽은 결과 = pytesseract 로 한 장씩 읽은 결과(kor·eng, psm 7·6, 글자 상자)
  B  잡글 다시 읽기(`_reread_words`, 네 종류 자리) — 결과는 종전(자리마다 한 번)과 같고 tesseract 는 6번 이하, 임시 파일 없음
  C  실제 쪽(`build_page`, 스캔 모사 + 있으면 `_samples` 표본 — 읽기만) — 결과 같음, `--list-langs` 를 쪽마다 띄우지 않는다
"""
import os, sys, subprocess
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "test")
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path
import fitz
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from viewer.study import ocr, tess_run           # 종전 코드에는 tess_run 이 없다 — 여기서 실패한다
info = ocr.ensure_tesseract()
if not info.get("ok"):
    print("SKIP - Tesseract 가 없다:", info.get("error"))
    os._exit(0)
import pytesseract
langs = set(ocr.available_langs())

# 종전 길: 그림마다 pytesseract 한 번(= 261108-18 이전 코드가 하던 것)
_new = (tess_run.data, tess_run.boxes)


def _old_data(ims, lang, config=""):
    return [pytesseract.image_to_data(im, lang=lang, config=config, output_type=pytesseract.Output.DICT) for im in ims]


def _old_boxes(ims, lang, config=""):
    return [pytesseract.image_to_boxes(im, lang=lang, config=config) for im in ims]


def old_path(on: bool):
    tess_run.data, tess_run.boxes = (_old_data, _old_boxes) if on else _new


# 임시 파일·프로세스 세기
saves = {"n": 0}
_real_save = pytesseract.pytesseract.save


def _count_save(*a, **k):
    saves["n"] += 1
    return _real_save(*a, **k)
pytesseract.pytesseract.save = _count_save
listlangs = {"n": 0}
_RealPopen = subprocess.Popen


class _P(_RealPopen):
    def __init__(self, args, *a, **k):
        if isinstance(args, (list, tuple)) and "--list-langs" in [str(x) for x in args]:
            listlangs["n"] += 1
        super().__init__(args, *a, **k)
subprocess.Popen = _P

# 한글·영문이 섞인 쪽 그림(300dpi)
FONT = next((p for p in (r"C:\Windows\Fonts\malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf") if os.path.exists(p)), None)
LINES = ["4.5.2 배합설계 COE의 활주로 시험", "음식을 찾는다 (prepotence)이라 행동을", "Harbor captain 실존적 변화를 2024",
         "WASHO 설계법을 정립 AASHO 도로", "심리 검사의 이해 3.1.2 개요"]
d = fitz.open()
pg = d.new_page(width=595, height=420)
for k, t in enumerate(LINES):
    if FONT:
        pg.insert_text((50, 60 + k * 60), t, fontsize=17, fontfile=FONT, fontname="kr")
    else:
        pg.insert_text((50, 60 + k * 60), t, fontsize=17)
pix = pg.get_pixmap(dpi=300)
from PIL import Image
img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
lang = "kor+eng" if {"kor", "eng"} <= langs else "eng"
page = tess_run.data([img], lang, "--psm 4")[0]
boxes = [(int(x) - 6, int(y) - 6, int(x + w) + 6, int(y + h) + 6)
         for t, x, y, w, h in zip(page["text"], page["left"], page["top"], page["width"], page["height"])
         if str(t).strip() and w > 8]
chk(len(boxes) >= 12, "준비: 쪽 그림의 낱말 자리", len(boxes))
crops = [img.crop(b) for b in boxes[:12]]

# A
for lg in [x for x in ("kor", "eng") if x in langs]:
    for cfg in ("--psm 7", "--psm 6"):
        chk(tess_run.data(crops, lg, cfg) == _old_data(crops, lg, cfg), "A %s %s — 한 번에 읽은 낱말 TSV = 한 장씩" % (lg, cfg))
if "eng" in langs:
    chk(tess_run.boxes(crops, "eng", "--psm 7") == _old_boxes(crops, "eng", "--psm 7"), "A eng 글자 상자 = 한 장씩")
k0 = tess_run.RUNS["n"]
tess_run.data(crops, "eng", "--psm 7")
chk(tess_run.RUNS["n"] - k0 == 1, "A 그림 12장 = tesseract 한 번", tess_run.RUNS["n"] - k0)

# B — 네 종류 자리(한글 잡글 kor·괄호 속 영문 eng·번호 num·섞인 낱말 mix·갈린 영문 grp)
if {"kor", "eng"} <= langs:
    kinds = [("kor", "SAS"), ("kor", "YES"), ("eng", "(0100010009'"), ("eng", "o)e}(prep"), ("num", "45.2"),
             ("mix", "COES]"), ("grp", "WASHO"), ("kor", "ASA"), ("mix", "CBRAAYS"), ("kor", "OB")]
    items = [(i, (b[0] + 6, b[1] + 6, b[2] - b[0] - 12, b[3] - b[1] - 12), kd, s)
             for i, (b, (kd, s)) in enumerate(zip(boxes, kinds))]
    saves["n"] = 0
    k0 = tess_run.RUNS["n"]
    new = ocr._reread_words(img, items)
    runs, temp = tess_run.RUNS["n"] - k0, saves["n"]
    old_path(True)
    try:
        s0 = saves["n"]
        old = ocr._reread_words(img, items)
        old_runs = saves["n"] - s0
    finally:
        old_path(False)
    chk(new == old, "B 잡글 다시 읽기 결과가 종전(자리마다 한 번)과 같다", (new, old))
    chk(runs <= 6 and temp == 0, "B tesseract %d번(종전 %d번), 임시 파일 %d개" % (runs, old_runs, temp), (runs, old_runs, temp))
    chk(old_runs > runs, "B 종전보다 적게 띄운다", (old_runs, runs))

# C — 실제 쪽
import test_fixtures as _fx
ROOT = Path(HERE).parent
cases = [(_fx.scanned_pdf(), [0], "kor+eng")]
for name, pages, lg in (("HM.pdf", [10], "eng"), ("성격심리.pdf", [401], "kor+eng")):
    p = ROOT / "_samples" / name                     # 있으면 표본(읽기만) — 없으면 건너뛴다
    if p.exists():
        cases.append((str(p), pages, lg))
    else:
        print("SKIP - 표본 없음:", name)
for path, pages, lg in cases:
    doc = fitz.open(path)
    for pno in pages:
        if pno >= doc.page_count:
            continue
        saves["n"] = 0
        listlangs["n"] = 0
        k0 = tess_run.RUNS["n"]
        a = ocr.build_page(doc, pno, lang=lg, dpi=300, force_ocr=True)
        runs, temp, ll = tess_run.RUNS["n"] - k0, saves["n"], listlangs["n"]
        old_path(True)
        try:
            b = ocr.build_page(doc, pno, lang=lg, dpi=300, force_ocr=True)
        finally:
            old_path(False)
        name = "%s %d쪽" % (Path(path).name, pno + 1)
        chk(a["text"] == b["text"] and a["words"] == b["words"], "C %s — 글·낱말 상자가 종전과 같다" % name)
        chk(temp == 0 and ll == 0, "C %s — tesseract %d번, 임시 파일 0, --list-langs 0" % (name, runs), (temp, ll))
    doc.close()

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
