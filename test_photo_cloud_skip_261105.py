# -*- coding: utf-8 -*-
"""사진을 스스로 여럿 여는 배경 워커는 클라우드에만 있는 사진을 열지 않는다 (사진 보기 SOT §4.37, 261105-20).

열면 Windows 가 그 사진을 통째로 내려받는다(사용자 결정 261105-10 '내려받지 않음'). 261105-19 점검에서 색인·날짜·지도 길은
막혀 있었는데 종류 판정(PhotoKindWorker)만 빠져, iCloud 전용 사진을 모두 내려받고 있었다.
A. 종류 판정 — 이름 행(수정 시각 0)은 판정 목록에 없다, 색인 뒤 클라우드로 비워진 사진은 열지 않는다(판정은 아직으로 남는다)
B. PC 로 받아지면 — 다음 색인 훑기가 행을 새로 쓰고 그때 판정한다
C. 정적 — 사진 모듈의 모든 워커를 분류한다: 폴더·여러 장을 스스로 여는 워커는 `cloud_only` 를 거친다, 새 워커는 분류해야 통과
"""
import os, sys, tempfile, shutil, ast
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_cloud_skip_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def jpg(path, color):
    from PIL import Image
    Image.new("RGB", (320, 240), color).save(path, "JPEG", quality=85)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_cloud_"))
try:
    from viewer import photo_io, photo_index, photo_tags
    from viewer import photo_controller as PC
    from viewer.study import ocr
    pix = tmp / "pix"
    pix.mkdir()
    L, C1, C2 = pix / "local.jpg", pix / "cloud1.jpg", pix / "cloud2.jpg"
    for p, c in ((L, (200, 30, 30)), (C1, (30, 200, 30)), (C2, (30, 30, 200))):
        jpg(p, c)

    cloud = set()                                     # 클라우드 전용으로 볼 파일 — (st_ino, st_dev)
    ident = lambda p: (os.stat(p).st_ino, os.stat(p).st_dev)
    _orig_cloud, _orig_kind, _orig_tess = photo_io.cloud_only, photo_tags.kind_tag, ocr.ensure_tesseract
    photo_io.cloud_only = lambda st: (st.st_ino, st.st_dev) in cloud
    opened = []
    photo_tags.kind_tag = lambda path, lang=None: (opened.append(Path(path).name), None)[1]
    ocr.ensure_tesseract = lambda *a, **k: {"ok": True}

    def index():
        PC.PhotoIndexWorker(str(pix), autotag=False).run()

    def kinds():
        opened.clear()
        PC.PhotoKindWorker(str(pix)).run()
        return sorted(opened)

    def todo():
        con = photo_index.connect()
        try:
            return sorted(Path(p).name for _k, p in photo_index.kind_todo(con, photo_index.norm_folder(pix), photo_tags.KIND_VER))
        finally:
            con.close()

    # A — cloud1 은 색인 때부터 클라우드(이름 행), cloud2 는 색인 뒤 클라우드로 비워짐('공간 확보')
    cloud = {ident(C1)}
    index()
    chk(todo() == ["cloud2.jpg", "local.jpg"], "A 이름 행(수정 시각 0)은 종류 판정 목록에 없다", str(todo()))
    cloud = {ident(C1), ident(C2)}
    chk(kinds() == ["local.jpg"], "A 종류 판정이 클라우드 전용 사진을 열지 않는다", str(opened))
    chk(todo() == ["cloud2.jpg"], "A 건너뛴 사진은 판정 '아직' 으로 남는다(PC 로 받아지면 판정)", str(todo()))

    # B — 본문에서 열어 PC 로 받아졌다
    cloud = set()
    index()
    chk(todo() == ["cloud1.jpg", "cloud2.jpg"], "B 받아진 뒤 다음 색인 훑기 — 이름 행이 새로 써져 판정 목록에", str(todo()))
    chk(kinds() == ["cloud1.jpg", "cloud2.jpg"], "B 그때 종류 판정", str(opened))
    photo_io.cloud_only, photo_tags.kind_tag, ocr.ensure_tesseract = _orig_cloud, _orig_kind, _orig_tess

    # C — 정적: 사진 모듈의 워커 분류. 폴더·여러 장을 스스로 여는 워커는 cloud_only 를 거친다(§4.37)
    BULK = {"PhotoIndexWorker", "PhotoKindWorker", "PhotoDateWorker", "PhotoMapWorker", "PhotoMetaRetagWorker"}
    CHOSEN = {                                         # 사용자가 고른·보는 사진 한 장(또는 고른 것)만 — 내려받는 것이 맞다
        "PhotoOrientSaveWorker", "PhotoCopyWorker", "PhotoShareWorker", "PhotoFlattenWorker", "PhotoInfoWorker",
        "PhotoOcrWorker", "PhotoPreloadWorker", "PhotoZipWorker",
        "PhotoWarpWorker", "PhotoRestoreWorker",       # 261106-6·-18: 크롭 창에서 고른 사진 펴기·고른 사진 되돌리기(261106-22 분류)
        "PhotoDeviceListWorker", "PhotoDeviceWorker", "PhotoDeviceScanWorker",   # 휴대 장치(클라우드 아님)
        "PhotoWatchScanWorker",                        # stat 만(열지 않는다)
        "RulesSaveWorker", "PhotoTextWorker",          # 사진을 열지 않는다(규칙 파일·색인 글만, 261107-10)
        "PhotoThumbWorker",                            # 보이는 칸만 — 셸 썸네일 후보는 현황 미결 위험(261105-10 보고)
    }
    root = Path(__file__).resolve().parent / "viewer"
    files = sorted(set(root.glob("photo_*.py")) | set((root / "widgets").glob("photo_*.py")) | {root / "tag_rules.py"})
    seen, missing, unknown = set(), [], []
    for f in files:
        src = f.read_text(encoding="utf-8")
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.ClassDef) and n.name.endswith("Worker"):
                seen.add(n.name)
                body = ast.get_source_segment(src, n) or ""
                if n.name in BULK:
                    if "cloud_only" not in body:
                        missing.append(n.name)
                elif n.name not in CHOSEN:
                    unknown.append("%s(%s)" % (n.name, f.name))
    chk(not missing, "C 폴더·여러 장을 여는 워커는 cloud_only 를 거친다(§4.37)", str(missing))
    chk(not unknown, "C 새 사진 워커는 이 검사의 BULK·CHOSEN 중 하나로 분류한다", str(unknown))
    chk(BULK <= seen, "C 목록의 워커가 코드에 있다", str(BULK - seen))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
