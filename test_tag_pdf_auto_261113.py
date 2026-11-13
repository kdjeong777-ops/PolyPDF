# -*- coding: utf-8 -*-
"""자동 해시태그 (PDF 모드) — 정해진 13 항목·이름 고정·속성 판정·한 번 정리 (태그 SOT §5.3·§5.3.1·§5.8, 261113-10 사용자 지시·결정).

사용자 지시(2026-11-13): 환경설정 '형식 낱말' → '자동 해시태그' — 항목은 날짜·한글·영어·스크린샷·스캔문서·텍스트문서·설명서·영수증·
공문·견적서·보고서·발표자료·논문, 켜고 끄기만(이름 못 고침), 기존 형식 낱말 지움, '분류 더하기' 없앰.
사용자 결정: PDF 모드용·사진 모드용을 따로(이번은 PDF), 빠진 형식·분류의 이미 붙은 자동 태그는 '자동 태그만 뗌'.
실제 MainWindow·SettingsDialog 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 환경설정 '자동 해시태그 (PDF 모드)' — 13 체크 상자(글 = 이름), 고칠 글 상자·[분류 더하기] 없음, 사진 묶음 '자동 해시태그 (사진 모드)'
B. 속성 판정 — 날짜(PDF 만든 날)·한글/영어·스캔문서/텍스트문서·스크린샷(이름·화면 크기 그림), 끈 항목은 뺀다, 자동 부여 대상
C. 한 번 정리 — 빠진 형식(기사)·사용자 분류·바꾼 형식 이름의 PDF 자동 태그를 정리, 직접 태그·사진 태그는 그대로, 표시를 쓰고 다시는 안 한다
D. 끈 PDF 자동 해시태그는 PDF 에서만 뺀다 — 사진의 같은 이름(영수증·촬영일)은 그대로
E. 261113-10 덧붙임(사용자 지시 '자동부여된 것이 해시태그 목록으로 안나와. 사진모드와 유사하게'·결정 '기본 켬 + 켜기 체크를 PDF 묶음 맨 위'):
   PDF 자동 부여가 기본 켬이고 꺼 둔 설정도 한 번 켠다, 켜기 체크가 '자동 해시태그 (PDF 모드)' 맨 위(굵게)이고 끄면 13 항목이 잠긴다
"""
import os, sys, tempfile, shutil, time, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QCheckBox, QGroupBox, QLineEdit, QPushButton
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_pdf_auto_tags_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "자동 해시태그 (PDF 모드)", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def pump(cond, timeout=20.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_pdfauto_"))


def mk(name, pages=1, text="", img=None, created=None, size=(595, 842)):
    p = str(tmp / name)
    d = fitz.open()
    for _ in range(pages):
        pg = d.new_page(width=size[0], height=size[1])
        if text:
            pg.insert_text((40, 60), text, fontsize=10)
        if img:
            pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, img[0], img[1]))
            pm.set_rect(pm.irect, (230, 230, 240))
            pg.insert_image(pg.rect, pixmap=pm)
    if created:
        d.set_metadata({"creationDate": created})
    d.save(p); d.close()
    return p


try:
    from viewer import auto_tag as AT, tag_rules as TR
    from viewer.settings_store import settings_dir
    rp = Path(settings_dir()) / "tag_rules.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    # 종전 규칙 파일 — 형식 이름 바꾸기·사용자 분류(261112-11)·끈 형식(기사), 정리 표시 없음
    rp.write_text(json.dumps({"alias": {"보고서": "외국보고서", "SamsungSM-S918N": "GalaxyS23"},
                              "format_custom": [{"name": "계약서", "words": ["계약"]}], "format_off": ["기사", "논문"], "mine": 1},
                             ensure_ascii=False), encoding="utf-8")
    # E 준비 — 종전 옵트인으로 꺼 둔 설정(한 번 켜기 표시 없음)
    (Path(settings_dir()) / "settings.json").write_text(json.dumps({"auto_tag_enabled": False, "auto_tag_optin_migrated": True}),
                                                        encoding="utf-8")
    from viewer.app import MainWindow
    from viewer.widgets.settings_dialog import SettingsDialog
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.show(); pump(lambda: False, 0.3)
    store = mw.bookmark_tree._tags

    # A
    chk(mw._prefs.get("auto_tag_enabled") is True and mw._prefs.get("auto_tag_on_migrated") is True,
        "E 꺼 둔 PDF 자동 부여를 한 번 켠다(기본 켬)", str({k: mw._prefs.get(k) for k in ("auto_tag_enabled", "auto_tag_on_migrated")}))
    dlg = SettingsDialog(mw._prefs, mw, host=mw, page="tags")
    pn = dlg.tag_rules_panel
    g1e = [g for g in pn.findChildren(QGroupBox) if g.title() == "자동 해시태그 (PDF 모드)"]
    if g1e:
        top = pn.pdf_lay.itemAt(0).widget() if pn.pdf_lay.count() else None
        chk(top is dlg.chk_auto_tag and g1e[0].isAncestorOf(top) and top.font().bold() and top.isChecked(),
            "E 켜기 체크가 'PDF 모드' 묶음 맨 위(굵게, 켜짐)", str(top.text() if top else None))
        dlg.chk_auto_tag.setChecked(False)
        chk(not any(c.isEnabled() for c in pn.fmt_chk.values()), "E 끄면 13 항목이 잠긴다")
        dlg.chk_auto_tag.setChecked(True)
        chk(all(c.isEnabled() for c in pn.fmt_chk.values()), "E 다시 켜면 풀린다")
    g1 = [g for g in pn.findChildren(QGroupBox) if g.title() == "자동 해시태그 (PDF 모드)"]
    chk(bool(g1), "A 묶음 '자동 해시태그 (PDF 모드)'", str([g.title() for g in pn.findChildren(QGroupBox)]))
    if g1:
        cbs = [c.text() for c in g1[0].findChildren(QCheckBox) if c is not dlg.chk_auto_tag]
        chk(cbs == list(AT.PDF_AUTO_ITEMS) and cbs[:6] == ["날짜", "한글", "영어", "스크린샷", "스캔문서", "텍스트문서"]
            and cbs[6:] == ["설명서", "영수증", "공문", "견적서", "보고서", "발표자료", "논문"], "A 13 항목 — 사용자 차례", str(cbs))
        chk(not g1[0].findChildren(QLineEdit), "A 이름을 고칠 글 상자가 없다")
        chk(not pn.fmt_chk["논문"].isChecked() and pn.fmt_chk["보고서"].isChecked(), "A 지금 규칙(논문 끔)")
    chk(not [b for b in pn.findChildren(QPushButton) if b.text() == "분류 더하기"], "A [분류 더하기] 없음")
    chk(any(g.title() == "자동 해시태그 (사진 모드)" for g in pn.findChildren(QGroupBox)), "A 사진 묶음 '자동 해시태그 (사진 모드)'")
    dlg.reject()

    # B
    def attrs(path, texts=None, rules=None):
        return AT.pdf_attr_tags(AT.extract_features(path, page_texts=texts), rules or {})
    ko_txt = ["배수성 포장의 공극률과 투수 성능을 시험한 결과 보고 " * 8 + "OGFC porous"]
    en_txt = ["Porous asphalt pavement permeability and durability study " * 8 + "배수성"]
    t1 = mk("ko.pdf", text="x", created="D:20240315093000+09'00'")
    chk(attrs(t1, ko_txt) == ["2024-03-15", "한글", "텍스트문서"], "B 날짜(PDF 만든 날)·한글·텍스트문서", str(attrs(t1, ko_txt)))
    chk(attrs(mk("en.pdf", text="x"), en_txt) == ["영어", "텍스트문서"], "B 영어(날짜 없으면 안 붙임)", str(attrs(mk("en.pdf", text="x"), en_txt)))
    _mx = attrs(mk("mix.pdf", text="x"), ["포장 pavement 설계 design " * 20])
    chk("한글" not in _mx and "영어" not in _mx, "B 반반 섞인 글은 언어를 붙이지 않는다", str(_mx))
    chk("한글" not in attrs(mk("short.pdf", text="x"), ["짧은 글"]), "B 글자가 적으면 언어 없음")
    sc = mk("scan.pdf", pages=2, img=(1240, 1754))
    chk(attrs(sc, []) == ["스캔문서"], "B 글자층 없는 그림 PDF → 스캔문서", str(attrs(sc, [])))
    chk("스캔문서" in attrs(sc, ko_txt * 2), "B OCR 글자층을 얹은 스캔(그림이 쪽을 채움)도 스캔문서", str(attrs(sc, ko_txt * 2)))
    chk(attrs(mk("old.pdf", text="x", created="D:19800101"), ko_txt)[0] == "한글", "B 1990년 전 날짜는 안 붙임")
    shot = mk("화면.pdf", img=(1080, 2340), size=(300, 650))
    chk("스크린샷" in attrs(shot, []), "B 화면 크기 그림 하나가 쪽을 채우면 스크린샷", str(attrs(shot, [])))
    chk("스크린샷" in attrs(mk("Screenshot_20240101.pdf", text="x"), en_txt), "B 이름이 스크린샷 꼴")
    chk("스크린샷" not in attrs(mk("photo.pdf", img=(1000, 1000), size=(500, 500)), []), "B 정사각 사진 그림은 스크린샷 아님")
    off = {"format_off": ["날짜", "한글", "스캔문서"]}
    chk(attrs(t1, ko_txt, off) == ["텍스트문서"] and attrs(sc, [], off) == [], "B 끈 항목은 붙이지 않는다", str(attrs(t1, ko_txt, off)))
    f = AT.extract_features(t1, page_texts=ko_txt)
    auto = [s["tag"] for s in AT.partition(AT.suggest_tags(f, {}, {}, 1))["auto"]]
    chk({"2024-03-15", "한글", "텍스트문서"} <= set(auto), "B 속성은 자동 부여 대상(점수 없이)", str(auto))

    # C
    A, B2, C = str(tmp / "a.pdf"), str(tmp / "b.pdf"), str(tmp / "c.pdf")
    PH = str(tmp / "p.jpg")
    store.set_auto(A, ["기사", "외국보고서", "계약서", "아스팔트"])
    store.set_auto(B2, ["논문"])
    store.set(C, ["지침", "기사"])
    store.set_auto_part(PH, "kind", ["영수증"])
    store.set_auto_part(PH, "meta", ["2026-11-05", "SamsungSM-S918N"])
    ends = []
    real_apply = TR.apply

    def spy(mw_, rules):
        job = real_apply(mw_, rules)
        job.ended.connect(lambda n: ends.append(n))
        return job
    TR.apply = spy
    mw._start_autotag_scan()                       # 첫 태그 계산 — 그 앞에서 한 번 정리(§5.8 의 6)
    chk(pump(lambda: bool(ends)), "C 첫 태그 계산 앞에서 한 번 정리가 돈다")
    chk(store.get_auto(A) == ["보고서", "아스팔트"], "C 빠진 형식·사용자 분류는 떼고 바꾼 형식 이름은 원래대로", str(store.get_auto(A)))
    chk(store.get_auto(B2) == [], "C 끈 항목(논문)의 자동 태그도 뗀다", str(store.get_auto(B2)))
    chk(store.get_manual(C) == ["지침", "기사"], "C 직접 붙인 태그는 그대로", str(store.get(C)))
    chk(store.get_auto_part(PH, "kind") == ["영수증"] and store.get_auto_part(PH, "meta") == ["2026-11-05", "GalaxyS23"],
        "C 사진 태그는 사진 규칙대로(별칭만)", str(store.record(PH)))
    saved = json.loads(rp.read_text(encoding="utf-8"))
    chk(saved.get("pdf_auto_v") == 2 and "format_custom" not in saved and saved.get("alias") == {"SamsungSM-S918N": "GalaxyS23"}
        and saved.get("format_off") == ["논문"] and saved.get("mine") == 1, "C 규칙 파일 — 정리 표시, 분류·형식 이름 바꾸기 없음, 다른 키는 남는다", str(saved))
    n0 = len(ends)
    mw._pdf_auto_migrated = False
    chk(TR.migrate_if_needed(mw) is None and len(ends) == n0, "C 표시가 있으면 다시 하지 않는다")
    TR.apply = real_apply

    # D
    fn = TR.remapper({"pdf_auto_v": 2}, {"format_off": ["영수증", "날짜"], "pdf_auto_v": 2})
    chk(fn("영수증", "x.pdf") is None and fn("2024-03-15", "x.pdf") is None and fn("영수증", "x.jpg") == "영수증"
        and fn("2024-03-15", "x.jpg") == "2024-03-15" and fn("기사", "x.pdf") == "기사",
        "D 끈 항목은 PDF 에서만(사진 그대로), 정리 뒤에는 '기사' 같은 주제 태그를 건드리지 않는다")
    mw.close()
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
