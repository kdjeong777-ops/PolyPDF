# -*- coding: utf-8 -*-
"""사진 모드 — 색 관리(ICC → sRGB)·썸네일 캐시 용량 상한 (사진 보기 SOT §5.1 F2·D9, 261104-2).

A. 사진에 든 프로필을 화면용 sRGB 로 바꾼다 — 감마 1.0(선형) 프로필의 회색 128 은 sRGB 로 약 188(밝게) — 썸네일·본문(사진 문서) 모두
B. sRGB 프로필·프로필 없는 사진은 그대로(128)
C. 깨진 프로필은 그대로 보인다(예외 없음)
D. 같은 프로필의 변환은 한 번만 짓는다, 24 MP 사진 화면 크기 변환 비용 기록
E. 썸네일 캐시가 상한을 넘으면 오래 안 쓴 것부터 지운다(10% 여유), 쓴 것(읽을 때 시각 갱신)은 남는다
표본 프로필은 검사가 직접 짓는다(ICC v2 표시 장치 — sRGB 원색·감마 1.0) — 시스템 프로필에 기대지 않는다.
"""
import io, os, sys, struct, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def linear_icc() -> bytes:
    """ICC v2 RGB 표시 장치 프로필 — sRGB(D50 적응) 원색, TRC 감마 1.0, 설명 'Linear Test'."""
    def s15(v):
        return struct.pack(">i", int(round(v * 65536)))

    def xyz(x, y, z):
        return b"XYZ " + b"\0" * 4 + s15(x) + s15(y) + s15(z)
    desc_txt = b"Linear Test\0"
    desc = b"desc" + b"\0" * 4 + struct.pack(">I", len(desc_txt)) + desc_txt + b"\0" * 4 + b"\0" * 4 + b"\0" * 2 + b"\0" + b"\0" * 67
    curv = b"curv" + b"\0" * 4 + struct.pack(">I", 1) + struct.pack(">H", 0x0100) + b"\0\0"
    tags = [(b"desc", desc), (b"wtpt", xyz(0.9642, 1.0, 0.8249)),
            (b"rXYZ", xyz(0.4361, 0.2225, 0.0139)), (b"gXYZ", xyz(0.3851, 0.7169, 0.0971)), (b"bXYZ", xyz(0.1431, 0.0606, 0.7141)),
            (b"rTRC", curv), (b"gTRC", curv), (b"bTRC", curv)]
    off = 128 + 4 + 12 * len(tags)
    table, body = b"", b""
    for sig, data in tags:
        while (off + len(body)) % 4:
            body += b"\0"
        table += sig + struct.pack(">II", off + len(body), len(data))
        body += data
    size = off + len(body)
    header = (struct.pack(">I", size) + b"lcms" + b"\x02\x10\x00\x00" + b"mntr" + b"RGB " + b"XYZ "
              + b"\0" * 12 + b"acsp" + b"MSFT" + b"\0" * 4 + b"\0" * 4 + b"\0" * 4 + b"\0" * 8 + b"\0" * 4
              + s15(0.9642) + s15(1.0) + s15(0.8249) + b"\0" * 4 + b"\0" * 16 + b"\0" * 28)
    assert len(header) == 128, len(header)
    return header + struct.pack(">I", len(tags)) + table + body


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_color_"))
try:
    from PIL import Image, ImageCms
    from viewer import photo_io
    from viewer.photo_doc import PhotoDocument
    from viewer.widgets import photo_strip

    lin = linear_icc()
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    grey = Image.new("RGB", (64, 64), (128, 128, 128))
    p_lin = tmp / "선형.jpg"; grey.save(p_lin, quality=95, icc_profile=lin)
    p_srgb = tmp / "sRGB.jpg"; grey.save(p_srgb, quality=95, icc_profile=srgb)
    p_none = tmp / "없음.jpg"; grey.save(p_none, quality=95)
    p_bad = tmp / "깨짐.jpg"; grey.save(p_bad, quality=95, icc_profile=b"not an icc profile at all" * 4)

    def thumb_val(p):
        img, _w, _h = photo_io.read_scaled(str(p), 32, auto_transform=True)
        return img.pixelColor(16, 16).red()

    def doc_val(p):
        d = PhotoDocument(p)
        r = d.render_scaled(0, 0.5)
        d.close()
        return r.samples[(r.width * (r.height // 2) + r.width // 2) * 3]

    v_t, v_d = thumb_val(p_lin), doc_val(p_lin)
    chk(175 <= v_t <= 200 and 175 <= v_d <= 200, "A 선형 프로필 회색 128 → sRGB 약 188(썸네일·본문)", "%d %d" % (v_t, v_d))
    chk(120 <= thumb_val(p_srgb) <= 136 and 120 <= thumb_val(p_none) <= 136, "B sRGB·프로필 없음은 그대로(128)")
    v = thumb_val(p_bad)
    chk(120 <= v <= 136, "C 깨진 프로필은 그대로(예외 없음)", str(v))

    n_before = len(photo_io._CMS)
    thumb_val(p_lin); thumb_val(p_lin)
    chk(len(photo_io._CMS) == n_before, "D 같은 프로필 변환은 한 번만 짓는다")
    big = Image.new("RGB", (6000, 4000), (128, 128, 128))
    pb = tmp / "큰 선형.jpg"; big.save(pb, quality=90, icc_profile=lin)
    t0 = time.perf_counter(); photo_io.read_scaled(str(pb), 2560, auto_transform=True); t_cms = time.perf_counter() - t0
    pn = tmp / "큰 없음.jpg"; big.save(pn, quality=90)
    t0 = time.perf_counter(); photo_io.read_scaled(str(pn), 2560, auto_transform=True); t_plain = time.perf_counter() - t0
    print("     24 MP 화면 크기 줄여 읽기 — 색 관리 %.0fms · 없음 %.0fms" % (t_cms * 1000, t_plain * 1000))
    chk(t_cms < t_plain + 0.3, "D 색 관리 비용은 줄인 그림 크기만큼(0.3초 미만 더)", "%.3f vs %.3f" % (t_cms, t_plain))

    # E — 캐시 상한
    cdir = photo_strip.cache_dir(); cdir.mkdir(parents=True, exist_ok=True)
    for f in cdir.glob("*.jpg"):
        f.unlink()
    blob = b"\xff" * 10_000
    now = time.time()
    for i in range(20):
        f = cdir / ("old%02d.jpg" % i); f.write_bytes(blob); os.utime(f, (now - 1000 + i, now - 1000 + i))
    keep = cdir / "recent.jpg"; keep.write_bytes(blob)
    n = photo_strip.prune_cache(max_bytes=100_000)          # 210KB → 90KB 아래로
    left = sorted(p.name for p in cdir.glob("*.jpg"))
    chk(n > 0 and sum((cdir / x).stat().st_size for x in left) <= 90_000, "E 상한을 넘으면 지운다(10% 여유)", "%d %s" % (n, left))
    chk("recent.jpg" in left and "old00.jpg" not in left, "E 오래 안 쓴 것부터 지우고 최근 것은 남긴다")
    chk(photo_strip.prune_cache(max_bytes=100_000) == 0, "E 상한 아래면 지우지 않는다")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
