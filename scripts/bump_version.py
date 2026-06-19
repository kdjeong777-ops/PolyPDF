"""260618-13: viewer/__init__.py 의 __version__ 을 인자값으로 변경(UTF-8 보존).
사용: python scripts/bump_version.py 2.26.0
"""
import io
import os
import re
import sys

def main() -> int:
    if len(sys.argv) != 2 or not re.match(r"^\d+\.\d+\.\d+$", sys.argv[1]):
        print("사용법: python scripts/bump_version.py X.Y.Z (예: 2.26.0)", file=sys.stderr)
        return 2
    ver = sys.argv[1]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # smart_pdf_viewer
    path = os.path.join(root, "viewer", "__init__.py")
    s = io.open(path, encoding="utf-8").read()
    s2, n = re.subn(r'__version__\s*=\s*"[^"]*"',
                    '__version__ = "%s"' % ver, s, count=1)
    if n != 1:
        print("오류: __version__ 라인을 찾지 못했습니다.", file=sys.stderr)
        return 1
    io.open(path, "w", encoding="utf-8", newline="").write(s2)
    print("버전 → %s" % ver)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
