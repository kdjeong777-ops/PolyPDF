# -*- coding: utf-8 -*-
"""앱이 남긴 낡은 임시 폴더 치우기 (마스터 §14.8.1, 261014-3 사용자 지시 '임시 파일이 계속 쌓이지 않도록').

앱은 끝날 때 `os._exit` 로 나간다(마스터 §14.8 종료 크래시 회피) — `atexit`·`TemporaryDirectory` 의 정리가 돌지 않는다.
비정상 종료·강제 종료도 마찬가지다. 그래서 정리를 **끝날 때가 아니라 시작할 때** 한 번 더 한다: 앱이 만드는
접두어의 폴더 중 `STALE_HOURS` 보다 오래된 것만 지운다(다른 PolyPDF 창이 지금 쓰는 폴더는 새것이라 건드리지 않는다).

★ 새 임시 폴더 접두어를 앱에 넣으면 `APP_TEMP_PREFIXES` 에 더한다. 쓰는 곳에서도 끝나면 바로 지우는 것이 먼저다.
"""
import os
import shutil
import tempfile
import threading
import time

# 앱 코드가 `tempfile.mkdtemp(prefix=...)` / `TemporaryDirectory(prefix=...)` 로 만드는 폴더
APP_TEMP_PREFIXES = (
    "polypdf_2up_",          # twoup.build_twoup — 병합·다단(끝나면 지운다)
    "polypdf_pages_",        # 썸네일 끼운 쪽(문서 닫을 때 지운다)
    "polypdf_printprev_",    # 인쇄 창 다단 미리보기(창 닫을 때 지운다)
    "polypdf_img2pdf_", "polypdf_nupprint_", "polypdf_bake_", "polypdf_nupfiles_", "polypdf_multi_",  # 인쇄(종료 때 지운다)
    "polypdf_upd_",          # 업데이트 내려받기
    "polypdf_tone_",         # 발표 시간 알림음(261014-3 전 — 지금은 고정 폴더 `polypdf_tone` 하나를 다시 쓴다)
    "polypdf_conv_",         # 형식 변환 — 스캔 쪽 사본·머리말 가린 사본(끝나면 지운다, 형식 변환 SOT §4.1)
    "polypdf_ocrb_",         # OCR 글자층 일괄 — 파일마다 임시 PDF(원본에 놓으면 비어 지운다, 텍스트 창 SOT §5.5)
)
STALE_HOURS = 24


def same_path(a, b) -> bool:
    """두 경로가 같은 파일인가 — 실제 경로(`normcase(realpath)`)로. str·Path·대소문자·슬래시·짧은 이름이 달라도 같다고 본다."""
    try:
        return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))
    except (OSError, ValueError):
        return False


def is_own_temp_dir(d, prefix: str) -> bool:
    """`d` 가 앱이 만든 전용 임시 폴더인가 — 이름이 `prefix` 로 시작하고 **시스템 임시 폴더 바로 아래**(실제 경로로).
    넘겨받은 경로의 부모를 지우기 전에 부른다(마스터 §14.8.1, 261112-13·14)."""
    if not prefix or not d:
        return False
    try:
        real = os.path.realpath(str(d))
        if not os.path.basename(real).startswith(prefix):
            return False
        root = os.path.normcase(os.path.realpath(tempfile.gettempdir()))
        return os.path.normcase(os.path.dirname(real)) == root
    except (OSError, ValueError):
        return False


def remove_own_temp_dir(d, prefix: str, who: str = "") -> bool:
    """전용 임시 폴더일 때만 통째로 지운다. 아니면 아무것도 지우지 않고 오류 출력에 한 줄(창 모드 exe 는 stderr 가 없을 수 있다).
    지웠으면 True."""
    if not d:
        return False
    if not is_own_temp_dir(d, prefix):
        try:
            import sys
            print(f"{who or 'temp_sweep'}: not an app temp dir ({prefix}), kept:", d, file=sys.stderr)
        except Exception:
            pass
        return False
    shutil.rmtree(str(d), ignore_errors=True)
    return True


def sweep(tmp=None, max_age_h: float = STALE_HOURS, now=None) -> int:
    """낡은 앱 임시 폴더를 지운다. 지운 폴더 수. 실패한 것은 건너뛴다(다음 시작 때 다시)."""
    tmp = tmp or tempfile.gettempdir()
    now = time.time() if now is None else now
    n = 0
    try:
        it = os.scandir(tmp)
    except OSError:
        return 0
    with it:
        for e in it:
            try:
                if not e.name.startswith(APP_TEMP_PREFIXES) or not e.is_dir(follow_symlinks=False):
                    continue
                if now - e.stat(follow_symlinks=False).st_mtime < max_age_h * 3600:
                    continue
                shutil.rmtree(e.path, ignore_errors=True)
                if not os.path.exists(e.path):
                    n += 1
            except OSError:
                continue
    return n


def sweep_in_background() -> threading.Thread:
    """시작 직후 창을 세우지 않게 배경 스레드로(응답성 SOT §4.4 — 파일 작업은 메인에서 하지 않는다)."""
    t = threading.Thread(target=sweep, name="polypdf-temp-sweep", daemon=True)
    t.start()
    return t
