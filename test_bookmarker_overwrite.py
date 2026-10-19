# -*- coding: utf-8 -*-
"""260905(§4.4.6.1·§4.4.6.2): 책갈피 자동 생성 —
모듈 안내는 실패 때만 / 모듈 경로 칸 제거 / 261019-1: 워커는 PDF 를 쓰지 않는다(종전 덮어쓰기 규칙 대체)."""
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

# --- 2) 261019-1(마스터 §4.4.2): 워커는 PDF 를 쓰지 않는다 — 종전 '현재 PDF에 저장' 덮어쓰기 길은 없앴다 ---
#   (원본에 쓰는 것은 책갈피창 [저장] → `_finalize_save` 하나 — 잠김·서명·다른 창 규칙은 그 길이 소유한다)
from viewer.workers import BookmarkerWorker
w = BookmarkerWorker(src, {"mode": "existing", "review": False, "save_txt": False})
done, err = [], []
w.finished.connect(lambda r: done.append(r))
w.error.connect(lambda m: err.append(m))
w.run()
chk(not err and done and done[0].get("phase") == "done" and done[0].get("bookmarks") == [("old", 1, 0)],
    "워커는 책갈피 목록만 돌려준다", str(err or done))
got = fitz.open(str(src)); toc = got.get_toc(); got.close()
chk([t[1] for t in toc] == ["old"], "원본 PDF 는 그대로", str(toc))
chk(not list(tmp.glob("*.bm_tmp.pdf")) and not list(tmp.glob("*_bookmarked.pdf")), "임시·새 PDF 를 만들지 않는다")
import inspect
import viewer.workers as _vw
chk(not hasattr(BookmarkerWorker, "_overwrite_in_place") and "apply_to_pdf" not in inspect.getsource(BookmarkerWorker),
    "워커에 PDF 쓰기 코드가 없다")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
