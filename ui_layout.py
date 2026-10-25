# -*- coding: utf-8 -*-
"""화면 자리 표 — 실제 `MainWindow` 의 탭 세부 줄에서 '명령 id → 탭·묶음·차례' 를 읽는다 (261025-9, 검사 도우미).

화면 자리의 원본은 코드(`app._build_menus`·`ribbon.DEFAULT_COLLECTION`)다. 검사가 단추 글자 목록을 손으로 적어 두면
자리를 옮길 때마다 기대가 낡는다(261025-1 뒤 실패 2건). 검사는 이 모듈로 자리를 묻는다:

    from ui_layout import layout, where
    layout(mw)["view"]            # [[ "view.single", "view.split", … ], [ "view.law", … ], [ "view.present" ]]
    where(mw, "tools.vprinter")   # ("tools", 묶음 번호, 묶음 안 차례) — 하위 메뉴 안이면 ("tools", g, i, "tools.install")

항목 이름: 명령 id(`cmd_id`)가 있으면 그것, 없으면 `item:<단추 글자>`(즐겨찾기 개별 단추 등).
숨긴 액션·숨긴 구분선은 세지 않는다 — 화면에 보이는 그대로다(메인 창을 `show()` 하지 않아도 된다).
검사가 아니다(이름이 `test_` 로 시작하지 않는다) — `test_sot_ui_layout.py` 가 디자인 SOT 표와 대조한다.
"""


def _cid(a) -> str:
    from viewer.widgets.ribbon import cmd_id
    return cmd_id(a) or ("item:" + a.iconText())


def layout(mw) -> dict:
    """탭 키 → 묶음 목록 → 항목 목록."""
    out = {}
    rb = mw._ribbon
    for key in rb.keys():
        row = rb.row(key)
        groups, cur = [], []
        for a in row.actions():
            if a.isSeparator():
                if a.isVisible() and cur:
                    groups.append(cur)
                    cur = []
                continue
            w = row.widgetForAction(a)
            if w is None or w.property("ribbonSpacer") or not a.isVisible():
                continue
            cur.append(_cid(a))
        if cur:
            groups.append(cur)
        out[key] = groups
    return out


def submenu_ids(action) -> list:
    """하위 메뉴(▾) 액션 안의 명령 id 차례."""
    m = action.menu() if action is not None else None
    return [_cid(x) for x in m.actions() if not x.isSeparator() and x.isVisible()] if m else []


def where(mw, cid: str):
    """명령의 원래 자리(탭·묶음·차례). `모음` 은 사용자가 고른 사본이라 다른 탭에 없을 때만 돌려준다."""
    lay = layout(mw)
    for key, groups in sorted(lay.items(), key=lambda kv: kv[0] == "collection"):
        for g, items in enumerate(groups):
            if cid in items:
                return (key, g, items.index(cid))
    for key in mw._ribbon.keys():                  # ▾ 안
        row = mw._ribbon.row(key)
        for a in row.actions():
            if a.menu() is not None and cid in submenu_ids(a):
                hit = where(mw, _cid(a))
                if hit:
                    return hit + (_cid(a),)
    return None
