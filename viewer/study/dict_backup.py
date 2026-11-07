"""사전 백업·복원 — dict.db·user_dict.db·dict_images/ 를 zip 으로 주고받는다(단어장 SOT §10).

**배경 스레드에서 부른다**(`StudyMixin._action_backup_dict`/`_action_restore_dict` → `_file_op_bg`, 응답성 SOT §5) —
사전이 크면(실제 26MB·13,000여 항목 + 그림) zip 압축·DB 복사가 메인을 세운다.
DB 는 파일을 통째로 복사·덮어쓰지 않고 SQLite 백업 API(`Connection.backup`)로 — 다른 연결이 열려 있으면
파일 복사 백업은 WAL 의 최근 변경을 빠뜨리고, 덮어쓰기 복원은 다시 열 때 남은 WAL 이 되감겨 사라진다(261107-13).
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path


def _copy_db(src_path, dst_path) -> None:
    from viewer import dbutil as _dbutil             # 표준 연결(응답성 SOT §4 ⑤) — 배경 대기 상한
    src = _dbutil.connect(Path(src_path), _dbutil.BUSY_MS_BG)
    dst = _dbutil.connect(Path(dst_path), _dbutil.BUSY_MS_BG)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def backup_to(out, db_path: Path, images_dir: Path) -> None:
    """dict.db·user_dict.db(있으면)·그림을 zip 하나로."""
    db_path = Path(db_path)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z, tempfile.TemporaryDirectory() as td:
        for p, name in ((db_path, "dict.db"), (db_path.parent / "user_dict.db", "user_dict.db")):   # 261019-5: 사용자 뜻도
            if p.exists():
                tmp = Path(td) / name
                _copy_db(p, tmp)
                z.write(str(tmp), name)
        for f in Path(images_dir).glob("*"):
            if f.is_file():
                z.write(str(f), f"dict_images/{f.name}")


def restore_from(fn, db_path: Path, images_dir: Path) -> None:
    """백업 zip 으로 바꾼다 — 지금 것은 `.bak`. 사용자 뜻 파일이 없는 옛 백업이면 사용자 뜻은 그대로
    (옛 백업의 dict.db 안 사용자 항목은 다음에 열 때 겹치지 않게 더해진다 — `DictStore._attach_user`)."""
    db_path = Path(db_path)
    udb = db_path.parent / "user_dict.db"
    with zipfile.ZipFile(fn, "r") as z, tempfile.TemporaryDirectory() as td:
        names = z.namelist()
        for name, dst in (("dict.db", db_path), ("user_dict.db", udb)):
            if name in names:
                if dst.exists():
                    _copy_db(dst, str(dst) + ".bak")
                _copy_db(z.extract(name, td), dst)
        for nm in names:
            if nm.startswith("dict_images/") and not nm.endswith("/"):
                with z.open(nm) as src, open(Path(images_dir) / Path(nm).name, "wb") as out:
                    shutil.copyfileobj(src, out)
