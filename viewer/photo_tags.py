# -*- coding: utf-8 -*-
"""사진 자동 해시태그 — 날짜·촬영 장비·지역(시·군·구)·종류 (태그 SOT §5.7, 261105-6, 사용자 결정).

모두 **오프라인**(태그 SOT §1-3) — 사진 머리(EXIF)·동봉 행정동 자료(`kr_dong`)·Tesseract 만 쓴다.
배경 워커(`photo_controller.PhotoIndexWorker`·`PhotoKindWorker`)에서 부른다. 저장은 메인이 태그 저장소의
**자동 칸 부분**(`TagStore.set_auto_part`)으로 — 사용자 태그·거절한 태그는 건드리지 않는다.

| 부분 | 값 | 출처 |
| meta | `YYYY-MM-DD`·장비·시군구·`스크린샷` | `photo_io.photo_info` (머리만) |
| kind | `영수증`·`명함`·`서류` | 글이 있어 보이는 사진만 작게 OCR(읽은 글은 판정에만 — 저장·색인하지 않는다, 사진 SOT D15) |
"""
from __future__ import annotations

import os
import re

AUTOTAG_VER = 2                 # 규칙을 바꾸면 올린다 — 다음 색인 훑기가 사진마다 다시 판정한다(2: 동 → 시·군·구, 261105-13)
KIND_VER = 1

SCREENSHOT = "스크린샷"
RECEIPT, CARD, DOCUMENT = "영수증", "명함", "서류"

_NAME_SHOT = re.compile(r"(screen ?shot|스크린샷|화면 ?캡처|캡처|screen ?capture|capture)", re.I)
# 화면 크기(짧은 변, 픽셀) — 휴대폰·태블릿·모니터. 카메라 정보 없는 PNG 의 보조 신호
SCREEN_SHORT = {640, 720, 750, 768, 800, 828, 900, 1024, 1050, 1080, 1125, 1170, 1179, 1200, 1242, 1284,
                1290, 1440, 1536, 1600, 1620, 1640, 1668, 1800, 2048, 2160}
_FAMILY = ("iphone", "ipad", "galaxy", "pixel", "xperia", "redmi", "mi ", "oneplus")
_CORP = re.compile(r"\b(corporation|corp\.?|co\.?|ltd\.?|inc\.?|imaging|electronics|company)\b", re.I)


def _clean(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣\-_]", "", s or "")


def date_tag(info: dict):
    """EXIF 촬영일 → 'YYYY-MM-DD'. 촬영 정보가 없으면 None(파일 날짜로는 만들지 않는다)."""
    t = (info.get("taken") or "").strip()
    if len(t) >= 10 and t[4] in ":-" and t[7] in ":-" and t[:4].isdigit() and t[5:7].isdigit() and t[8:10].isdigit():
        if t[:4] == "0000":
            return None
        return t[:4] + "-" + t[5:7] + "-" + t[8:10]
    return None


def device_tag(info: dict):
    """EXIF Make/Model → 장비 태그. 규칙(태그 SOT §5.7):
    ① 회사 이름은 첫 낱말만(`NIKON CORPORATION` → NIKON), 모두 소문자면 첫 글자만 대문자(`samsung` → Samsung)
    ② 모델에 회사 이름이나 제품군(iPhone·Galaxy·Pixel …)이 들어 있으면 모델만, 아니면 회사 + 모델
    ③ 글자·숫자·`-`·`_` 만 남기고 띄어쓰기를 지운다(`iPhone 15 Pro` → iPhone15Pro). 40자까지."""
    ex = info.get("exif") or {}
    make = _CORP.sub("", (ex.get("Make") or "").strip()).strip()
    model = (ex.get("Model") or "").strip()
    if not model:
        return None
    brand = (make.split() or [""])[0]
    if brand.islower():
        brand = brand[:1].upper() + brand[1:]
    low = model.lower() + " "
    if not brand or brand.lower() in low or any(low.startswith(f) for f in _FAMILY):
        tag = model
    else:
        tag = brand + " " + model
    tag = _clean(tag)[:40]
    return tag or None


def has_camera(info: dict) -> bool:
    ex = info.get("exif") or {}
    return bool((ex.get("Make") or "").strip() or (ex.get("Model") or "").strip())


def _shot_mark(path: str) -> bool:
    """사진 머리의 '스크린샷' 표시 — iOS 는 ImageDescription·UserComment 에 `Screenshot` 을 적는다. 머리만 읽는다."""
    if "|" in str(path):                         # zip 안 사진 — 파일이 아니다(이름·크기 신호만)
        return False
    try:
        from PIL import Image
        from viewer import photo_io
        photo_io._prep(path)
        with Image.open(str(path)) as im:
            ex = im.getexif()
            vals = [ex.get(0x010E)]
            try:
                vals.append((ex.get_ifd(0x8769) or {}).get(0x9286))
            except Exception:
                pass
        for v in vals:
            if isinstance(v, bytes):
                v = v.decode("latin-1", "ignore")
            if v and "screenshot" in str(v).lower():
                return True
    except Exception:
        pass
    return False


def is_screenshot(path: str, info: dict) -> bool:
    """카메라 정보가 없고, ① 머리에 스크린샷 표시(iOS) ② 이름이 스크린샷 꼴 ③ PNG 이고 짧은 변이 화면 크기·비율 1.3~2.4 중 하나."""
    if has_camera(info):
        return False
    name = os.path.basename(str(path).split("|")[-1])
    if _NAME_SHOT.search(name) or _shot_mark(path):
        return True
    w, h = int(info.get("width") or 0), int(info.get("height") or 0)
    if (info.get("format") or "").upper() == "PNG" and w and h:
        s, l = min(w, h), max(w, h)
        return s in SCREEN_SHORT and 1.3 <= l / s <= 2.4
    return False


def place_tag(info: dict):
    """GPS → 국내 시·군·구 이름('고양시'·'강남구' — 태그 SOT §5.7, 261105-13). 해외·자료 밖·위치 없음은 None."""
    g = info.get("gps")
    if not g:
        return None
    lat, lon = g
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    from viewer import kr_dong
    return kr_dong.region_name(lat, lon)


def alias(tag: str, rules=None) -> str:
    """사용자 별칭(`tag_rules.json` 의 alias, 태그 SOT §5.3) — 장비 코드를 사람이 아는 이름으로 바꿔 쓸 수 있다."""
    try:
        if rules is None:
            from viewer import auto_tag
            rules = auto_tag.load_rules()
        return (rules.get("alias") or {}).get(tag, tag)
    except Exception:
        return tag


def meta_tags(path: str, info: dict, rules=None) -> list:
    """사진 머리에서 만드는 자동 태그 — 날짜 → 지역 → 장비 → 스크린샷 차례."""
    out = []
    for t in (date_tag(info), place_tag(info), device_tag(info), SCREENSHOT if is_screenshot(path, info) else None):
        if t:
            t = alias(t, rules)
            if t and t not in out:
                out.append(t)
    return out


_DATE_TAG = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_date_tag(t: str) -> bool:
    return bool(_DATE_TAG.match(t or ""))


def date_groups(counts: dict) -> list:
    """`#` 풀다운의 '날짜' 묶음(검색 SOT §5.1) — 하루 태그를 해·달로 모아 [(토큰, 파일 수)], 새 것부터.
    해 → 그 해의 달 차례. 고르면 `#2026`·`#2026-11` 토큰이 들어가 앞부분 일치로 그 해·달 사진이 걸린다."""
    years, months = {}, {}
    for t, n in (counts or {}).items():
        if is_date_tag(t):
            years[t[:4]] = years.get(t[:4], 0) + n
            months[t[:7]] = months.get(t[:7], 0) + n
    out = []
    for y in sorted(years, reverse=True):
        out.append((y, years[y]))
        out += [(m, months[m]) for m in sorted(months, reverse=True) if m.startswith(y + "-")]
    return out


def row_tags(store, path: str, part: str, new: list) -> list:
    """사진 정보 색인 행에 적을 태그 글(워커가 미리 맞춰 둔다) — 저장소 사본의 태그에서 그 부분의 옛 값을 빼고 새 값을 더한다.
    거절·사용자 태그는 저장소 규칙(`set_auto_part`)과 같게 걸러진다. 실제 저장은 메인이 한다."""
    if store is None:
        return list(new)
    try:
        cur = store.get(path)
        old = {t.lower() for t in store.get_auto_part(path, part)} - {t.lower() for t in store.get_manual(path)}
        block = {t.lower() for t in store.get_rejected(path)}
    except Exception:
        return list(new)
    out = [t for t in cur if t.lower() not in old]
    low = {t.lower() for t in out}
    for t in new:
        if t.lower() not in low and t.lower() not in block:
            low.add(t.lower())
            out.append(t)
    return out


# ── 종류 — 영수증·명함·서류 (글이 있는 사진만 OCR) ─────────────────────────
TEXT_BRIGHT_MIN = 0.30          # 밝은 화소(> 160) 비율 — 종이 바탕
TEXT_SAT_MAX = 70.0             # 평균 채도(0~255) — 종이·글은 색이 옅다
TEXT_EDGE_MIN = 0.035           # 강한 가로 변화(|dx| > 40) 비율 — 글자 획
OCR_SIDE = 1600                 # 종류 판정 OCR 의 긴 변(픽셀)
DOC_WORDS_MIN = 60              # 서류 — 글이 빽빽
CARD_WORDS_MAX = 80             # 명함 — 짧은 글

_RECEIPT_WORDS = ("합계", "부가세", "부가가치세", "승인번호", "카드번호", "결제", "영수증", "공급가액", "과세", "면세",
                  "거스름", "받을금액", "판매", "매출", "단가", "수량", "카드승인", "사업자", "total", "vat", "receipt",
                  "subtotal", "cash", "change")
_PHONE = re.compile(r"(?<!\d)(0\d{1,2}|\+82)[\s.)\-]{0,2}\d{3,4}[\s.\-]\d{4}(?!\d)")
_CARD_MARK = re.compile(r"(?i)(\btel\b|\bt\s*[.:]|\bm\s*[.:]|mobile|\bfax\b|\bf\s*[.:]|h\.?p\b|e-?mail|휴대폰|전화|팩스)")
_TITLE = re.compile(r"(대표이사|대표|팀장|부장|차장|과장|대리|이사|실장|본부장|사원|연구원|주임|\bCEO\b|Manager|Director|Engineer)")
_WORD = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def text_like(path: str) -> bool:
    """글이 있어 보이는 사진인가 — 작은 판(긴 변 256)의 밝기·채도·가로 변화로. OCR 할 후보만 고른다."""
    try:
        from PIL import Image, ImageOps
        from viewer import photo_io
        photo_io._prep(path)
        with Image.open(str(path)) as im:
            try:
                im.draft("RGB", (512, 512))
            except Exception:
                pass
            im = ImageOps.exif_transpose(im)
            im.thumbnail((256, 256))
            rgb = im.convert("RGB")
        return text_stats_ok(*text_stats(rgb))
    except Exception:
        return False


def text_stats(rgb) -> tuple:
    """(밝은 비율, 평균 채도, 가로 변화 비율) — PIL RGB 그림."""
    from PIL import ImageStat
    g = rgb.convert("L")
    w, h = g.size
    px = g.tobytes()
    n = len(px) or 1
    bright = sum(1 for v in px if v > 160) / n
    sat = ImageStat.Stat(rgb.convert("HSV").getchannel("S")).mean[0]
    e = 0
    for y in range(h):
        row = px[y * w:(y + 1) * w]
        for x in range(1, w):
            if abs(row[x] - row[x - 1]) > 40:
                e += 1
    edge = e / max(1, (w - 1) * h)
    return bright, sat, edge


def text_stats_ok(bright, sat, edge) -> bool:
    return bright >= TEXT_BRIGHT_MIN and sat <= TEXT_SAT_MAX and edge >= TEXT_EDGE_MIN


def ocr_text(path: str, lang: str | None = None) -> str:
    """종류 판정용 OCR — 긴 변 `OCR_SIDE` 로 줄여 한 번. 글은 돌려주기만 한다(저장 없음)."""
    from PIL import Image, ImageOps
    from viewer import photo_io
    from viewer.study import ocr
    photo_io._prep(path)
    with Image.open(str(path)) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((OCR_SIDE, OCR_SIDE))
        im = im.convert("RGB")
    res = ocr.ocr_image(im, lang=ocr.resolve_lang(lang or ocr.default_lang()), dpi=150.0)
    return res.get("text") or ""


def classify_text(text: str):
    """OCR 글 → 영수증·명함·서류 또는 None. 차례: 영수증(낱말 둘 이상) ▶ 명함(짧은 글 + 연락처 신호 둘 이상) ▶ 서류(빽빽)."""
    t = text or ""
    low = t.lower().replace(" ", "")
    words = _WORD.findall(t)
    n = len(words)
    if n < 4:
        return None
    if sum(1 for k in _RECEIPT_WORDS if k in low) >= 2:
        return RECEIPT
    if n <= CARD_WORDS_MAX:
        sig = (bool(_PHONE.search(t)) + bool(_CARD_MARK.search(t)) + ("@" in t)
               + bool(re.search(r"(?i)www\.|https?://", t)) + bool(_TITLE.search(t)))
        if sig >= 2:
            return CARD
    if n >= DOC_WORDS_MIN:
        return DOCUMENT
    return None


def kind_tag(path: str, lang: str | None = None):
    """종류 태그 하나 또는 None — 후보가 아니면 OCR 하지 않는다."""
    if not text_like(path):
        return None
    return classify_text(ocr_text(path, lang))
