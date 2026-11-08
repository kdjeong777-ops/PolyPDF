# -*- coding: utf-8 -*-
"""Tesseract 를 **한 번 띄워 여러 그림을** 읽는다 — 임시 파일 없이(단어학습 SOT §14.B '실행', 261108-18).

pytesseract 는 부를 때마다 tesseract.exe 하나를 띄우고 %TEMP% 에 그림·결과 파일을 만들고 지운다. 한 쪽 OCR 이 잡글 자리를
다시 읽느라 이것을 쪽당 수십 번 해(실측 3~28번) 백신이 프로세스 시작·임시 파일마다 검사해 느려지고 멈췄다.
여기서는 그림들을 **여러 쪽 TIFF 하나**로 묶어 표준 입력으로 넘기고(`tesseract stdin stdout …`), 결과(TSV·글자 상자)를
표준 출력에서 받아 쪽(=그림)마다 나눈다. 쪽마다 따로 읽으므로 결과는 pytesseract 로 한 장씩 읽은 것과 **같다**(실측 비교 —
`test_ocr_batch_run_261108.py`). 돌려주는 꼴도 pytesseract 와 같다(`data` = `image_to_data(Output.DICT)`, `boxes` = `image_to_boxes`).

pytesseract 가 다르게 다루는 그림(모드가 L·RGB·알파 섞인 것 밖이거나, 원래 형식이 PNG 가 아닌 것 — 그 형식으로 다시 저장해 넘긴다)은
그 그림만 종전대로 pytesseract 로 읽는다. Qt 를 쓰지 않는다 — 배경 스레드에서 그대로 부른다.
"""
from __future__ import annotations

import os
import shlex
import struct
import subprocess
import threading

RUNS = {"n": 0}            # tesseract 실행 수(검사가 센다 — 이 모듈과 pytesseract 대체 길 모두)
_LOCK = threading.Lock()


def _count() -> None:
    with _LOCK:
        RUNS["n"] += 1


def _exe() -> str:
    import pytesseract
    return str(pytesseract.pytesseract.tesseract_cmd)


def _plain(im):
    """이 길로 넘길 수 있는 그림이면 L·RGB 그림(알파는 pytesseract 처럼 흰 바탕에 얹는다), 아니면 None."""
    from PIL import Image
    if getattr(im, "format", None) not in (None, "PNG"):
        return None
    if "A" in im.getbands():
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, (0, 0), im.getchannel("A"))
        im = bg
    return im if im.mode in ("L", "RGB") else None


def tiff_pages(ims) -> bytes:
    """L·RGB 그림 여러 장 → 여러 쪽 TIFF(압축 없음, 해상도 태그 없음 — pytesseract 가 쓰는 PNG 처럼 tesseract 가 해상도를 짐작한다)."""
    out = bytearray(b"II*\x00\x00\x00\x00\x00")
    prev_next = 4
    for im in ims:
        w, h = im.size
        spp = 3 if im.mode == "RGB" else 1
        raw = im.tobytes()
        data_off = len(out)
        out += raw
        if len(out) % 2:
            out += b"\x00"
        bps_off = 0
        if spp == 3:
            bps_off = len(out)
            out += struct.pack("<HHH", 8, 8, 8)
        tags = [(256, 4, 1, w), (257, 4, 1, h), (258, 3, spp, bps_off if spp == 3 else 8),
                (259, 3, 1, 1), (262, 3, 1, 2 if spp == 3 else 1), (273, 4, 1, data_off),
                (277, 3, 1, spp), (278, 4, 1, h), (279, 4, 1, len(raw)), (284, 3, 1, 1)]
        ifd = len(out)
        struct.pack_into("<I", out, prev_next, ifd)
        out += struct.pack("<H", len(tags))
        for tag, typ, cnt, val in tags:
            if typ == 3 and cnt == 1:
                out += struct.pack("<HHIHH", tag, typ, cnt, val, 0)
            else:
                out += struct.pack("<HHII", tag, typ, cnt, val)
        prev_next = len(out)
        out += b"\x00\x00\x00\x00"
    return bytes(out)


def _run(ims, lang: str, config: str, tail: list) -> str:
    args = [_exe(), "stdin", "stdout"]
    if lang:
        args += ["-l", lang]
    args += shlex.split(config or "", posix=(os.name != "nt")) + tail
    kw = {"input": tiff_pages(ims), "capture_output": True, "env": os.environ}
    if os.name == "nt":                                  # 콘솔 창을 띄우지 않는다(`ocr._HiddenSubprocess` 와 같은 값)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kw.update(creationflags=0x08000000, startupinfo=si)
    _count()
    p = subprocess.run(args, **kw)
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError("tesseract %d: %s" % (p.returncode, err[-500:]))
    return p.stdout.decode("utf-8", "replace")


def _file_to_dict(tsv: str) -> dict:
    """pytesseract `file_to_dict(tsv, '\\t', -1)` 와 같다 — 숫자 칸은 `int(float())`, 글 칸(끝)은 그대로."""
    result = {}
    rows = [row.split("\t") for row in tsv.strip().split("\n")]
    if len(rows) < 2:
        return result
    header = rows.pop(0)
    length = len(header)
    if len(rows[-1]) < length:
        rows[-1].append("")
    str_col = length - 1
    for i, head in enumerate(header):
        result[head] = []
        for row in rows:
            if len(row) <= i:
                continue
            if i != str_col:
                try:
                    val = int(float(row[i]))
                except ValueError:
                    val = row[i]
            else:
                val = row[i]
            result[head].append(val)
    return result


def _split(plain_idx, n, fallback, batch):
    """일부는 이 길(`batch(그림들) -> 결과들`)로, 나머지는 `fallback(그림) -> 결과` 로 — 순서는 그대로."""
    out = [None] * n
    if plain_idx:
        for k, r in zip([k for k, _im in plain_idx], batch([im for _k, im in plain_idx])):
            out[k] = r
    return out


def data(images, lang: str, config: str = "") -> list:
    """그림마다 pytesseract `image_to_data(…, output_type=Output.DICT)` 와 같은 사전 — tesseract 한 번."""
    images = list(images)
    plain = [(k, _plain(im)) for k, im in enumerate(images)]
    ok = [(k, im) for k, im in plain if im is not None]

    def batch(ims):
        tsv = _run(ims, lang, config, ["-c", "tessedit_create_tsv=1"])
        lines = tsv.splitlines()
        head = lines[0] if lines else ""
        pages = {}
        for ln in lines[1:]:
            f = ln.split("\t")
            try:
                pg = int(f[1])
            except (IndexError, ValueError):
                continue
            f[1] = "1"                                   # 한 장씩 읽을 때처럼 page_num = 1
            pages.setdefault(pg, []).append("\t".join(f))
        return [_file_to_dict(head + "\n" + "\n".join(pages.get(k + 1, [])) + "\n") for k in range(len(ims))]
    out = _split(ok, len(images), None, batch) if ok else [None] * len(images)
    for k, im in enumerate(images):
        if out[k] is None:
            import pytesseract
            _count()
            out[k] = pytesseract.image_to_data(im, lang=lang, config=config, output_type=pytesseract.Output.DICT)
    return out


def boxes(images, lang: str, config: str = "") -> list:
    """그림마다 pytesseract `image_to_boxes(…)` 와 같은 글 — tesseract 한 번."""
    images = list(images)
    plain = [(k, _plain(im)) for k, im in enumerate(images)]
    ok = [(k, im) for k, im in plain if im is not None]

    def batch(ims):
        txt = _run(ims, lang, config, ["-c", "tessedit_create_boxfile=1", "batch.nochop", "makebox"])
        pages = {}
        for ln in txt.splitlines():
            f = ln.rsplit(" ", 1)
            if len(f) != 2:
                continue
            try:
                pg = int(f[1])
            except ValueError:
                continue
            pages.setdefault(pg, []).append(f[0] + " 0")    # 한 장씩 읽을 때처럼 쪽 번호 0
        return ["\n".join(pages.get(k, [])) + ("\n" if pages.get(k) else "") for k in range(len(ims))]
    out = _split(ok, len(images), None, batch) if ok else [None] * len(images)
    for k, im in enumerate(images):
        if out[k] is None:
            import pytesseract
            _count()
            out[k] = pytesseract.image_to_boxes(im, lang=lang, config=config)
    return out
