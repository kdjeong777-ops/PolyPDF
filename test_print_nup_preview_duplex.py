# -*- coding: utf-8 -*-
"""261008-2: 인쇄 '다단 인쇄' — 미리보기 · 단면/양면 연동 · 양면(긴 쪽/짧은 쪽) 세분화 (마스터 §11.10.1).

사용자 요청:
  - '다단 인쇄' 선택 시 미리보기에 해당 인쇄 설정으로 나타나도록
  - '다단 인쇄' 선택 시 해당 설정의 '단면/양면' 이 '프린터 옵션' 에 적용되도록
  - '다단 인쇄' 설정의 '양면' 을 프린터 설정과 같은 '양면(긴 쪽)'·'양면(짧은 쪽)' 으로 세분화

A. 다단 설정 창 — 세 갈래, 옛 스타일(duplex: True) 호환, 저장 값
B. 인쇄 창 미리보기 — 다단을 켜면 시트 수·모양이 **실제 다단 PDF(build_twoup)** 와 같다(범위별)
C. 단면/양면 — 다단을 켜면 그 설정이 프린터 옵션에 걸리고 잠긴다, 끄면 되돌린다, 설정 창·스타일 고르기도
"""
import os, sys, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = Path(tempfile.mkdtemp(prefix="polypdf_nupprev_"))
try:
    src = root / "원본.pdf"
    d = fitz.open()
    for i in range(8):
        d.new_page(width=595, height=842).insert_text((72, 72), f"page {i + 1}", fontsize=40)
    d.save(str(src)); d.close()

    from viewer.twoup import build_twoup, duplex_choice, merge_twoup_settings
    from viewer.widgets.twoup_dialog import TwoUpSettingsDialog
    from viewer.widgets.print_dialog import PrintScopeDialog

    # ── A. 다단 설정 창 ──────────────────────────────────────────────
    t = TwoUpSettingsDialog({"duplex": True}, None, sample=str(src))
    chk([t.cmb_duplex.itemText(i) for i in range(t.cmb_duplex.count())]
        == ["단면", "양면(긴 쪽)", "양면(짧은 쪽)"], "A '인쇄 면' 이 프린터와 같은 세 갈래")
    chk(t.cmb_duplex.currentText() == "양면(긴 쪽)", "A 옛 스타일 duplex:True → 양면(긴 쪽)", t.cmb_duplex.currentText())
    t.cmb_duplex.setCurrentIndex(2)
    g = t.get_settings()
    chk(g["duplex"] is True and g["duplex_side"] == "short", "A 짧은 쪽 저장 = duplex True + duplex_side short", str(g.get("duplex_side")))
    t.chk_docbreak.setChecked(True)
    chk(not t.chk_doc_odd.isHidden(), "A 짧은 쪽도 양면 — '새 문서는 홀수 페이지로' 가 보인다")
    t.cmb_duplex.setCurrentIndex(0)
    chk(t.get_settings()["duplex"] is False and t.chk_doc_odd.isHidden(), "A 단면이면 duplex False·홀수 시작 숨김")
    t.apply_settings({"duplex": True, "duplex_side": "short"})
    chk(t.cmb_duplex.currentText() == "양면(짧은 쪽)", "A 스타일 적용도 세 갈래로 읽는다")
    t.done(0)
    chk(duplex_choice({}) == "none" and duplex_choice({"duplex": True}) == "long"
        and duplex_choice({"duplex": True, "duplex_side": "short"}) == "short", "A duplex_choice")

    # ── B. 인쇄 창 다단 미리보기 ─────────────────────────────────────
    _n = [0]

    def real_sheets(pages, settings):
        _n[0] += 1                                  # 다단 엔진이 문서를 캐시한다 — 이름을 매번 새로
        sub = root / f"sub_real{_n[0]}.pdf"; out = root / f"nup_real{_n[0]}.pdf"
        sd = fitz.open(str(src)); td = fitz.open()
        for p in pages:
            td.insert_pdf(sd, from_page=p, to_page=p)
        td.save(str(sub)); sd.close(); td.close()
        build_twoup([{"type": "pdf", "path": str(sub), "name": src.stem}], settings, str(out),
                    log=lambda *a, **k: True, progress=lambda *a, **k: True)
        with fitz.open(str(out)) as nd:
            return nd.page_count, nd[0].rect

    dlg = PrintScopeDialog(8, 2, 0, 0, None, preset_api=None, sample=str(src), thumb_pages=[1, 4, 6])
    dlg.resize(900, 650); dlg.show(); app.processEvents(); QTest.qWait(30)
    off_label = dlg.lbl_pageno.text()
    chk(off_label == "1 / 8", "준비 — 다단 끄면 원본 쪽 기준", off_label)
    dlg.chk_nup.setChecked(True); app.processEvents()
    n_real, r_real = real_sheets(list(range(8)), dlg.nup_settings())
    chk(dlg.lbl_pageno.text() == f"시트 1 / {n_real}",
        "B 다단을 켜면 미리보기가 **인쇄될 시트** 기준(실제 다단 PDF 와 같은 수)", f"{dlg.lbl_pageno.text()} vs {n_real}")
    pm = dlg.preview.pixmap()
    chk(pm is not None and not pm.isNull() and (pm.width() > pm.height()) == (r_real.width > r_real.height),
        "B 미리보기 모양 = 실제 시트 방향(2-up 세로 원본 → 가로 시트)",
        f"{pm.width()}x{pm.height()} vs {r_real.width:.0f}x{r_real.height:.0f}")
    chk(dlg.preview_cap.text().startswith("다단"), "B 설명 줄에 '다단'", dlg.preview_cap.text())
    dlg.btn_next.click(); app.processEvents()
    chk(dlg.lbl_pageno.text() == f"시트 2 / {n_real}", "B ▶ 는 시트를 넘긴다", dlg.lbl_pageno.text())
    for rb, pages, why in ((dlg.rb_cur, [2], "현재 페이지"), (dlg.rb_thumb, [1, 4, 6], "선택 썸네일")):
        rb.setEnabled(True); rb.setChecked(True); app.processEvents()
        n, _r = real_sheets(pages, dlg.nup_settings())
        chk(dlg.lbl_pageno.text() == f"시트 1 / {n}", f"B 범위 '{why}' 도 실제와 같은 시트 수", f"{dlg.lbl_pageno.text()} vs {n}")
    dlg.rb_range.setChecked(True); dlg.sp_from.setValue(3); dlg.sp_to.setValue(7); app.processEvents()
    n, _r = real_sheets([2, 3, 4, 5, 6], dlg.nup_settings())
    chk(dlg.lbl_pageno.text() == f"시트 1 / {n}", "B 페이지 범위(3~7)도 같다", f"{dlg.lbl_pageno.text()} vs {n}")
    dlg.rb_all.setChecked(True)
    dlg.chk_nup.setChecked(False); app.processEvents()
    chk(dlg.lbl_pageno.text() == "1 / 8" and not dlg.preview_cap.text().startswith("다단"),
        "B 다단을 끄면 원본 쪽 미리보기로 돌아온다", dlg.lbl_pageno.text())

    # ── C. 단면/양면 연동 ─────────────────────────────────────────────
    dlg.cmb_duplex.setCurrentText("양면(긴 쪽)")
    dlg._nup_settings = {"duplex": True, "duplex_side": "short"}
    dlg.chk_nup.setChecked(True); app.processEvents()
    chk(dlg.cmb_duplex.currentText() == "양면(짧은 쪽)" and not dlg.cmb_duplex.isEnabled(),
        "C 다단을 켜면 그 설정의 면이 프린터 옵션에 걸리고 잠긴다", dlg.cmb_duplex.currentText())
    chk(dlg.duplex_mode() == QPrinter.DuplexMode.DuplexShortSide, "C 프린터에 넘기는 값(duplex_mode)도 짧은 쪽")
    chk("양면(짧은 쪽)" in dlg.preview_cap.text(), "C 미리보기 설명에도 면", dlg.preview_cap.text())

    def fake_exec(td):
        td.cmb_duplex.setCurrentIndex(0)          # 설정 창에서 '단면' 으로 바꾸고 확인
        return QDialog.DialogCode.Accepted
    _orig_exec = TwoUpSettingsDialog.exec
    TwoUpSettingsDialog.exec = fake_exec
    dlg.btn_nup.click(); app.processEvents()
    TwoUpSettingsDialog.exec = _orig_exec
    chk(dlg.cmb_duplex.currentText() == "단면", "C 다단 설정 창에서 바꾸면 프린터 옵션도 따라간다", dlg.cmb_duplex.currentText())
    dlg.chk_nup.setChecked(False); app.processEvents()
    chk(dlg.cmb_duplex.currentText() == "양면(긴 쪽)" and dlg.cmb_duplex.isEnabled(),
        "C 다단을 끄면 켜기 전 값으로 되돌리고 풀린다", dlg.cmb_duplex.currentText())
    dlg.cmb_preset.addItem("짧은쪽 스타일", {"name": "짧은쪽 스타일", "duplex": True, "duplex_side": "short"})
    dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.count() - 1)
    dlg.cmb_preset.activated.emit(dlg.cmb_preset.count() - 1); app.processEvents()
    chk(dlg.chk_nup.isChecked() and dlg.cmb_duplex.currentText() == "양면(짧은 쪽)",
        "C 스타일을 고르면 다단이 켜지고 그 면이 걸린다", dlg.cmb_duplex.currentText())
    dlg.done(0)
    chk(dlg._nup_tmpdir is None, "임시 범위 PDF 를 닫을 때 지운다")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
