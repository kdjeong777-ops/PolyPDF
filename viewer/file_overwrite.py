"""260915-1(마스터 §4.7.5): 원본 PDF 를 **읽는 중인 핸들이 있어도** 덮어쓴다.

Windows 에서 `os.replace` 는 목적지를 지울 수 있어야 한다. 앱 안의 누구든 원본을
열어 두면(색인·목록 조사·텍스트 창 작업 스레드의 `fitz.open`, `open(..., "rb")`)
바꿔치기가 거부된다. 저장 직전에 UI 가 쥔 핸들은 `_close_main_view_doc` 가 놓지만,
**배경 스레드가 쥔 핸들은 UI 가 닫을 수 없다** — 그래서 같은 증상이 두 번 고친 뒤에도
되풀이됐다(260908-1 재시도, 260913-4 핸들 한 곳 해제).

그런 핸들은 모두 쓰기 공유를 허용한다(MuPDF·파이썬 모두 CRT 기본 `_SH_DENYNO`).
그래서 이름을 바꾸는 대신 **같은 파일의 내용을 제자리에서** 바꿔 쓸 수 있다(실측).
다른 프로그램이 쓰기를 막고 열었거나(예: Acrobat) 읽기 전용이면 여기서도 실패한다 —
그때만 새 이름으로 저장한다(호출측).

바꿔치기와 달리 원자적이지 않으므로, 쓰기 전에 원본을 백업하고 실패하면 되돌린다.
백업 이름은 `.pdf` 로 끝나지 않아 폴더 목록·색인에 나타나지 않는다.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

CHUNK = 4 << 20


def backup_path(dst) -> Path:
    dst = Path(dst)
    return dst.with_name("~" + dst.name + ".polypdf-bak")


def _write_into(fo, src: Path) -> None:
    fo.seek(0)
    with open(src, "rb") as fi:
        shutil.copyfileobj(fi, fo, CHUNK)
    fo.truncate()
    fo.flush()
    os.fsync(fo.fileno())


def overwrite_in_place(new_file, dst) -> None:
    """`new_file` 의 내용으로 `dst` 를 제자리에서 덮어쓰고 `new_file` 을 지운다.

    실패하면 `dst` 는 원래 내용으로 되돌리고 예외를 다시 던진다(`new_file` 은 남긴다).
    되돌리기마저 실패하면 백업을 남기고 그 경로를 예외에 적는다."""
    new_file, dst = Path(new_file), Path(dst)
    want = new_file.stat().st_size
    bak = backup_path(dst)
    shutil.copyfile(str(dst), str(bak))
    try:
        fo = open(dst, "r+b")          # 쓰기를 막은 핸들·읽기 전용이면 여기서 실패(아직 안 씀)
    except BaseException:
        bak.unlink(missing_ok=True)
        raise
    with fo:
        try:
            _write_into(fo, new_file)
            if os.fstat(fo.fileno()).st_size != want:
                raise OSError("덮어쓴 크기가 맞지 않습니다")
        except BaseException as e:
            try:
                _write_into(fo, bak)
            except BaseException as e2:
                raise OSError(f"원본 되돌리기 실패 — 백업: {bak} ({e2})") from e
            bak.unlink(missing_ok=True)
            raise
    bak.unlink(missing_ok=True)
    new_file.unlink(missing_ok=True)
