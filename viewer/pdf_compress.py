# -*- coding: utf-8 -*-
"""PDF 압축 (마스터 §4.7.19, 261014-21) — 그림만 다시 쓰고 글자는 그대로, 새 파일 `<이름>_압축.pdf`.

- `compress_file` — **보조 프로세스**에서 돈다(`convert/proc.serve` 의 `kind: compress`). PyMuPDF 의 그림 다시 쓰기는
  한 번의 긴 C 호출이라 배경 스레드여도 창을 세운다(응답성 SOT §12).
- `run` — 부모(배경 스레드)에서: 건너뛸 파일을 가르고, 보조 프로세스를 띄우고, 줄어들지 않았으면 결과를 지운다.
"""
from __future__ import annotations

import os
from pathlib import Path

from viewer.i18n import tr, tr_noop

# 수준 → (그림 목표 해상도 dpi, JPEG 품질). 목표보다 `THRESHOLD_K` 배 넘게 촘촘한 그림만 줄인다.
COMPRESS_LEVELS = {"low": (200, 85), "mid": (150, 75), "high": (100, 60)}
LEVEL_LABELS = {"low": tr_noop("약 — 그림 200 dpi"), "mid": tr_noop("보통 — 그림 150 dpi"), "high": tr_noop("강 — 그림 100 dpi")}
THRESHOLD_K = 1.3
MIN_GAIN = 0.05            # 이보다 덜 줄었으면 새 파일을 남기지 않는다(글자만 있는 작은 PDF 도 몇 바이트는 준다)
MIN_SAVED = 4096           # 261020-2: 줄어든 양도 이만큼은 돼야 — PyMuPDF 1.28 은 글자뿐인 798바이트 PDF 를 41바이트(5.1%) 줄여 쓸모없는 사본을 남겼다

SKIP_SIGNED = tr_noop("서명된 PDF — 사본에서 서명이 깨집니다")
SKIP_ENCRYPTED = tr_noop("암호 PDF — 사본이 암호 없이 저장됩니다")
SKIP_NOT_SMALLER = tr_noop("더 줄일 것이 없습니다")


class Skipped(Exception):
    """건너뛴 파일 — 까닭(`tr_noop` 문구)을 담는다."""


def out_path(src) -> Path:
    from viewer.pathutil import unique_path
    s = Path(src)
    return unique_path(s.with_name(tr("{stem}_압축").format(stem=s.stem) + ".pdf"), first=2)


def compress_file(src: str, dst: str, level: str) -> None:
    """보조 프로세스 쪽 — 그림 다시 쓰기 + 글꼴 부분집합 + 정리해서 저장."""
    import fitz
    dpi, q = COMPRESS_LEVELS.get(level, COMPRESS_LEVELS["mid"])
    doc = fitz.open(src)
    try:
        doc.rewrite_images(dpi_threshold=int(dpi * THRESHOLD_K), dpi_target=dpi, quality=q,
                           lossy=True, lossless=True, bitonal=False, color=True, gray=True)
        try:
            doc.subset_fonts()
        except Exception:
            pass
        doc.save(dst, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True, use_objstms=1)
    finally:
        doc.close()


def run(src, level: str, tick) -> tuple:
    """배경 스레드에서 — `(결과 경로, 원래 크기, 새 크기)`. 건너뛰면 `Skipped`, 중지면 `convert.Cancelled`."""
    from viewer import index_proc, sign_core
    from viewer.convert import Cancelled
    from viewer.convert.proc import KEY_ENV, SERVER_ARG
    src = str(src)
    if sign_core.is_signed_file(src):
        raise Skipped(SKIP_SIGNED)
    import fitz
    d = fitz.open(src)
    try:
        if d.needs_pass or d.is_encrypted:
            raise Skipped(SKIP_ENCRYPTED)
    finally:
        d.close()
    dst = out_path(src)
    state = {"cancel": False}

    def on_progress(done, total, label):
        try:
            tick(int(done), max(1, int(total)), str(label))
        except Cancelled:
            state["cancel"] = True
    tick(0, 1, Path(src).name)

    def cancelled():
        # 자식은 긴 C 호출 하나라 진행을 보내지 않는다 — 기다리는 동안 여기서 중지를 물어본다
        if not state["cancel"]:
            on_progress(0, 1, Path(src).name)
        return state["cancel"]
    ok = index_proc.run_job({"kind": "compress", "src": src, "dst": str(dst), "level": level},
                            on_progress, cancelled,
                            server_arg=SERVER_ARG, key_env=KEY_ENV, what="PDF")
    if state["cancel"]:
        _rm(dst)
        raise Cancelled()
    if ok is None or not dst.exists():
        _rm(dst)
        raise RuntimeError(tr("압축 파일을 만들지 못했습니다"))
    a, b = os.path.getsize(src), os.path.getsize(dst)
    if b > a * (1.0 - MIN_GAIN) or a - b < MIN_SAVED:
        _rm(dst)
        raise Skipped(SKIP_NOT_SMALLER)
    tick(1, 1, Path(src).name)
    return dst, a, b


def _rm(p) -> None:
    try:
        if p and Path(p).exists():
            os.remove(p)
    except Exception:
        pass
