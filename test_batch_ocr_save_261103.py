# -*- coding: utf-8 -*-
"""261103-1(사용자 지시) 일괄 OCR 끝 — 저장 안내·책갈피 — 마스터 §4.4.3 B2 · 디자인 SOT §2.18.

A. 본문에 연 파일이 책갈피창 목록에 없어도: 일괄 OCR 의 책갈피를 그 파일 행을 더해 넣는다(종전: '넣을 수 없습니다' 로 버림)
B. 끝나면 주 창 가운데 확인 창 — 넣은 책갈피 수·저장 안 한 OCR, `저장` 이 기본
C. `저장` → 책갈피는 PDF 에, 보류 OCR 은 확정(종전: 파일 행이 없어 [저장] 할 곳이 없었다)
D. 저장할 것이 없으면 창 없음 · 책갈피를 못 만들었어도 보류 OCR 이 있으면 창, `나중에` 는 아무것도 저장하지 않는다
실제 경로: `_action_batch_ocr` → StudyBuildWorker → BookmarkerWorker(배경 스레드, 실제 OCR).
"""
import os, sys, tempfile, time, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "ptest261103")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

QStandardPaths.setTestModeEnabled(True)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

app = QApplication.instance() or QApplication(sys.argv)
import modal_guard
guard = modal_guard.install(label=lambda: "일괄 OCR 끝", echo=False)   # 마스터 §14.7.2 의 6 — 아래에서 필요한 답만 바꿔 끼운다
infos = []
QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
boxes = []
_press = {"which": "default"}
def _fake_exec(box):
    """모달로 기다리지 않는다(마스터 §14.7.2) — 글·기본 단추를 적고 정한 단추를 누른다."""
    boxes.append({"title": box.windowTitle(), "text": box.text(), "default": box.defaultButton().text()
                  if box.defaultButton() else None, "parent": box.parent()})
    b = box.defaultButton() if _press["which"] == "default" else box.escapeButton()
    if b is not None:
        b.click()
    return 0
QMessageBox.exec = _fake_exec
# 261107-30(텍스트 창 SOT §5.4.1): `저장` 이 'OCR 을 PDF 글자층에 넣을까요?' 도 묻는다 — 이 검사는 저장 자체를 보므로
#   [넣지 않고 저장] 으로 답한다(modal_guard 의 exec 는 아무것도 누르지 않아 창은 [취소] = 저장 안 함으로 남는다)
from viewer import ocr_layer_save as _ols
layer_asked = []
_RealDlg = _ols._dialog_cls()


class _SkipDlg(_RealDlg):
    def exec(self):
        layer_asked.append(True)
        self._pick("skip")
        return 1
_ols._dialog_cls = lambda: _SkipDlg

root = Path(tempfile.mkdtemp(prefix="polypdf_batch261103_"))
from viewer.study import study_store as ss
ss.enable_pending(True, root / "pend" / "study_pending_test.db")
import test_fixtures as _fx
pdf = root / "doc.pdf"
_s = fitz.open(_fx.scanned_pdf())
_d = fitz.open(); _d.insert_pdf(_s, from_page=0, to_page=3); _d.save(str(pdf)); _d.close(); _s.close()
other = root / "other.pdf"
shutil.copy(pdf, other)

from viewer.app import MainWindow
from viewer.history import HistoryItem
mw = MainWindow(); mw.show(); app.processEvents()
bt = mw.bookmark_tree
bt.load_pdf_files([str(other)]); app.processEvents()          # 책갈피창 목록에는 다른 파일만
mw._load_main(HistoryItem(str(pdf), 0, "", "bookmark")); app.processEvents(); QTest.qWait(300)
chk(mw.main_view.current_file() and Path(mw.main_view.current_file()).name == "doc.pdf"
    and bt._file_node_for_path(str(pdf)) is None, "준비: 본문에 doc.pdf, 책갈피창 목록에는 없음")


def wait_jobs(limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents(); QTest.qWait(200)
        if not mw._jobs_list() and time.time() - t0 > 2:
            break
    QTest.qWait(300); app.processEvents()


mw._action_batch_ocr()
wait_jobs()
node = bt._file_node_for_path(str(pdf))
if node is not None and not node.data(0, bt.DATA_TOC_LOADED):
    bt._on_item_expanded(node)
chk(not any("넣을 수 없습니다" in s for s in infos), "A1 '넣을 수 없습니다' 로 버리지 않는다", f"{infos}")
chk(node is not None and node.childCount() > 0, "A2 그 파일 행을 더해 책갈피를 넣었다",
    f"children={node.childCount() if node else None}")
chk(len(boxes) == 1 and boxes[0]["title"] == "일괄 OCR" and boxes[0]["parent"] is mw,
    "B1 끝나면 주 창 가운데 확인 창 하나(상태 표시줄 한 줄이 아니라)", f"{[(b['title'], b['parent']) for b in boxes]}")
txt = boxes[0]["text"] if boxes else ""
chk("doc.pdf" in txt and "책갈피" in txt and "OCR" in txt, "B2 파일 이름·넣은 책갈피·저장 안 한 OCR 을 알린다", repr(txt))
chk(boxes and boxes[0]["default"] == "저장", "B3 `저장` 이 기본 단추(디자인 SOT §2.7 예외)", f"{boxes[0]['default'] if boxes else None}")

# C. `저장` 을 눌렀다 — 표준 저장(배경)이 끝나기를 기다린다
t0 = time.time()
while time.time() - t0 < 60:
    app.processEvents(); QTest.qWait(100)
    if not bt._dirty and not mw._jobs_list():
        break
QTest.qWait(800); app.processEvents()
_d = fitz.open(str(pdf)); toc = _d.get_toc(); _d.close()
chk(len(toc) == (node.childCount() if node else -1) and not bt._dirty, "C1 `저장` → 책갈피가 PDF 에",
    f"toc={len(toc)} dirty={bt._dirty}")
st = ss.StudyStore()
left = ss.file_key_for(str(pdf)) in st.pending_keys()
st.close()
chk(not left, "C2 `저장` → 보류 OCR 도 확정")
chk(layer_asked, "C3 `저장` 이 OCR 글자층 창도 거친다(일괄 OCR 뒤 글자층 없는 쪽 — 261107-30)")

# D. 저장할 것이 없으면 창 없음 / 책갈피 없이 보류 OCR 만 — `나중에` 는 아무것도 저장하지 않는다
boxes.clear(); infos.clear()
mw._batch_ocr_finished(pdf, bt, 0, "", False); app.processEvents()
chk(not boxes and not infos, "D1 저장할 것이 없으면 창을 띄우지 않는다")
st = ss.StudyStore()
fk = ss.file_key_for(str(pdf))
st.save_page(fk, 0, "보류 글", dpi=300, engine="t", source="ocr", conf=1, words=[], lang="kor")
st.close()
_press["which"] = "escape"
mw._batch_ocr_finished(pdf, bt, 0, "만들 책갈피를 찾지 못했습니다.", True); app.processEvents(); QTest.qWait(300)
chk(len(boxes) == 1 and "찾지 못했습니다" in boxes[0]["text"], "D2 책갈피를 못 만들어도 보류 OCR 이 있으면 창 + 까닭",
    f"{[b['text'] for b in boxes]}")
st = ss.StudyStore()
chk(fk in st.pending_keys(), "D3 `나중에`(Esc) → 아무것도 저장하지 않는다")
st.close()
_press["which"] = "default"
mw._batch_ocr_finished(pdf, bt, 0, "만들 책갈피를 찾지 못했습니다.", True); app.processEvents()
for _ in range(50):
    app.processEvents(); QTest.qWait(50)
st = ss.StudyStore()
chk(fk not in st.pending_keys(), "D4 책갈피 없이 `저장` → 보류 OCR 만 확정")
st.close()

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
