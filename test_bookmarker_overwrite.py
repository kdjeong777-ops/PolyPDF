# -*- coding: utf-8 -*-
"""260905(§4.4.6.1·§4.4.6.2): 책갈피 자동 생성 —
모듈 안내는 실패 때만 / 모듈 경로 칸 제거 / '현재 PDF에 저장' 덮어쓰기 안전 규칙."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication, QLabel

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

app = QApplication.instance() or QApplication(sys.argv)

# --- 1) 다이얼로그: 성공 시 안내 없음 / 모듈 경로 칸 없음 ---
from viewer.widgets.bookmarker_dialog import BookmarkerDialog
tmp = Path(tempfile.mkdtemp(prefix="polypdf_bm_"))
src = tmp / "BM.pdf"
d = fitz.open()
for i in range(6):
    d.new_page(width=400, height=600).insert_text((40, 100), f"page {i+1}")
d.set_toc([[1, "old", 1]])
d.save(str(src)); d.close()

dlg = BookmarkerDialog(default_pdf=src, prefs={})
chk(not hasattr(dlg, "edit_path"), "'모듈 경로(선택)' 입력칸 제거")
chk(not hasattr(dlg, "_browse_pkg"), "모듈 경로 찾아보기 핸들러 제거")
chk(not dlg.warn.isVisibleTo(dlg) and not dlg.warn.text(),
    "모듈 로드 성공 시 안내 없음", repr(dlg.warn.text()))
labels = [w.text() for w in dlg.findChildren(QLabel)]
chk(not any("내장" in t and "pdf_bookmarker" in t for t in labels),
    "'내장 pdf_bookmarker 라이브러리' 안내 문구 제거")
chk(not any("로드 완료" in t for t in labels), "'모듈 로드 완료' 상자 제거")
opts = dlg.result_options()
chk("bookmarker_path" not in opts, "result_options 에 bookmarker_path 없음", str(sorted(opts)))

# 로드 실패로 위장하면 안내가 보인다
from viewer import bookmarker_bridge as bridge
_orig_recheck, _orig_status = bridge.recheck, bridge.get_status
bridge.recheck = lambda p=None: False
bridge.get_status = lambda: "not found: pdfplumber"
dlg2 = BookmarkerDialog(default_pdf=src, prefs={})
chk(dlg2.warn.isVisibleTo(dlg2), "로드 실패 시에만 안내 표시")
chk("pdfplumber" in dlg2.warn.text() and "requirements.txt" in dlg2.warn.text(),
    "실패 안내에 원인·설치 방법 포함")
chk(not dlg2._ok_btn.isEnabled(), "로드 실패면 확인 버튼 비활성")
bridge.recheck, bridge.get_status = _orig_recheck, _orig_status
dlg.close(); dlg2.close()

# --- 2) 덮어쓰기: 정상 / 점유 중 / 임시 파일 정리 ---
from viewer.workers import BookmarkerWorker
import pdf_bookmarker as pb
bms = [("1장", 1, 0), ("1.1 절", 2, 1), ("2장", 4, 0)]
w = BookmarkerWorker(src, {"bookmarks": bms, "review": False, "overwrite": True,
                           "save_pdf": True, "save_txt": False, "method": "toc"})
done, err = [], []
w.finished.connect(lambda r: done.append(r))
w.error.connect(lambda m: err.append(m))
w.run()
chk(not err and done and done[0]["count"] == 3, "덮어쓰기 정상 저장", str(err or done))
got = fitz.open(str(src)); toc = got.get_toc(); got.close()
chk([t[1] for t in toc] == ["1장", "1.1 절", "2장"], "원본에 새 책갈피 반영", str(toc))
chk(not (src.with_name(src.stem + ".bm_tmp.pdf")).exists(), "임시 파일 남지 않음")

# 다른 곳에서 연 상태 → 정직한 오류 + 임시 파일 정리 + 원본 보존
held = fitz.open(str(src))
w2 = BookmarkerWorker(src, {"bookmarks": [("바뀐제목", 1, 0)], "review": False,
                            "overwrite": True, "save_pdf": True, "save_txt": False})
done2, err2 = [], []
w2.finished.connect(lambda r: done2.append(r))
w2.error.connect(lambda m: err2.append(m))
w2.run()
held.close()
chk(bool(err2), "점유 중이면 오류로 알림", str(err2))
if err2:
    chk("다른 프로그램이 열고 있어" in err2[0] and "새 PDF로 저장" in err2[0],
        "오류 문구가 원인·조치를 알려 줌", err2[0].splitlines()[0])
    chk("원본은 그대로" in err2[0], "원본이 보존됨을 알림")
chk(not (src.with_name(src.stem + ".bm_tmp.pdf")).exists(),
    "실패해도 임시 파일 남지 않음")
got = fitz.open(str(src)); toc2 = got.get_toc(); got.close()
chk([t[1] for t in toc2] == ["1장", "1.1 절", "2장"], "실패 시 원본 그대로", str(toc2))

# 지난 실패의 잔재가 있어도 정상 진행
stale = src.with_name(src.stem + ".bm_tmp.pdf")
stale.write_bytes(b"garbage")
w3 = BookmarkerWorker(src, {"bookmarks": bms, "review": False, "overwrite": True,
                            "save_pdf": True, "save_txt": False})
done3, err3 = [], []
w3.finished.connect(lambda r: done3.append(r))
w3.error.connect(lambda m: err3.append(m))
w3.run()
chk(not err3 and not stale.exists(), "남아 있던 임시 파일을 정리하고 진행", str(err3))

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
