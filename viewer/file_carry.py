# -*- coding: utf-8 -*-
"""261105-8(마스터 §4.7.14): 파일을 옮기거나 이름을 바꾸거나 복사한 뒤 **경로를 키로 쓰는 기록**을 새 경로로.

설정 폴더의 기록은 파일 경로(또는 그 해시)를 키로 쓴다 — 옮기지 않으면 OCR·고친 글이 **사라진 것처럼** 보이고
다시 읽어야 했다(쪽당 4초대). 여기서 맡는 것(배경 스레드에서 불러도 된다 — 앱은 `_file_op_bg` 로):

| 기록 | 키 | 함수 |
| --- | --- | --- |
| OCR 쪽·낱말·어휘(`study.db` 저장본 + 보류 저장소) | `file_key_for`(경로 해시) | `StudyStore.carry_file` |
| 고른·지운 낱말(`user_study.db` `sel_event`) | 같은 해시 | `UserStore.carry_file` |
| 텍스트 창 고침·하이라이트·반영 표시(`text_fix.json`) | `norm_key` | `TextFixStore.carry_file` |

폴더 사이드카(꾸밈 `page_meta.json`·`hyperlinks.json`)·메모리 상태는 앱이 메인에서 맞춘다(`_on_files_relocated`·`_on_files_copied`).
태그는 이 길이 아니다 — 이동은 `TagStore.rehome`, 복사는 `TagStore.copy_tags`(`MainWindow._on_files_copied`, 태그 SOT §6.1-⑥).
"""
from __future__ import annotations

from pathlib import Path


def carry_records(pairs, copy: bool = False, study_db=None, user_db=None, fix_store=None) -> int:
    """pairs = [(옛 경로, 새 경로), ...]. 옮긴(복사한) 파일 수. 한 기록이 실패해도 나머지는 한다."""
    from viewer.study.study_store import StudyStore, UserStore, file_key_for
    from viewer import dbutil
    pairs = [(str(a), str(b)) for a, b in (pairs or []) if a and b]
    if not pairs:
        return 0
    hit = set()
    keys = [(file_key_for(a), file_key_for(b), b) for a, b in pairs]
    try:
        st = StudyStore(study_db, busy_ms=dbutil.BUSY_MS_BG)
        try:
            for (ka, kb, b), pr in zip(keys, pairs):
                try:
                    if st.carry_file(ka, kb, new_path=b, copy=copy):
                        hit.add(pr)
                except Exception:
                    pass
        finally:
            st.close()
    except Exception:
        pass
    try:
        us = UserStore(user_db, busy_ms=dbutil.BUSY_MS_BG)
        try:
            for (ka, kb, _b), pr in zip(keys, pairs):
                try:
                    if us.carry_file(ka, kb, copy=copy):
                        hit.add(pr)
                except Exception:
                    pass
        finally:
            us.close()
    except Exception:
        pass
    try:
        if fix_store is None:
            from viewer.text_fix_store import store
            fix_store = store()
        for pr in pairs:
            try:
                if fix_store.carry_file(pr[0], pr[1], copy=copy):
                    hit.add(pr)
            except Exception:
                pass
    except Exception:
        pass
    return len(hit)


def carry_sidecars(root_store, pairs, copy: bool, inside, dest_store_for) -> list:
    """연 폴더의 사이드카(`PageMetaStore`·`HyperlinkStore` 하나)에서 그 파일의 기록을 새 경로로.

    - 둘 다 연 폴더 안: 이동은 `rename_file`, 복사는 `copy_file`
    - 새 경로가 연 폴더 밖: 기록을 떼어(`export_entry`) 그 폴더의 사이드카에 넣고(`dest_store_for(폴더)`), 이동이면 옛 키를 지운다
    바뀐 저장소 목록(쓰기는 부른 쪽이 — 저장 안 한 편집이 있으면 연 폴더 것은 쓰지 않는다)."""
    changed = []
    if root_store is None:
        return changed
    for old, new in pairs:
        try:
            if inside(new):
                ok = (root_store.copy_file(old, new) if copy else root_store.rename_file(old, new))
                if ok and root_store not in changed:
                    changed.append(root_store)
                continue
            ent = root_store.export_entry(old) if hasattr(root_store, "export_entry") else None
            if not ent:
                continue
            ds = dest_store_for(str(Path(new).parent))
            if ds is not None and ds.import_entry(new, ent) and ds not in changed:
                changed.append(ds)
            if not copy and root_store.drop_entry(old) and root_store not in changed:
                changed.append(root_store)
        except Exception:
            pass
    return changed
