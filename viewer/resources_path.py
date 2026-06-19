"""자원 파일 경로 헬퍼 — PyInstaller --add-data 와 소스 실행 모두 지원."""
from __future__ import annotations
import sys
from pathlib import Path


def resource_path(name: str) -> str:
    """`resources/<name>` 의 절대 경로를 반환.

    검색 우선순위:
      1. PyInstaller `_MEIPASS/resources/<name>`
      2. 프로젝트 루트의 `resources/<name>` (소스 실행)
      3. 빈 문자열 (자원 없음 — 호출자가 빈 아이콘 처리)
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cand = Path(base) / "resources" / name
        if cand.exists():
            return str(cand)
    # 패키지 디렉터리 기준
    here = Path(__file__).resolve().parent.parent  # smart_pdf_viewer/
    cand = here / "resources" / name
    if cand.exists():
        return str(cand)
    return ""


def has_icon(name: str) -> bool:
    return bool(resource_path(name))
