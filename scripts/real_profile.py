# -*- coding: utf-8 -*-
"""261102-1: 사용자 **실제** 설정 폴더(`%APPDATA%\\LocalTools\\PolyPDF`)를 읽는 경로 — 마스터 §14.2.1.

Claude 데스크톱(MSIX 패키지)에서 띄운 셸·파이썬과 그 자식은 `%APPDATA%` 아래를 **파일 단위로** 패키지 복사본과 섞어 본다
(`%LOCALAPPDATA%\\Packages\\<패키지>\\LocalCache\\Roaming\\…` 에 있는 파일은 복사본, 없는 파일은 실제 것). 2026-11-02 실측:
복사본에 10-25 의 낡은 `index.db`(16MB)만 있어 셸은 **낡은 index.db + 실제 `-wal`** 을 함께 보았다 → 'malformed'·엉뚱한 행.
10-31 빌드 시험의 시드 색인 '손상'(T4)도 이 섞인 보기를 복사한 것으로 보인다(실제 index.db 2.55GB 는 integrity_check ok).
★ 그 프로세스는 패키지 신원이 없다(`GetCurrentPackageFullName` 은 '패키지 없음') — 신원으로는 가려낼 수 없다.

그래서 Windows 에서는 **관리 공유**(`\\\\localhost\\C$\\…`)로 읽는다 — 그 길은 가상화를 타지 않고, 가상화가 없을 때도 같은 파일이다.
관리 공유를 못 쓰는데 패키지 복사본 폴더가 있으면 `ok=False` — 부르는 쪽이 실제 폴더 읽기(시드·무결성)를 하지 않고 알린다.
★ 이 경로로도 **읽기만** 한다. 가상화된 셸에서의 삭제는 실제 폴더에 닿는다(마스터 §14.2.1) — 지우지 않는다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def admin_share(p: Path) -> Path:
    """`C:\\Users\\…` → `\\\\localhost\\C$\\Users\\…`."""
    drive, rest = os.path.splitdrive(str(p))
    return Path("\\\\localhost\\%s$%s" % (drive.rstrip(":"), rest))


def package_copies(name: str = "PolyPDF") -> list:
    """이 폴더의 패키지 복사본(있으면 셸이 섞어 본다)."""
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
    try:
        return [d for d in base.glob("*/LocalCache/Roaming/LocalTools/" + name) if d.is_dir()]
    except OSError:
        return []


def real_dir(name: str = "PolyPDF") -> tuple[Path, bool]:
    """(읽을 경로, 믿을 수 있나). Windows 는 관리 공유가 되면 그것 · 안 되면 그대로(복사본 폴더가 있으면 False)."""
    p = Path(os.environ["APPDATA"]) / "LocalTools" / name
    if sys.platform != "win32":
        return p, True
    q = admin_share(p)
    try:
        if q.parent.is_dir():
            return q, True
    except OSError:
        pass
    return p, not package_copies(name)


MIXED_MSG = ("이 셸은 실제 설정 폴더를 MSIX 패키지 복사본과 섞어 볼 수 있고 관리 공유(\\\\localhost\\C$)도 못 써서 "
             "실제 폴더를 읽지 않는다(마스터 §14.2.1). 탐색기로 확인하거나 패키지 밖 셸에서 다시.")
