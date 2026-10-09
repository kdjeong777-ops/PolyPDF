# -*- coding: utf-8 -*-
"""wordfreq 를 빠르게 쓰기 — 응답성 SOT §12 (261009-14).

wordfreq 는 데이터 폴더를 `locate.this_dir()` 로 찾는데, 그 함수가 `inspect.stack()` 을 부른다 — 모든
프레임의 소스 줄까지 읽는 함수라, 소스 파일이 없는 설치본(PyInstaller)에서는 **첫 import 가 1.9초**
걸렸다(설치본 실측, 문서를 처음 열 때 메인 스레드 정지). 데이터 파일을 읽을 때마다 다시 부른다.
같은 값(부른 쪽 파일의 폴더)을 `sys._getframe(1)` 로 돌려주는 함수로 바꿔 끼운다.

쓰는 곳은 `from viewer.study.wordfreq_fast import zipf_frequency` — wordfreq 를 직접 import 하지 않는다.
"""
import os
import sys
from pathlib import Path

_installed = False


def install() -> None:
    """`locate.this_dir` 를 가벼운 것으로 — wordfreq 를 불러오기 **전에** 한 번."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        import locate
    except Exception:
        return

    def this_dir() -> Path:
        g = sys._getframe(1).f_globals
        if "__file__" in g:
            return Path(os.path.abspath(g["__file__"])).parent
        return Path(os.path.abspath(os.getcwd()))

    locate.this_dir = this_dir


def zipf_frequency(word: str, lang: str, **kw) -> float:
    install()
    from wordfreq import zipf_frequency as _z
    return _z(word, lang, **kw)


def warm_up() -> None:
    """배경 스레드에서 한 번 — 첫 문서 열기가 import·첫 사전 읽기를 치르지 않게(MainWindow 가 시작 뒤 부른다)."""
    try:
        zipf_frequency("the", "en")
    except Exception:
        pass
