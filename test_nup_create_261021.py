# -*- coding: utf-8 -*-
"""261021-3: 도구 '다단 생성' — 파일 하나, 1단 배치, 여러 파일 항목 제외 (마스터 §11.10.2 · 디자인 SOT §2.9.1).

A. 도구 메뉴 '다단 생성...' 은 'PDF 병합...' 바로 아래
B. `TwoUpSettingsDialog(single=True)` — 제목, 간지·문서마다 새 쪽·홀수 시작 숨김, 숨긴 값은 그대로(스타일 저장에 보존), '1장 (1-up)'
C. 1-up — 세로 쪽은 세로 용지, 가로 쪽은 가로 용지, 쪽 하나에 시트 하나
D. 파일 하나 다단 — 목차는 책갈피 1단계(본문 번호), 책갈피는 원본 단계 그대로(파일 이름 단계 없음),
   간지·문서 나눔이 켜진 스타일이어도 끈다(`single_file_settings`)
E. 미리보기도 같은 목차(책갈피 1단계)
F. 앱 경로 — 새 파일 `<원본>_nup.pdf`, 원본 그대로, 저장 안 한 편집이 있으면 만들지 않음
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog, QFileDialog

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_nupcreate261021_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


root = Path(tempfile.mkdtemp(prefix="nupcreate261021_"))
try:
    folder = root / "f"; folder.mkdir()
    src = folder / "doc.pdf"
    d = fitz.open()
    for i in range(6):
        w, h = (842, 595) if i == 5 else (595, 842)
        d.new_page(width=w, height=h).insert_text((72, 300), "PAGE %d" % (i + 1))
    d.set_toc([[1, "Chapter A", 1], [2, "Sec A1", 2], [1, "Chapter B", 4], [2, "Sec B1", 5]])
    d.save(str(src)); d.close()

    from viewer.twoup import build_twoup, single_file_settings, merge_twoup_settings
    from viewer.widgets.twoup_dialog import TwoUpSettingsDialog
    ITEM = [{"type": "pdf", "path": str(src), "name": "doc"}]

    # B — 설정 창
    presets = []
    api = {"get_presets": lambda: list(presets),
           "save_preset": lambda name, cfg: presets.append(dict(cfg, name=name))}
    dlg = TwoUpSettingsDialog({"make_divider": True, "doc_break": True, "make_cover": False, "make_toc": False},
                              None, preset_api=api, sample=str(src), single=True)
    dlg.show(); spin(0.3)
    chk(dlg.windowTitle() == "다단 생성", "B1 제목 '다단 생성'", dlg.windowTitle())
    chk(not dlg.grp_divider.isVisible() and not dlg.chk_docbreak.isVisible() and not dlg.chk_doc_odd.isVisible(),
        "B2 간지·문서마다 새 쪽·홀수 시작은 숨긴다")
    chk(dlg.chk_toc.text() == "목차 만들기 (책갈피 1단계)", "B3 목차 체크 이름", dlg.chk_toc.text())
    g = dlg.get_settings()
    chk(g.get("make_divider") is True and g.get("doc_break") is True and "single_file" not in g,
        "B4 숨긴 칸의 값은 그대로(스타일 저장에 병합용 설정이 남는다), single_file 은 스타일에 안 들어감", str(g.get("make_divider")))
    chk(dlg.cmb_nup.itemData(0) == 1 and dlg.cmb_nup.itemText(0) == "1장 (1-up)", "B5 '1장 (1-up)' 이 첫 항목")
    b_base = dlg.preview._base
    chk(b_base.get("single_file") is True and b_base.get("make_divider") is False, "B6 미리보기는 파일 하나 값으로 그린다")
    dlg.close(); spin(0.1)
    dlg2 = TwoUpSettingsDialog({}, None, preset_api=api, sample=str(src))
    chk(dlg2.windowTitle() == "다단 생성 설정" and not dlg2.grp_divider.isHidden(), "B7 병합·인쇄 쪽 창은 종전 그대로")
    dlg2.close()

    # C — 1-up
    out1 = str(root / "one.pdf")
    build_twoup(ITEM, single_file_settings({"nup": 1, "make_cover": False, "make_toc": False}), out1)
    o = fitz.open(out1)
    sizes = [(round(p.rect.width), round(p.rect.height)) for p in o]
    chk(o.page_count == 6, "C1 1-up — 쪽 하나에 시트 하나", str(o.page_count))
    chk(sizes[0][0] < sizes[0][1] and sizes[5][0] > sizes[5][1], "C2 세로 쪽은 세로 용지, 가로 쪽은 가로 용지", str(sizes))
    o.close()

    # D — 목차·책갈피·간지 끔
    out2 = str(root / "two.pdf")
    build_twoup(ITEM, single_file_settings({"nup": 2, "make_cover": False, "make_toc": True,
                                            "make_divider": True, "doc_break": True}), out2)
    o = fitz.open(out2)
    toc_txt = o[0].get_text("text")
    chk("Chapter A" in toc_txt and "Chapter B" in toc_txt and "Sec A1" not in toc_txt and "doc" not in toc_txt.split(),
        "D1 목차 = 책갈피 1단계(파일 이름이 아니다)", toc_txt[:200])
    toc = o.get_toc(simple=True)
    chk([(lv, t) for lv, t, _p in toc] == [(1, "Chapter A"), (2, "Sec A1"), (1, "Chapter B"), (2, "Sec B1")],
        "D2 책갈피는 원본 단계 그대로(파일 이름 단계 없음)", str(toc))
    # 목차 1쪽 + 본문 6쪽/2 = 3시트, 간지 없음
    chk(o.page_count == 4, "D3 간지·문서 나눔은 꺼진다(목차 1 + 본문 3)", str(o.page_count))
    chk([p for _lv, _t, p in toc] == [2, 2, 3, 4], "D4 책갈피가 그 쪽이 든 시트로", str(toc))
    chk("1" in toc_txt and "2" in toc_txt, "D5 목차 번호는 본문 번호")
    o.close()
    # 병합(single 아님)은 종전대로 파일 이름 단계
    out3 = str(root / "merge.pdf")
    build_twoup(ITEM, merge_twoup_settings({"nup": 2, "make_cover": False, "make_toc": False}), out3)
    o = fitz.open(out3)
    chk(o.get_toc(simple=True)[0][:2] == [1, "doc"], "D6 병합은 종전대로 파일 이름이 1단계", str(o.get_toc(simple=True)[:2]))
    o.close()

    # G — 261021-4: 쪽 밖을 가리키는 책갈피(자동 생성)가 섞여도 목차 쪽 수·번호가 맞다
    nob = root / "nobm.pdf"
    d = fitz.open()
    for i in range(6):
        d.new_page(width=595, height=842).insert_text((72, 300), "N %d" % (i + 1))
    d.save(str(nob)); d.close()
    gen = lambda path, doc: ([("Good %d" % k, 1 + k % 6, 0) for k in range(10)]
                             + [("Out %d" % k, 99, 0) for k in range(15)])
    out4 = str(root / "outrange.pdf")
    g_err = None
    try:
        build_twoup([{"type": "pdf", "path": str(nob), "name": "nobm"}],
                    single_file_settings({"nup": 2, "make_cover": False, "make_toc": True}), out4,
                    gen_bookmarks_fn=gen)
    except Exception as e:                                     # noqa: BLE001
        g_err = e
    chk(g_err is None, "G1 쪽 밖 책갈피가 섞여도 만들어진다", repr(g_err))
    if g_err is None:
        o = fitz.open(out4)
        body = [o[i].get_text("text") for i in range(o.page_count)]
        chk(o.page_count == 1 + 3 and "Out 0" not in body[0] and "Good 9" in body[0],
            "G2 목차는 쪽 안 책갈피만, 한 쪽(목차 1 + 본문 3)", str((o.page_count, body[0][:80])))
        chk(body[1].strip().endswith("1") or "\n1\n" in "\n" + body[1] + "\n", "G3 본문 첫 시트 번호가 1", body[1][-20:])
        o.close()

    # H — 261021-4: 파일 하나 창의 샘플 단추는 간지 양식을 만들지 않는다
    import importlib.util
    if importlib.util.find_spec("docx") is not None:
        sdir = root / "samples"; sdir.mkdir()
        from PyQt6.QtWidgets import QFileDialog as _QFD
        _orig_dir = _QFD.getExistingDirectory
        _QFD.getExistingDirectory = staticmethod(lambda *a_, **k: str(sdir))
        QMessageBox.information = staticmethod(lambda *a_, **k: None)
        dlg3 = TwoUpSettingsDialog({}, None, preset_api=api, sample=str(src), single=True)
        dlg3._save_samples()
        made = sorted(p.name for p in sdir.iterdir())
        chk(len(made) == 2 and not any("간지" in n for n in made), "H 파일 하나 창 샘플 = 표지·목차만", str(made))
        dlg3.close()
        _QFD.getExistingDirectory = _orig_dir
    else:
        print("SKIP - H python-docx 없음")

    # E — 미리보기 목차
    from viewer.twoup import compose_preview, clear_preview_cache
    png, ow, oh, cells, total = compose_preview(str(src), single_file_settings({"nup": 2, "make_cover": False, "make_toc": True}), 0, dpi=40)
    from viewer import twoup as _tw
    tdoc = _tw._PREVIEW_DOC.get("toc_doc")
    ptxt = tdoc[0].get_text("text") if tdoc is not None else ""
    chk(total == 4 and "Chapter B" in ptxt, "E 미리보기도 같은 목차·시트 수", str((total, ptxt[:80])))
    clear_preview_cache()

    # F — 앱 경로
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    # A — 메뉴 자리
    m_tools = next(x.menu() for x in mw.menuBar().actions() if x.text().startswith("도구"))
    names = [x.text() for x in m_tools.actions() if not x.isSeparator()]
    chk("다단 생성..." in names and names.index("다단 생성...") == names.index("PDF 병합...") + 1,
        "A 도구 메뉴 '다단 생성...' 은 'PDF 병합...' 바로 아래", str(names[:12]))
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(src), 0); spin(1.0)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    before = src.read_bytes()
    TwoUpSettingsDialog.exec = lambda self: (self.cmb_nup.setCurrentIndex(0), QDialog.DialogCode.Accepted)[1]
    asked = []
    QFileDialog.getSaveFileName = staticmethod(lambda *a_, **k: (asked.append(a_[2]), (a_[2], ""))[1])
    mw.action_nup_create(); spin(3.0)
    out = folder / "doc_nup.pdf"
    chk(asked and Path(asked[0]).name == "doc_nup.pdf", "F1 저장 창 기본 이름 <원본>_nup.pdf", str(asked))
    chk(out.exists() and fitz.open(str(out)).page_count == 6, "F2 새 파일(1-up 6쪽)", str(out.exists()))
    chk(src.read_bytes() == before, "F3 원본은 그대로")
    mw._on_bookmark_activated(str(src), 0); spin(1.0)
    asked.clear()
    mw._edit_dirty = True
    mw.action_nup_create(); spin(0.5)
    chk(not asked, "F4 저장 안 한 편집이 있으면 만들지 않는다")
    mw._edit_dirty = False
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
