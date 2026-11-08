"""261108-11(릴리스 SOT §14.2): 빌드 묶음의 exe·dll·pyd 가 UPX 로 압축되지 않았는지 본다.

UPX 로 압축된 실행 파일은 백신 휴리스틱이 악성으로 오인하기 쉽다(기획 '백신 오인·멈춤 줄이기' F2).
`build_ci.bat` 이 PyInstaller 에 `--noupx` 를 주지만, 빌드 도구·옵션이 바뀌어도 결과로 확인한다.
판정: PE 구획(section) 이름이 `UPX` 로 시작하면 압축된 것(UPX0·UPX1·UPX2 — UPX 가 쓰는 이름).

    python scripts/check_no_upx.py dist/PolyPDF      → 압축 파일이 있으면 종료 코드 1
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

EXTS = (".exe", ".dll", ".pyd")


def pe_sections(path) -> list[str]:
    """PE 파일의 구획 이름 목록. PE 가 아니면 []."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
            if head[:2] != b"MZ" or len(head) < 0x40:
                return []
            pe = struct.unpack_from("<I", head, 0x3C)[0]
            f.seek(pe)
            hdr = f.read(24)
            if len(hdr) < 24 or hdr[:4] != b"PE\0\0":
                return []
            nsec = struct.unpack_from("<H", hdr, 6)[0]
            opt = struct.unpack_from("<H", hdr, 20)[0]
            f.seek(pe + 24 + opt)
            raw = f.read(40 * min(nsec, 96))
    except (OSError, struct.error):
        return []
    return [raw[i:i + 8].rstrip(b"\0").decode("latin-1") for i in range(0, len(raw) - 39, 40)]


def is_upx(path) -> bool:
    return any(s.upper().startswith("UPX") for s in pe_sections(path))


def find_upx(root) -> list[Path]:
    root = Path(root)
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in EXTS and p.is_file() and is_upx(p))


def main(argv) -> int:
    try:                                                # 검사 작성 SOT §14.7.2 의 21 — 콘솔 코드 페이지와 무관하게
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(argv) != 2 or not Path(argv[1]).is_dir():
        print("사용법: check_no_upx.py <빌드 폴더>")
        return 2
    bad = find_upx(argv[1])
    for p in bad:
        print("UPX 압축:", p)
    n = sum(1 for p in Path(argv[1]).rglob("*") if p.suffix.lower() in EXTS)
    print("[check_no_upx] 실행 파일 %d개 중 UPX 압축 %d개" % (n, len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
