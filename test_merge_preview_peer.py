# -*- coding: utf-8 -*-
"""260915-2: PDF 병합 선택·미리보기·병합 후 표시 / 다른 PolyPDF 창이 연 PDF 저장 (마스터 §4.8·§4.7.8).

사용자 지시
  "책갈피창에서 파일을 다중 선택하여 병합 실행시 병합화면에서 해당 파일을 우측리스트에 포함"
  "우측리스트 오른쪽에 파일 미리보기 … 좌측/우측 리스트에서 파일 1개가 선택되면 그 파일"
  "병합 후 책갈피창의 폴더와 동일한 폴더에 저장될 경우, 폴더를 리프레쉬하고, 새로 만든 파일을 선택"
  "동일 pdf가 다른 polypdf 창으로 보여주고 있어 … 설명하고, 다른 창에서 읽는 상태에서 제거하고 저장"

다른 창은 **진짜 다른 프로세스**로 띄운다(같은 프로세스면 서로의 응답을 기다리다 막힌다).
"""
import os, sys, json, time, subprocess, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
faulthandler.dump_traceback_later(360, exit=True)   # 모달 창에 막히면 멈춰 있지 말고 위치를 남기고 끝낸다
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
app.setApplicationName("PolyPDF-test-peer")       # 두 프로세스가 같은 등록 폴더를 보게


def make_pdf(p, n=6, tag=None):
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((72, 72), f"{tag or p.stem} PAGE {i + 1}")
    d.set_toc([[1, "one", 1]])
    d.save(str(p)); d.close()


def spin(n=10, ms=30):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


# ─────────────────────────── 다른 창(피어) 프로세스 ───────────────────────────
if len(sys.argv) >= 4 and sys.argv[1] == "--peer":
    src, state, mode = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1200, 800); mw.show(); app.processEvents()
    mw.open_folder(src.parent); spin(15)
    mw._load_main(HistoryItem(str(src), 3, "", "bookmark")); spin(10)
    if mode == "dirty":
        if not mw._in_edit():
            mw.bookmark_tree.btn_edit.setChecked(True); spin(4)
        pt = mw.page_thumbs
        pt.list.clearSelection(); pt.list.item(0).setSelected(True); pt._delete_selected(); spin(4)

    def dump():
        mv = mw.main_view
        st = {"ready": mw._instance_link is not None, "file": mv.current_file() and str(mv.current_file()),
              "page": mv.current_page() if mv._doc is not None else None,
              "doc_open": mv._doc is not None}
        if mv._doc is not None:
            st["pages"] = mv._doc.page_count
        state.write_text(json.dumps(st), encoding="utf-8")
        if (state.parent / "STOP").exists():
            os._exit(0)
    t = QTimer(); t.timeout.connect(dump); t.start(150)
    QTimer.singleShot(120_000, lambda: os._exit(0))
    app.exec()
    os._exit(0)

# ─────────────────────────── 검사 본체 ───────────────────────────
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = Path(tempfile.mkdtemp(prefix="polypdf_merge_peer_"))
peers = []
try:
    for nm in ("A", "B", "C"):
        make_pdf(root / f"{nm}.pdf")
    (root / "sub").mkdir()
    make_pdf(root / "sub" / "D.pdf", 3)
    msgs = []
    QMessageBox.warning = staticmethod(lambda *a, **k: msgs.append(("w", a[2])))
    QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(("i", a[2])))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    from viewer.widgets import merge_dialog as md
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    bt = mw.bookmark_tree
    mw.open_folder(root); spin(30)

    def node_of(p):
        for n in bt._iter_file_nodes():
            if Path(str(n.data(0, bt.DATA_FILE))).resolve() == Path(p).resolve():
                return n

    # ── 1. 책갈피창 다중 선택 → 병합창 오른쪽 목록 ─────────────────────────
    if not mw._in_edit():
        bt.btn_edit.setChecked(True); spin(4)
    bt.tree.clearSelection()
    for nm in ("A", "C"):
        node_of(root / f"{nm}.pdf").setSelected(True)
    seen = {}
    real_exec = md.MergeFilesDialog.exec

    def fake_exec(self):
        seen["right"] = [Path(d["path"]).name for d in self.result_items()]
        return md.QDialog.DialogCode.Rejected
    md.MergeFilesDialog.exec = fake_exec
    try:
        mw._on_merge_files(None)                   # 도구 모음·메뉴의 'PDF병합' 경로
    finally:
        md.MergeFilesDialog.exec = real_exec
    chk(sorted(seen.get("right") or []) == ["A.pdf", "C.pdf"], "1 도구 모음 'PDF병합' 도 책갈피창에서 고른 파일을 **오른쪽 목록에** 넣는다",
        str(seen))
    bt.btn_edit.setChecked(False); spin(4)

    # ── 2. 미리보기 ─────────────────────────────────────────────────
    dlg = md.MergeFilesDialog([str(root / "A.pdf"), str(root / "B.pdf")], [str(root / "C.pdf")],
                              [], mw)
    dlg.resize(1100, 600); dlg.show(); spin(5)
    pv = dlg.preview
    dlg.left.item(1).setSelected(True); spin(3)
    chk(pv.lbl_title.text() == "B.pdf" and pv.lbl_page.text() == "1 / 6" and not pv.canvas.pixmap().isNull(),
        "2 왼쪽 목록에서 하나 고르면 그 파일 첫 쪽이 보인다", "%s %s" % (pv.lbl_title.text(), pv.lbl_page.text()))
    pv.step(+1); spin(2)
    chk(pv.lbl_page.text() == "2 / 6" and pv.btn_prev.isEnabled(), "2 ▶ 로 쪽을 넘긴다", pv.lbl_page.text())
    dlg.left.item(0).setSelected(True); spin(3)
    chk(pv._doc is None and "2개" in pv.canvas.text(), "2 둘을 고르면 미리보기 대신 안내(문서는 닫는다)",
        pv.canvas.text())
    dlg.right.item(0).setSelected(True); spin(3)
    chk(pv.lbl_title.text() == "C.pdf", "2 오른쪽 목록에서 하나 고르면 **오른쪽 파일**이 보인다", pv.lbl_title.text())
    chk(len(dlg.left.selectedItems()) == 2, "2 왼쪽 선택은 그대로 둔다('→' 등록이 계속 된다)")
    dlg.left.clearSelection(); dlg.left.item(0).setSelected(True); spin(3)
    chk(pv.lbl_title.text() == "A.pdf", "2 다시 왼쪽을 고르면 왼쪽 파일", pv.lbl_title.text())
    shot = root / "shot.png"
    from PyQt6.QtGui import QImage, QColor
    im = QImage(120, 80, QImage.Format.Format_RGB32); im.fill(QColor("red")); im.save(str(shot))
    dlg._screenshot_paths = [str(shot), str(shot)]
    dlg._add_screenshots()
    dlg.right.clearSelection(); dlg.right.item(dlg.right.count() - 1).setSelected(True); spin(3)
    chk(pv.lbl_page.text() == "1 / 2" and not pv.canvas.pixmap().isNull(), "2 스크린샷 묶음도 차례로 보인다",
        pv.lbl_page.text())
    dlg.right.clearSelection(); dlg.right.item(0).setSelected(True); spin(3)
    chk(pv._doc is not None, "준비 — 미리보기 문서가 열려 있다")
    dlg.reject(); spin(2)
    chk(pv._doc is None, "2 병합창을 닫으면 미리보기 문서도 닫는다(원본 저장을 막지 않게)")

    # ── 3. 병합 후 — 책갈피창 폴더(하위 포함)면 새로 읽고 새 파일 선택·표시, 완료창 없음 ──
    after_calls = []
    mw._after_pdf_created = lambda p: after_calls.append(p)

    def run_merge(out_path):
        def fake_exec2(self):
            for i in range(self.left.count()):
                self.left.item(i).setSelected(Path(self.left.item(i).data(self._DATA)).stem in ("A", "B"))
            self._move_selected()
            self.chk_auto.setChecked(False)
            return md.QDialog.DialogCode.Accepted
        from PyQt6.QtWidgets import QFileDialog
        real_save = QFileDialog.getSaveFileName
        md.MergeFilesDialog.exec = fake_exec2
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out_path), "PDF (*.pdf)"))
        try:
            mw._on_merge_files(None)
        finally:
            md.MergeFilesDialog.exec = real_exec
            QFileDialog.getSaveFileName = real_save
        for _ in range(200):
            spin(1, 30)
            if Path(out_path).exists() and mw.main_view.current_file() \
                    and Path(mw.main_view.current_file()).resolve() == Path(out_path).resolve():
                break
        spin(10)

    bt.tree.clearSelection()
    out1 = root / "AB_merged.pdf"
    run_merge(out1)
    cur = bt.tree.currentItem()
    chk(out1.exists() and node_of(out1) is not None, "3 같은 폴더 — 폴더를 다시 읽어 새 파일이 목록에 있다")
    chk(cur is not None and bt._file_node_of(cur) is node_of(out1), "3 새 파일이 **선택**돼 있다",
        cur.text(0) if cur else "")
    chk(Path(mw.main_view.current_file()).name == "AB_merged.pdf", "3 본문에 새 파일이 열린다")
    chk(after_calls == [], "3 완료창('새 창으로 열기' 등)은 띄우지 않는다", str(after_calls))
    out2 = root / "sub" / "AB_sub.pdf"
    run_merge(out2)
    chk(Path(mw.main_view.current_file()).name == "AB_sub.pdf" and after_calls == [],
        "3 하위 폴더도 같은 동작", str(after_calls))
    other = Path(tempfile.mkdtemp(prefix="polypdf_merge_out_")) / "X.pdf"
    run_merge(other); spin(10)
    chk(after_calls == [str(other)], "3 다른 폴더면 종전대로 완료창", str(after_calls))
    shutil.rmtree(other.parent, ignore_errors=True)

    # ── 4. 다른 PolyPDF 창이 같은 PDF 를 열고 있을 때 저장 ─────────────────
    src = root / "B.pdf"

    def start_peer(mode):
        st = root / f"peer_{mode}.json"
        st.unlink(missing_ok=True)
        pr = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--peer", str(src), str(st), mode],
                              cwd=os.path.dirname(os.path.abspath(__file__)))
        peers.append(pr)
        for _ in range(600):
            time.sleep(0.1)
            try:
                s = json.loads(st.read_text(encoding="utf-8"))
                if s.get("doc_open"):
                    return pr, st
            except Exception:
                pass
        return pr, st

    def peer_state(st):
        try:
            return json.loads(st.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def edit_and_save(answer):
        asked = []
        mw._ask_peer_release = lambda name, holders: (asked.append((name, holders)), answer)[1]
        mw._load_main(HistoryItem(str(src), 0, "", "bookmark")); spin(10)
        if not mw._in_edit():
            bt.btn_edit.setChecked(True); spin(4)
        pt = mw.page_thumbs
        pt.list.clearSelection(); pt.list.item(1).setSelected(True); pt._delete_selected(); spin(3)
        bt.tree.setCurrentItem(node_of(src)); spin(2)
        msgs.clear()
        bt._op_save(); spin(15)
        return asked

    def pages(p):
        d = fitz.open(str(p)); n = d.page_count; d.close(); return n

    pr, st = start_peer("clean")
    chk(peer_state(st).get("doc_open") and peer_state(st).get("page") == 3, "준비 — 다른 창이 B.pdf 4쪽을 보고 있다",
        str(peer_state(st)))
    n0 = pages(src)
    asked = edit_and_save("cancel")
    chk(asked and asked[0][0] == "B.pdf" and len(asked[0][1]) == 1 and not asked[0][1][0]["dirty"],
        "4 저장 전에 **다른 창이 열고 있음을 알아채고** 묻는다", str(asked))
    chk(pages(src) == n0 and not [m for t, m in msgs if t == "w"] and mw._page_edits_dirty(),
        "4 [취소] — 원본 그대로, 오류창 없음, 편집은 남는다", str(msgs))
    chk(not list(root.glob("*_recon_tmp.pdf")) and not list(root.glob("*_book_tmp.pdf")), "4 취소해도 임시 파일이 남지 않는다")
    bt.tree.setCurrentItem(node_of(src)); spin(2)
    mw._ask_peer_release = lambda name, holders: "release"
    bt._op_save()
    for _ in range(100):
        time.sleep(0.1); spin(1, 10)
        s = peer_state(st)
        if s.get("doc_open") and s.get("pages") == n0 - 1:
            break
    s = peer_state(st)
    chk(pages(src) == n0 - 1 and not (root / "B_edited.pdf").exists(), "4 [닫고 저장] — **원본에** 저장된다",
        str(pages(src)))
    chk(s.get("doc_open") and s.get("pages") == n0 - 1 and s.get("page") == 3,
        "4 다른 창은 저장된 파일을 **보던 쪽으로 다시 연다**", str(s))
    (root / "STOP").write_text("1"); pr.wait(15); (root / "STOP").unlink()

    pr2, st2 = start_peer("dirty")
    n1 = pages(src)
    asked = edit_and_save("rename")
    chk(asked and asked[0][1] and asked[0][1][0]["dirty"], "4 다른 창에 저장 안 한 편집이 있으면 그렇게 알린다", str(asked))
    chk((root / "B_edited.pdf").exists() and pages(src) == n1, "4 [새 이름으로 저장] — 원본·그 창 편집은 그대로",
        str(sorted(p.name for p in root.glob('*.pdf'))))
    chk(peer_state(st2).get("doc_open"), "4 그 창은 파일을 계속 보고 있다(놓게 하지 않았다)")
    chk(Path(mw.main_view.current_file()).name == "B_edited.pdf", "4 이 창은 새 파일로 옮긴다(§4.7.5)")
    (root / "STOP").write_text("1"); pr2.wait(15)
finally:
    for pr in peers:
        try:
            if pr.poll() is None:
                pr.kill()
        except Exception:
            pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
