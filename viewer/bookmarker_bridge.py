"""`pdf_bookmarker` 패키지로의 브리지 (v1.6.16, v1.6.17 벤더링 추가).

뷰어 시작 시간을 늘리지 않도록 **지연 임포트**. 사용자가 메뉴를
열기 전에는 외부 모듈이 로드되지 않는다.

검색 우선순위 (v1.6.17 갱신):
  0. **벤더링된 사본 `viewer._vendor.pdf_bookmarker`** — 별도 설치 불필요
  1. 이미 import 가능한 `pdf_bookmarker` (pip 설치 / 시스템)
  2. 형제 디렉터리 `<repo>/pdf_bookmarker/` (sys.path 추가)
  3. `preferences.bookmarker_path` (파일/폴더 경로)

라이브러리 의존성(`pdfplumber`/`pypdfium2`/`pypdf`)이 없으면 import 실패 →
`is_available()=False`. 다이얼로그가 친절히 안내.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterable, Optional

_PKG_NAME = "pdf_bookmarker"
_loaded = None              # type: ignore[var-annotated]
_status_msg = ""             # 사용자에게 보일 마지막 시도 메시지


def _is_valid(m) -> bool:
    """공개 API 가 있는 '진짜' 패키지인지 검사 (namespace package 거르기)."""
    return hasattr(m, "extract_bookmarks_auto") and hasattr(m, "apply_bookmarks_to_pdf")


def _try_import() -> Optional[object]:
    """현 sys.path 에서 import 시도. 실패하거나 namespace 패키지면 None."""
    global _status_msg
    # 이전에 namespace 로 캐시된 경우 무효화
    if _PKG_NAME in sys.modules and not _is_valid(sys.modules[_PKG_NAME]):
        del sys.modules[_PKG_NAME]
    try:
        m = importlib.import_module(_PKG_NAME)
    except Exception as e:        # ImportError 또는 의존성 누락
        _status_msg = f"{type(e).__name__}: {e}"
        return None
    if not _is_valid(m):
        _status_msg = (
            f"'{_PKG_NAME}' 가 namespace package 로 로드됨 — 잘못된 경로일 가능성. "
            f"패키지의 부모(=__init__.py 가 들어있는 폴더의 상위)를 지정하세요."
        )
        # 다음 후보가 올바른 경로일 수 있도록 캐시에서 제거
        sys.modules.pop(_PKG_NAME, None)
        return None
    return m


def _sibling_repo_root() -> Path:
    """`main.py` 의 부모(=smart_pdf_viewer/)의 부모(=repo 루트)."""
    # viewer/bookmarker_bridge.py 기준: parent=viewer/, parent.parent=smart_pdf_viewer/,
    # parent.parent.parent = repo root (smart_pdf_viewer 의 형제 폴더가 여기).
    return Path(__file__).resolve().parent.parent.parent


def _candidate_paths(extra: Optional[str] = None) -> Iterable[Path]:
    """sys.path 후보 디렉터리. 다음을 차례로 yield.

    각 후보는 *그 안에 `pdf_bookmarker/__init__.py` 가 있는 디렉터리* 여야
    Python 이 정상 패키지로 임포트.  사용자가 외부 프로젝트의 **루트**
    (예: `.../MPDF`) 를 지정해도 `MPDF/pdf_bookmarker/` 가 자동으로 시도되도록
    각 입력의 자기 자신과 `<input>/pdf_bookmarker` 를 모두 후보로 둔다.
    """
    yield _sibling_repo_root() / "pdf_bookmarker"
    if extra:
        p = Path(extra).expanduser().resolve()
        base = p if p.is_dir() else p.parent
        yield base
        sub = base / "pdf_bookmarker"
        if sub.is_dir():
            yield sub


def _try_vendored() -> Optional[object]:
    """v1.6.17: viewer._vendor.pdf_bookmarker 를 'pdf_bookmarker' 로 등록 후 반환.

    내부 패키지를 별칭으로 sys.modules 에 등록하여, 외부 모듈처럼 단순
    `import pdf_bookmarker` 가 가능하도록 한다(워커·앱 코드 통일).
    """
    global _status_msg
    try:
        from viewer._vendor import pdf_bookmarker as vendored      # type: ignore
    except Exception as e:
        _status_msg = f"vendored import failed: {type(e).__name__}: {e}"
        return None
    if not _is_valid(vendored):
        _status_msg = "vendored 'pdf_bookmarker' 가 비완전 — 패키지 구조를 확인하세요."
        return None
    sys.modules[_PKG_NAME] = vendored
    return vendored


def load(bookmarker_path: Optional[str] = None):
    """패키지 로드 시도. 성공 시 모듈 반환, 실패 시 None.

    이미 로드되어 있으면 캐시 반환.
    """
    global _loaded, _status_msg
    if _loaded is not None:
        return _loaded
    _status_msg = ""

    # 0) 벤더링된 사본 (v1.6.17 — 별도 설치 없이 동작)
    m = _try_vendored()
    if m is not None:
        _loaded = m
        return m

    # 1) 이미 import 가능 (외부 설치)
    m = _try_import()
    if m is not None:
        _loaded = m
        return m

    # 2/3) 후보 경로를 sys.path 에 추가하며 재시도
    for cand in _candidate_paths(bookmarker_path):
        if not cand.exists():
            continue
        sp = str(cand)
        if sp not in sys.path:
            sys.path.insert(0, sp)
        m = _try_import()
        if m is not None:
            _loaded = m
            return m
        # 실패 시 sys.path 에 남겨도 무해 — 의존성 누락이라면 다른 경로도 같은 결과

    return None


def is_available(bookmarker_path: Optional[str] = None) -> bool:
    return load(bookmarker_path) is not None


def recheck(bookmarker_path: Optional[str] = None) -> bool:
    """캐시를 비우고 다시 로드 시도. UI가 경로 변경 후 호출."""
    global _loaded
    _loaded = None
    sys.modules.pop(_PKG_NAME, None)
    return is_available(bookmarker_path)


def get_status() -> str:
    """마지막 시도의 결과 메시지(없으면 빈 문자열)."""
    if _loaded is not None:
        return f"loaded from {getattr(_loaded, '__file__', '?')}"
    return _status_msg or "패키지를 찾지 못했습니다."


# ─── 얇은 API 래퍼 (모듈 미로드 시 RuntimeError) ─────────────────────
def _require():
    if _loaded is None:
        raise RuntimeError(
            "pdf_bookmarker 패키지가 로드되지 않았습니다. "
            "먼저 bookmarker_bridge.load() 를 호출하세요."
        )
    return _loaded


def extract_auto(pdf_path, mode: str = "auto", offset: Optional[int] = None) -> dict:
    """모드 'auto'|'toc'|'font' 로 책갈피를 추출.

    반환: {method, bookmarks, toc_pages, offset}
    """
    pb = _require()
    force = None if mode == "auto" else mode      # 'toc' or 'font'
    res = pb.extract_bookmarks_auto(str(pdf_path), force_method=force, offset=offset)
    return {
        "method": res.method,
        "bookmarks": res.bookmarks,
        "toc_pages": list(res.toc_pages or []),
        "offset": res.offset,
    }


def apply_to_pdf(input_pdf, output_pdf, bookmarks) -> Path:
    pb = _require()
    return Path(pb.apply_bookmarks_to_pdf(str(input_pdf), str(output_pdf), bookmarks))


def write_txt(bookmarks, out_path) -> Path:
    pb = _require()
    return Path(pb.write_bookmark_file(bookmarks, str(out_path)))
