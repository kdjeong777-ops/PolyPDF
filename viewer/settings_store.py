"""설정 저장/복원 (JSON) + 스키마 마이그레이션."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import QStandardPaths


CURRENT_SCHEMA = 11

# 260611-91: 배포용 기본값 프로파일 — '설정/스타일'만 담고 개인·머신 항목은 제외.
#   설정 키(이 항목들만 기본값에 포함/초기화 대상):
CONFIG_TOP_KEYS = ["preferences", "render_dpi", "fit_mode", "study_settings",
                   "read_aloud", "capture_mode", "capture_copy", "capture_sizes",
                   "panels_visible"]
#   개인(세션) 최상위 키 — 기본값에서 제외, 초기화 시 유지:
PERSONAL_TOP_KEYS = ["favorites", "law_favorites", "recent_folders",
                     "last_folder", "last_main",
                     "screenshots", "screenshots_meta"]
#   머신 종속 환경설정(경로 등) — 기본값에서 제외, 초기화 시 유지:
PERSONAL_PREF_KEYS = {"recording_dir", "recording_mic", "recording_system",
                      "ffmpeg_path", "bookmarker_path", "recording_keys",
                      "recording_test_ok"}
DEFAULT_PROFILE_NAME = "default_settings.json"


def settings_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def app_base_dir() -> Path:
    """실행 파일(또는 개발 시 패키지 루트) 디렉터리 — 배포용 기본값 파일 위치."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def default_profile_path() -> Path:
    return app_base_dir() / DEFAULT_PROFILE_NAME


def load_default_profile() -> Optional[dict]:
    """프로그램 폴더에 동봉된 기본값 프로파일(있으면). 배포자가 만들어 함께 배포."""
    p = default_profile_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def extract_distributable_defaults(settings: dict, name: str = "기본값") -> dict:
    """현재 설정에서 '배포 가능한 기본값'(설정·스타일)만 추출 — 개인·머신 항목 제외."""
    out = {"profile_name": name,
           "schema_version": int(settings.get("schema_version", CURRENT_SCHEMA))}
    for k in CONFIG_TOP_KEYS:
        if k in settings:
            out[k] = settings[k]
    prefs = dict(out.get("preferences") or {})
    for pk in PERSONAL_PREF_KEYS:
        prefs.pop(pk, None)
    out["preferences"] = prefs
    return out


def merge_reset(current: dict, profile: Optional[dict]) -> dict:
    """초기화용 병합: 개인·머신 항목은 현재값 유지, 설정·스타일은 profile(없으면 공장값)로.
    profile 에 없는 설정 키는 제거 → load() 가 하드코딩 기본값을 채운다(공장 초기화)."""
    profile = profile or {}
    out = dict(current)
    cur_prefs = dict(current.get("preferences") or {})
    new_prefs = dict(profile.get("preferences") or {})
    for k in PERSONAL_PREF_KEYS:          # 머신 경로 등은 유지
        if k in cur_prefs:
            new_prefs[k] = cur_prefs[k]
    for k in CONFIG_TOP_KEYS:
        if k == "preferences":
            out["preferences"] = new_prefs
        elif k in profile:
            out[k] = profile[k]
        else:
            out.pop(k, None)
    out["schema_version"] = CURRENT_SCHEMA
    return out


def settings_path(name: str = "settings.json") -> Path:
    return settings_dir() / name


def _migrate_v1_to_v2(d: dict) -> dict:
    d.setdefault("render_dpi", 192)
    d["schema_version"] = 2
    return d


def _migrate_v2_to_v3(d: dict) -> dict:
    d.setdefault("recent_folders", [])
    d["schema_version"] = 3
    return d


def _migrate_v3_to_v4(d: dict) -> dict:
    """v1.5.0: panels_visible + fit_mode 추가. history 항목의 page_index 기본값 보정."""
    d.setdefault("panels_visible", {
        "search_results": True,
        "bookmark_history": True,
        "search_history": True,
        "screenshots": True,
    })
    d.setdefault("fit_mode", "쪽 맞춤")  # "쪽 맞춤" — 유니코드 이스케이프
    d["fit_mode"] = d.get("fit_mode") or "쪽 맞춤"
    # 옛 history 항목에 page_index 가 없으면 0
    hist = d.get("history", {})
    for stack in ("bookmark", "search"):
        for item in hist.get(stack, []):
            if "page_index" not in item or item.get("page_index") is None:
                item["page_index"] = 0
    d["schema_version"] = 4
    return d


def _migrate_v4_to_v5(d: dict) -> dict:
    """v1.5.1: 사용자 설정 추가 — 시작 시 작업 복원/마지막 페이지/히스토리·스크린샷 한도."""
    prefs = d.setdefault("preferences", {})
    prefs.setdefault("restore_session", True)        # 시작 시 기존 작업 복원
    prefs.setdefault("restore_last_page", True)      # 마지막 페이지(False=첫 페이지)
    prefs.setdefault("history_max", 30)              # 책갈피·검색 히스토리 한도
    prefs.setdefault("screenshot_max", 30)           # 스크린샷 한도
    d["schema_version"] = 5
    return d


def _migrate_v5_to_v6(d: dict) -> dict:
    """v1.5.2: 히스토리·스크린샷 시작 시 복원 토글."""
    prefs = d.setdefault("preferences", {})
    prefs.setdefault("restore_history", True)        # 책갈피·검색 히스토리 복원
    prefs.setdefault("restore_screenshots", True)    # 스크린샷 리스트 복원
    d["schema_version"] = 6
    return d


def _migrate_v6_to_v7(d: dict) -> dict:
    """v1.6.1: 즐겨찾기 (favorites) 키 추가."""
    d.setdefault("favorites", [])
    d.setdefault("law_favorites", [])     # 260616-6: 법령·고시 즐겨찾기
    d["schema_version"] = 7
    return d


def _migrate_v7_to_v8(d: dict) -> dict:
    """v1.6.2: 히스토리 기능 제거 + 검색결과/스크린샷 2단 세로 레이아웃.

    - `history` 키 제거 (선택 목록 히스토리 + 검색 히스토리 패널 삭제).
    - `panels_visible` 의 bookmark_history / search_history 키 제거.
    - `preferences.history_max`, `restore_history` 제거 (스크린샷만 남음).
    - `screenshots_meta` 신규 추가 (스크린샷 카드별 원본 PDF + 페이지 메타. 빈 리스트 기본값).
    - 이전 `screenshots` (PNG 경로 리스트) 는 호환 보존.
    """
    d.pop("history", None)
    pv = d.get("panels_visible", {})
    pv.pop("bookmark_history", None)
    pv.pop("search_history", None)
    d["panels_visible"] = pv
    prefs = d.get("preferences", {})
    prefs.pop("history_max", None)
    prefs.pop("restore_history", None)
    d["preferences"] = prefs
    d.setdefault("screenshots_meta", [])
    d["schema_version"] = 8
    return d


def _migrate_v8_to_v9(d: dict) -> dict:
    """v1.6.4: 스크린샷 PDF 저장 옵션 + 카드 검색어 메타.

    - screenshots_meta 각 항목에 src_query 키가 없으면 None.
    - preferences.pdf_save_show_query/filename/pageno 기본값 False.
    idempotent: 이미 v9 인 dict 를 다시 통과시켜도 안전.
    """
    for m in d.get("screenshots_meta", []):
        m.setdefault("src_query", None)
    prefs = d.setdefault("preferences", {})
    prefs.setdefault("pdf_save_show_query", False)
    prefs.setdefault("pdf_save_show_filename", False)
    prefs.setdefault("pdf_save_show_pageno", False)
    d["schema_version"] = 9
    return d


def _migrate_v9_to_v10(d: dict) -> dict:
    """260606-25: 패널 툴바 재설계 — 이제 [뷰어모드]/[기능] 핵심 UI 이므로
    옛 기본값(숨김)을 1회 강제로 '보이기'로 올림. idempotent."""
    prefs = d.setdefault("preferences", {})
    prefs["show_panel_toolbar"] = True
    d["schema_version"] = 10
    return d


def _migrate_v10_to_v11(d: dict) -> dict:
    """260610-1: 파일 경계 이동(cross_file_nav)을 1회 강제 켜기.

    구버전(기본 OFF 시절) 앱이 종료 시 메모리의 옛 False 를 다시 저장해,
    설정 파일에 True 를 넣어도 다음 실행에서 False 로 되살아나는 좀비 상태가
    있었음(사용자 환경 실증). v9→v10 의 show_panel_toolbar 와 같은 방식으로
    1회 강제 True — 이후 사용자가 끄면 그 선택은 유지됨. idempotent."""
    prefs = d.setdefault("preferences", {})
    prefs["cross_file_nav"] = True
    d["schema_version"] = 11
    return d


def _migrate(d: dict) -> dict:
    v = d.get("schema_version", 1)
    if v < 2:
        d = _migrate_v1_to_v2(d)
    if v < 3:
        d = _migrate_v2_to_v3(d)
    if v < 4:
        d = _migrate_v3_to_v4(d)
    if v < 5:
        d = _migrate_v4_to_v5(d)
    if v < 6:
        d = _migrate_v5_to_v6(d)
    if v < 7:
        d = _migrate_v6_to_v7(d)
    if v < 8:
        d = _migrate_v7_to_v8(d)
    if v < 9:
        d = _migrate_v8_to_v9(d)
    if v < 10:
        d = _migrate_v9_to_v10(d)
    if v < 11:
        d = _migrate_v10_to_v11(d)
    return d


def load(name: str = "settings.json") -> dict:
    p = settings_path(name)
    if not p.exists():
        base = {
            "schema_version": CURRENT_SCHEMA,
            "recent_folders": [],
            "render_dpi": 192,
            "fit_mode": "쪽 맞춤",
            "panels_visible": {
                "search_results": True, "screenshots": True,
            },
            "screenshots_meta": [],
        }
        # 260611-91: 첫 실행 시 동봉된 배포용 기본값이 있으면 그 설정·스타일로 시작
        prof = load_default_profile()
        if prof:
            for k in CONFIG_TOP_KEYS:
                if k in prof:
                    base[k] = prof[k]
        return _migrate(base)
    try:
        raw = p.read_text(encoding="utf-8")
        d = json.loads(raw)
    except Exception:
        return {
            "schema_version": CURRENT_SCHEMA,
            "recent_folders": [],
            "render_dpi": 192,
            "fit_mode": "쪽 맞춤",
            "screenshots_meta": [],
        }
    # 260611-90: 프로그램 업데이트로 스키마가 올라가면, 마이그레이션 전 원본을 1회 백업.
    #   (혹시 모를 마이그레이션 결함으로부터 즐겨찾기·스타일 등 사용자 설정 보호)
    try:
        old_v = int(d.get("schema_version", 1))
    except Exception:
        old_v = 1
    if old_v < CURRENT_SCHEMA:
        try:
            bak = p.with_name(p.stem + f".v{old_v}.bak.json")
            if not bak.exists():
                bak.write_text(raw, encoding="utf-8")
        except Exception:
            pass
    return _migrate(d)


def save(data: dict, name: str = "settings.json") -> None:
    p = settings_path(name)
    data.setdefault("schema_version", CURRENT_SCHEMA)
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
