# -*- coding: utf-8 -*-
"""사진 정보의 주소 (사진 보기 SOT §4.18·D20, 261111-21).

- `offline_address(lat, lon)` — 동봉 행정동 자료(`kr_dong.lookup`, 태그 SOT §5.7 소유 — 읽기·호출만)로
  '서울특별시 강남구 역삼1동'. 위치는 앱 밖으로 나가지 않는다. 처음 부르면 자료를 읽는다(~1초) — **배경에서만**.
- `online_address(lat, lon, lang)` — 사용자가 누르고 확인했을 때만 OpenStreetMap Nominatim reverse 한 번.
  사용자 정보는 싣지 않는다(User-Agent 는 앱 이름만). 같은 위치는 앱이 켜 있는 동안 기억한다. 네트워크 — **배경에서만**.
"""
from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request

from PyQt6.QtCore import QObject, pyqtSignal

PHOTO_ADDR_URL = "https://nominatim.openstreetmap.org/reverse"
PHOTO_ADDR_TIMEOUT = 8                    # 초
OSM_CREDIT = "© OpenStreetMap contributors"   # 261111-25 — 상세 주소 결과 옆 출처(ODbL), 정보 창 고지는 about.py
_UA = "PolyPDF photo viewer"

ABROAD, NOT_FOUND = "abroad", "not_found"  # offline_address 의 두 번째 값(주소가 없을 때 까닭)

_LOCK = threading.Lock()
_CACHE: dict = {}                         # (위도, 경도, 언어) → 상세 주소


def offline_address(lat, lon):
    """(주소 또는 '', 까닭) — 까닭은 '' (찾음)·ABROAD(국내 상자 밖)·NOT_FOUND(상자 안인데 못 찾음)."""
    from viewer import kr_dong
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return "", NOT_FOUND
    b = kr_dong.KR_BOX
    if not (b[0] <= lo <= b[2] and b[1] <= la <= b[3]):
        return "", ABROAD
    full = kr_dong.lookup(la, lo)
    return (full, "") if full else ("", NOT_FOUND)


# 국내 주소 — Nominatim address 칸을 큰 단위부터(서버 display_name 은 작은 단위부터라 한국 주소 꼴이 아니다)
_KR_KEYS = ("province", "state", "city", "county", "borough", "city_district", "district", "town",
            "municipality", "suburb", "quarter", "village", "hamlet", "neighbourhood", "road", "house_number")


def format_reply(data: dict) -> str:
    """Nominatim reverse 응답 → 한 줄 주소. 국내는 큰 단위부터, 국외는 서버 전체 이름."""
    if not isinstance(data, dict):
        return ""
    a = data.get("address") or {}
    if (a.get("country_code") or "").lower() == "kr" and a:
        out = []
        for k in _KR_KEYS:
            v = (a.get(k) or "").strip()
            if v and v not in out:
                out.append(v)
        if out:
            return " ".join(out)
    return (data.get("display_name") or "").strip()


def _fetch(url: str, timeout: float):              # 검사가 바꿔 끼운다(가짜 서버)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def online_address(lat, lon, lang: str = "ko") -> str:
    """상세 주소 — 실패하면 예외(부르는 쪽이 알린다). 같은 위치·언어는 기억한 것을 준다."""
    key = (round(float(lat), 6), round(float(lon), 6), lang or "ko")
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    q = urllib.parse.urlencode({"format": "jsonv2", "lat": "%.6f" % key[0], "lon": "%.6f" % key[1],
                                "zoom": 18, "addressdetails": 1, "accept-language": key[2]})
    text = format_reply(_fetch(PHOTO_ADDR_URL + "?" + q, PHOTO_ADDR_TIMEOUT))
    if not text:
        raise ValueError("empty address")
    with _LOCK:
        _CACHE[key] = text
    return text


class PhotoAddressWorker(QObject):
    """상세 주소(온라인) 한 번 — 응답성 SOT §4.4 감사표의 한 행. done(토큰, 주소 또는 '', 실패면 True)."""
    done = pyqtSignal(int, str, bool)
    finished = pyqtSignal()

    def __init__(self, token: int, lat, lon, lang: str):
        super().__init__()
        self.token, self.lat, self.lon, self.lang = token, lat, lon, lang

    def request_cancel(self):
        pass

    def run(self):
        try:
            try:
                self.done.emit(self.token, online_address(self.lat, self.lon, self.lang), False)
            except Exception:
                self.done.emit(self.token, "", True)
        finally:
            self.finished.emit()
