# -*- coding: utf-8 -*-
"""등록 이미지(도장·명판·'원본대조필' 같은 스탬프) 보관 (261101-3, 마스터 §4.6.11).

설정 폴더 `stamps\\` 아래(휴대용 판은 `Data\\stamps\\` — `settings_store.settings_dir()` 가 정한다).
목록은 `stamps\\stamps.json` 하나, 파일은 `stamps\\<id>.png`(바탕 투명 그림) · `stamps\\<id>.pdf`(벡터 조각 1쪽).
경로는 `stamps\\` 기준 상대 경로로 적는다(폴더 이전에 안 깨지게). Qt 를 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

INDEX = "stamps.json"
MM_DEFAULT = 40.0        # 그림으로 등록한 것의 기본 폭(mm) — 벡터 조각은 끈 영역의 실제 폭
MM_MIN = 3.0
MM_MAX = 300.0
DATE_FORMATS = ("%Y-%m-%d", "%Y. %#m. %#d.", "%Y년 %#m월 %#d일", "%Y.%m.%d")
DATE_BOX_DEFAULT = [0.0, 0.75, 1.0, 0.25]          # 이미지 안 정규화 상자 [x, y, w, h] — 아래 25%
_BAD = re.compile(r'[\\/:*?"<>|]+')
# 261112-5(마스터 §4.6.11 '기본 항목'): 앱이 동봉한 일반 도장 — 첫 실행 때 한 번 넣고(`seeded`), 지우면 다시 생기지 않는다.
#   그림은 동봉 파일을 가리킨다(`builtin:` — 설정 폴더로 복사하지 않는다). 이름은 사용자 데이터 기본 이름(고칠 수 있다)
BUILTIN_PREFIX = "builtin:"
#   `ko`: 한국어 화면에서만 넣는다(다국어 SOT §7, 사용자 지시 '원본대조필은 한글판만') — 다른 언어로 시작하면 `seeded` 에도
#   적지 않아, 나중에 한국어로 바꾸면 그때 한 번 넣는다. 이미 넣은 것은 사용자 데이터라 언어를 바꿔도 지우지 않는다
BUILTIN = ({"key": "original_copy", "name": "원본대조필", "res": "stamps/original_copy.png", "width_mm": 40.0, "ko": True},)


def root() -> Path:
    from viewer.settings_store import settings_dir
    d = Path(settings_dir()) / "stamps"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _empty() -> dict:
    return {"items": [], "last": "", "seeded": []}


def _seed(data: dict) -> bool:
    """아직 넣지 않은 기본 항목을 목록 맨 앞에. 같은 이름이 이미 있으면(사용자가 먼저 등록) 넣은 것으로만 적는다. 바꿨으면 True."""
    from viewer.resources_path import resource_path
    from viewer.i18n import korea_only_visible
    changed = False
    for b in BUILTIN:
        if b["key"] in data["seeded"] or not resource_path(b["res"]):
            continue
        if b.get("ko") and not korea_only_visible():
            continue                              # 한국어 화면이 아니면 넣지도, 넣은 것으로 적지도 않는다

        data["seeded"].append(b["key"])
        changed = True
        if any(x.get("name") == b["name"] for x in data["items"]):
            continue
        sid = "b_" + b["key"]
        data["items"].insert(0, {"id": sid, "name": b["name"], "kind": "png", "file": BUILTIN_PREFIX + b["res"],
                                 "width_mm": b["width_mm"], "date": norm_date(None)})
        if not data["last"]:
            data["last"] = sid
    return changed


def load() -> dict:
    p = root() / INDEX
    data = _empty()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            if isinstance(raw.get("items"), list):
                data["items"] = [x for x in raw["items"] if isinstance(x, dict) and x.get("id")]
            if isinstance(raw.get("last"), str):
                data["last"] = raw["last"]
            if isinstance(raw.get("seeded"), list):
                data["seeded"] = [str(k) for k in raw["seeded"]]
    except FileNotFoundError:
        pass
    except Exception:
        try:                                     # 깨진 목록 — 지우지 않고 옆에 보관(그림 파일은 그대로)
            p.replace(p.with_suffix(".broken.json"))
        except Exception:
            pass
    if _seed(data):
        try:                                     # 한 번만(작은 json) — 다음부터는 seeded 가 막는다
            save(data)
        except Exception:
            pass
    return data


def save(data: dict) -> None:
    p = root() / INDEX
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(p))


def abspath(rel: str) -> Path:
    if rel.startswith(BUILTIN_PREFIX):            # 동봉 기본 항목
        from viewer.resources_path import resource_path
        return Path(resource_path(rel[len(BUILTIN_PREFIX):]) or rel)
    return root() / rel


def _unlink(rel: str) -> None:
    if rel and not rel.startswith(BUILTIN_PREFIX):  # 동봉 파일은 지우지 않는다
        try:
            abspath(rel).unlink(missing_ok=True)
        except Exception:
            pass


def move(sid: str, delta: int) -> bool:
    """차례를 delta(−1 위로 · +1 아래로)만큼. 옮겼으면 True."""
    d = load()
    ids = [x["id"] for x in d["items"]]
    if sid not in ids:
        return False
    i = ids.index(sid)
    j = max(0, min(len(ids) - 1, i + int(delta)))
    if i == j:
        return False
    d["items"].insert(j, d["items"].pop(i))
    save(d)
    return True


def items() -> list:
    return list(load()["items"])


def get(sid: str):
    return next((x for x in load()["items"] if x.get("id") == sid), None)


def last() -> dict | None:
    d = load()
    e = next((x for x in d["items"] if x.get("id") == d["last"]), None)
    return e or (d["items"][0] if d["items"] else None)


def set_last(sid: str) -> None:
    d = load()
    if d["last"] != sid:
        d["last"] = sid
        save(d)


def clamp_mm(v) -> float:
    try:
        v = float(v)
    except Exception:
        v = MM_DEFAULT
    return max(MM_MIN, min(MM_MAX, v))


def clean_name(name: str) -> str:
    return (_BAD.sub("_", (name or "").strip()) or "image")[:40]


def add(kind: str, payload: bytes, name: str, width_mm: float, date: dict | None = None) -> dict:
    """새 등록. `kind` = "png" | "pdf", `payload` = 그 파일의 바이트."""
    sid = uuid.uuid4().hex[:12]
    rel = f"{sid}.{'pdf' if kind == 'pdf' else 'png'}"
    abspath(rel).write_bytes(payload)
    e = {"id": sid, "name": clean_name(name), "kind": "pdf" if kind == "pdf" else "png",
         "file": rel, "width_mm": round(clamp_mm(width_mm), 1), "date": norm_date(date)}
    d = load()
    d["items"].append(e)
    d["last"] = sid
    save(d)
    return e


def update(sid: str, **fields) -> dict | None:
    """이름·폭·날짜·(그림을 다시 정리했으면) `payload`."""
    d = load()
    e = next((x for x in d["items"] if x.get("id") == sid), None)
    if e is None:
        return None
    if "payload" in fields and fields["payload"] is not None:
        kind = fields.get("kind", e.get("kind", "png"))
        rel = f"{sid}.{'pdf' if kind == 'pdf' else 'png'}"
        abspath(rel).write_bytes(fields["payload"])
        if rel != e.get("file"):
            _unlink(e.get("file", ""))
        e["file"], e["kind"] = rel, kind
    if "name" in fields:
        e["name"] = clean_name(fields["name"])
    if "width_mm" in fields:
        e["width_mm"] = round(clamp_mm(fields["width_mm"]), 1)
    if "date" in fields:
        e["date"] = norm_date(fields["date"])
    save(d)
    return dict(e)


def remove(sid: str) -> None:
    d = load()
    e = next((x for x in d["items"] if x.get("id") == sid), None)
    if e is None:
        return
    _unlink(e.get("file", ""))
    d["items"] = [x for x in d["items"] if x.get("id") != sid]
    if d["last"] == sid:
        d["last"] = d["items"][0]["id"] if d["items"] else ""
    save(d)


def reorder(ids: list) -> None:
    d = load()
    pos = {s: i for i, s in enumerate(ids)}
    d["items"].sort(key=lambda x: pos.get(x.get("id"), len(pos)))
    save(d)


def payload(e: dict) -> bytes:
    return abspath(e["file"]).read_bytes()


def norm_date(date) -> dict:
    """날짜 글자 설정 — {on, fmt, box: [x, y, w, h](이미지 안 0..1), color: '#rrggbb' | ''(= 잉크 평균색)}."""
    date = dict(date or {})
    fmt = date.get("fmt") if date.get("fmt") in DATE_FORMATS else DATE_FORMATS[0]
    box = date.get("box")
    try:
        box = [max(0.0, min(1.0, float(v))) for v in box][:4]
        if len(box) != 4 or box[2] <= 0.01 or box[3] <= 0.01:
            raise ValueError
    except Exception:
        box = list(DATE_BOX_DEFAULT)
    col = date.get("color") if isinstance(date.get("color"), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", date.get("color") or "") else ""
    return {"on": bool(date.get("on")), "fmt": fmt, "box": [round(v, 4) for v in box], "color": col}


def date_text(fmt: str, when=None) -> str:
    """`%#m`·`%#d` = 앞 0 없음. strftime 에 맡기지 않고 직접 푼다(OS·한글 무관)."""
    import datetime
    w = when or datetime.date.today()
    return (fmt.replace("%#m", str(w.month)).replace("%#d", str(w.day)).replace("%Y", f"{w.year:04d}")
            .replace("%m", f"{w.month:02d}").replace("%d", f"{w.day:02d}"))
