# -*- coding: utf-8 -*-
"""문서 정보 배경 읽기(`doc_info.read_info`)가 쪽 수만큼 메모리를 쌓지 않는다 (261108-8, 응답성 SOT §9.2).

beta.6 설치 시험에서 PDF 를 연 직후 최대 작업 집합이 T2(스캔본 490쪽) 347 → 576 MB 로 늘었다 — 정보 줄의
`DocInfoWorker` 가 모든 쪽의 글자층을 판정하는 동안 MuPDF 저장소에 쪽마다 그림 스트림이 남고, 문서를 닫을 때야
놓였다. 고친 뒤: `REOPEN_PAGES` 쪽마다 자기 문서를 닫고 다시 연다.

M. 쪽마다 다른 그림(압축 안 되는 노이즈)이 든 PDF — 읽는 동안 전용 메모리 최대 증가 < 그림 합계의 40 %
   (수정 전: 그림 합계만큼 ≈ 100 %)
R. 다시 열어도 결과는 같다 — 쪽 수·글자층 없는 쪽 수가 다시 열지 않을 때와 같다
P. 암호 걸린 PDF 도 다시 열 때 암호로 다시 풀어 끝까지 센다
C. 취소하면 캐시에 넣지 않는다(종전 규칙 그대로)
"""
import ctypes, ctypes.wintypes as wt, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"          # 검사 작성 SOT §14.7 — Qt 를 들이는 검사는 모두 오프스크린
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)             # 검사 작성 SOT §14.7.2 의 3

import fitz
from viewer import doc_info

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]


_H = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0010, False, os.getpid())


def private_mb() -> float:
    m = _PMC(); m.cb = ctypes.sizeof(_PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(_H, ctypes.byref(m), m.cb)
    return m.PrivateUsage / 1048576.0


PAGES, SIDE = 160, 512                               # 쪽마다 512×512 회색 노이즈 = 0.25 MB, 합계 40 MB
IMG_MB = PAGES * SIDE * SIDE / 1048576.0
tmp = tempfile.mkdtemp(prefix="polypdf_docinfo_mem_")


def build(path, pw=None):
    out = fitz.open()
    for i in range(PAGES):
        p = out.new_page(width=300, height=300)
        p.insert_image(p.rect, pixmap=fitz.Pixmap(fitz.csGRAY, SIDE, SIDE, os.urandom(SIDE * SIDE), False))
    if pw:
        out.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=pw, owner_pw=pw + "o")
    else:
        out.save(path)
    out.close()


def read(path, pw=None, cancelled=lambda: False):
    with doc_info._LOCK:
        doc_info._CACHE.clear()
    base = private_mb()
    peak = [base]
    info = doc_info.read_info(path, pw, cancelled=cancelled, pace=lambda: peak.append(private_mb()))
    return info, max(peak) - base


plain = os.path.join(tmp, "noise.pdf")
build(plain)
read(plain)                                           # 첫 읽기의 일회성 할당(모듈·글꼴)을 빼고 잰다

# M
info, grow = read(plain)
chk(info.get("pages_checked") == PAGES, "M 모든 쪽을 읽었다", str(info.get("pages_checked")))
chk(grow < IMG_MB * 0.4, "M 읽는 동안 전용 메모리 증가 < 그림 합계의 40%%(%.0f MB)" % (IMG_MB * 0.4),
    "증가 %.1f MB" % grow)
print("     증가 %.1f MB / 그림 합계 %.0f MB" % (grow, IMG_MB))

# R
keep = getattr(doc_info, "REOPEN_PAGES", None)
try:
    doc_info.REOPEN_PAGES = 10 ** 9
    ref, _ = read(plain)
finally:
    if keep is not None:
        doc_info.REOPEN_PAGES = keep
for k in ("pages_checked", "pages_no_text", "pages_ocr_layer"):
    chk(info.get(k) == ref.get(k), "R %s 같다" % k, "%s vs %s" % (info.get(k), ref.get(k)))

# P
enc = os.path.join(tmp, "noise_pw.pdf")
build(enc, "pw1234")
pinfo, _ = read(enc, "pw1234")
chk(pinfo.get("encrypted") is True, "P 암호 PDF 로 알아본다")
chk(pinfo.get("pages_checked") == PAGES, "P 다시 열 때 암호로 풀어 끝까지 센다", str(pinfo.get("pages_checked")))

# C
calls = [0]


def _cancel_late():
    calls[0] += 1
    return calls[0] > PAGES // 2


cinfo, _ = read(plain, cancelled=_cancel_late)
chk("pages_checked" not in cinfo, "C 취소하면 쪽 수를 내지 않는다")
chk(doc_info.cached(plain) is None, "C 취소한 결과는 캐시에 없다")

print()
print("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
