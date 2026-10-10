# -*- coding: utf-8 -*-
"""전자서명 자료 보관 — 디지털 ID·서명 그림·신뢰 목록·겉모양 설정 (보안 SOT §9).

모두 설정 폴더 `signing\\` 아래(휴대용 판은 `Data\\signing\\` — `settings_store.settings_dir()` 가 정한다).
목록은 `signing\\signing.json` 하나 — `settings.json` 에 두지 않는다(환경설정 허용목록·배포용 기본값과
섞이지 않게, SOT §9). 파일 경로는 `signing\\` 기준 상대 경로로 적는다(폴더 이전에 안 깨지게).

**평문 비밀번호는 어디에도 쓰지 않는다**(SOT §6). Hello 로 잠근 암호문만 `signing\\hello\\` 에 있다(sign_hello).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

INDEX = "signing.json"


def root() -> Path:
    from viewer.settings_store import settings_dir
    d = Path(settings_dir()) / "signing"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _empty() -> dict:
    return {"ids": [], "default_id": "", "images": [], "default_image": "",
            "appearance": {"show_name": True, "show_date": True, "show_reason": False, "layout": "overlay"},
            "last_reason": "", "last_location": "", "trusted": [],
            "tsa_on": False, "tsa_url": ""}                 # 2단계(보안 SOT §3.6): 타임스탬프 — 끄는 것이 기본


def load() -> dict:
    p = root() / INDEX
    data = _empty()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k in data and isinstance(v, type(data[k])):
                    data[k] = v
    except FileNotFoundError:
        pass
    except Exception:
        # 깨진 목록 — 지우지 않고 옆에 보관해 둔다(ID 파일 자체는 그대로 있다)
        try:
            p.replace(p.with_suffix(".broken.json"))
        except Exception:
            pass
    return data


def save(data: dict) -> None:
    """원자적 쓰기(임시 파일 + os.replace) — 마스터 §7.2 암호 기억과 같은 규칙."""
    p = root() / INDEX
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def abspath(rel: str) -> Path:
    return root() / Path(rel)


# ---- 디지털 ID ---------------------------------------------------------------

def add_id(pfx: bytes, info) -> dict:
    """`.pfx` 를 `ids\\<지문16>.pfx` 로 두고 목록에 넣는다. 이미 있으면 파일만 새로 쓴다."""
    d = load()
    rel = f"ids/{info.fp[:16]}.pfx"
    path = abspath(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(pfx)
    os.replace(tmp, path)
    entry = next((e for e in d["ids"] if e.get("fp") == info.fp), None)
    if entry is None:
        entry = {"fp": info.fp}
        d["ids"].append(entry)
    entry.update(name=info.name, email=info.email, org=info.org, not_after=info.not_after, file=rel)
    entry.setdefault("hello", False)
    if not d["default_id"]:
        d["default_id"] = info.fp
    # 내 디지털 ID 는 자동 신뢰(SOT §5)
    if info.fp not in d["trusted"]:
        d["trusted"].append(info.fp)
    save(d)
    return entry


def get_id(fp: str) -> dict | None:
    return next((e for e in load()["ids"] if e.get("fp") == fp), None)


def read_pfx(fp: str) -> bytes:
    e = get_id(fp)
    if e is None:
        raise FileNotFoundError(fp)
    return abspath(e["file"]).read_bytes()


def set_id_flag(fp: str, **kw) -> None:
    d = load()
    for e in d["ids"]:
        if e.get("fp") == fp:
            e.update(kw)
    save(d)


def remove_id(fp: str) -> None:
    """ID 와 그 Hello 보관값을 지운다(SOT §3.2·§6.1). 신뢰 목록의 지문은 남긴다 — 이미 서명한 문서를 계속 '신뢰함' 으로 본다."""
    d = load()
    e = next((x for x in d["ids"] if x.get("fp") == fp), None)
    if e is not None:
        try:
            abspath(e["file"]).unlink(missing_ok=True)
        except Exception:
            pass
        d["ids"] = [x for x in d["ids"] if x.get("fp") != fp]
        if d["default_id"] == fp:
            d["default_id"] = d["ids"][0]["fp"] if d["ids"] else ""
        save(d)
    try:
        from viewer import sign_hello
        sign_hello.forget(fp)
    except Exception:
        pass


# ---- 서명 그림 -----------------------------------------------------------------

_BAD = re.compile(r'[\\/:*?"<>|]+')


def add_image(img, name: str) -> dict:
    """정리한 RGBA 그림을 `images\\<이름>.png` 로. 같은 이름이면 덮어쓴다."""
    name = (_BAD.sub("_", (name or "").strip()) or "signature")[:40]
    rel = f"images/{name}.png"
    path = abspath(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path), "PNG")
    d = load()
    if not any(x.get("name") == name for x in d["images"]):
        d["images"].append({"name": name, "file": rel})
    if not d["default_image"]:
        d["default_image"] = name
    save(d)
    return {"name": name, "file": rel}


def image_path(name: str) -> str:
    e = next((x for x in load()["images"] if x.get("name") == name), None)
    return str(abspath(e["file"])) if e else ""


def remove_image(name: str) -> None:
    d = load()
    e = next((x for x in d["images"] if x.get("name") == name), None)
    if e is None:
        return
    try:
        abspath(e["file"]).unlink(missing_ok=True)
    except Exception:
        pass
    d["images"] = [x for x in d["images"] if x.get("name") != name]
    if d["default_image"] == name:
        d["default_image"] = d["images"][0]["name"] if d["images"] else ""
    save(d)


# ---- 신뢰 목록 ------------------------------------------------------------------

def trusted() -> list:
    return list(load()["trusted"])


def trust(fp: str, on: bool = True) -> None:
    d = load()
    fp = fp.lower()
    if on and fp not in d["trusted"]:
        d["trusted"].append(fp)
    if not on:
        d["trusted"] = [x for x in d["trusted"] if x != fp]
    save(d)
