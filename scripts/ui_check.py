# -*- coding: utf-8 -*-
"""PolyPDF 화면 점검 — 주요 창·대화상자를 오프스크린으로 띄워 스크린샷을 찍고 레이아웃을 검사한다.

사용법 (public 폴더에서, 개발 venv 로):

    .venv\\Scripts\\python.exe scripts/ui_check.py                 # ko·en 둘 다(언어마다 하위 프로세스)
    .venv\\Scripts\\python.exe scripts/ui_check.py --lang en       # 한 언어만
    .venv\\Scripts\\python.exe scripts/ui_check.py --out D:\\tmp\\ui  # 출력 폴더 지정
    .venv\\Scripts\\python.exe scripts/ui_check.py --only settings,print   # 일부 창만(이름은 아래 출력 참조)

출력 (기본 `<작업폴더>/_review/ui_check/`, 작업폴더 = public 의 부모):
    <lang>/<name>.png        창 스크린샷 (설정 창은 스크롤 내용 전체도 `settings_full.png`)
    <lang>/findings.json     창별 검사 결과
    findings.json            언어별 결과를 합친 것
    summary.md               창별 요약 표 + 항목별 상세

검사 항목 (창마다):
    1. 잘린 글자 — 보이는 버튼·라벨(줄바꿈 없음)·콤보·체크·라디오에서
       sizeHint 폭 > 실제 폭+1 **이고** 글자 폭(+여백) > 실제 폭일 때만 잡는다
       (스타일 최소 폭 때문에 sizeHint 만 큰 오탐을 줄인다). 아이콘만 있는 버튼은 뺀다.
    2. 기본 크기에서 가로 스크롤바가 보이는 QScrollArea (화면 디자인 SOT §2.14)
    3. 기본 크기가 1366x768 보다 큰 창 (작은 노트북 화면)
    4. en 실행에서 화면에 보이는 한글 [가-힣] (글꼴 이름·이중 언어 표기 '/ Language' 등은 뺀다)
    5. 같은 레이아웃 안 형제 위젯끼리 겹침 (중첩 레이아웃 포함)
    6. 줄바꿈 라벨의 세로 잘림 — 배치된 높이 < heightForWidth(폭)

안전장치:
    - QStandardPaths 테스트 모드 + 고유 앱 이름 → 사용자 실제 설정 폴더(LocalTools\\PolyPDF)를 건드리지 않는다.
    - 대화상자는 exec() 대신 show() — QDialog.exec 를 바꿔 끼워 '앱이 실제로 만드는 그대로' 붙잡는다.
      QMessageBox·QFileDialog 정적 함수도 막아 멈추지 않게 한다.
    - 종료는 os._exit (Qt 종료 단계 충돌 방지).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent
DEFAULT_OUT = PUBLIC.parent / "_review" / "ui_check"
LANGS = ("ko", "en")

SMALL_SCREEN = (1366, 768)
HANGUL = re.compile(r"[가-힣]")
# en 실행에서도 한글이 있어야 맞는 글(이중 언어 표기 — 다국어 SOT)
BILINGUAL_OK = ("/ Language", "Language / ", "Restart now", "Later")


# ════════════════════════════════════════════════════════════════════════
#  하위 프로세스: 한 언어 실행
# ════════════════════════════════════════════════════════════════════════
def run_one(lang: str, out_root: Path, only=None):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if os.path.isdir(r"C:\Windows\Fonts"):
        os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"     # 실제 글꼴 폭으로 잰다
    os.environ.pop("POLYPDF_LANG", None)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.path.insert(0, str(PUBLIC))

    from PyQt6.QtCore import QStandardPaths, QCoreApplication
    QStandardPaths.setTestModeEnabled(True)                  # 무엇이든 만들기 전에
    from PyQt6.QtWidgets import (QApplication, QDialog, QMessageBox, QFileDialog, QInputDialog,
                                 QWidget, QAbstractButton, QToolButton, QLabel, QComboBox,
                                 QFontComboBox, QCheckBox, QRadioButton, QScrollArea, QGroupBox,
                                 QTabBar, QLineEdit, QStyle, QStackedLayout, QMenu, QTextBrowser,
                                 QTextEdit, QMainWindow)
    from PyQt6.QtGui import QFont, QFontDatabase, QTextDocument, QPageSize

    app = QApplication.instance() or QApplication(sys.argv[:1])
    QCoreApplication.setApplicationName("polypdf_ui_check_%s_%d" % (lang, os.getpid()))
    QCoreApplication.setOrganizationName("polypdf_ui_check")
    app.setFont(QFont("Malgun Gothic", 9))

    from viewer import i18n
    i18n.install(app, lang)                                   # 창을 만들기 전에

    out_dir = out_root / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    font_families = set(QFontDatabase.families())
    lang_names = {n for _c, n, _s in i18n.available_languages()}   # 언어 목록은 자기 이름(한국어)으로 보인다

    def pump(sec=0.6):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    # ── 막히는 호출 막기 ────────────────────────────────────────────────
    captured = []                     # exec() 로 띄우려던 대화상자

    def fake_exec(self, *a, **k):
        captured.append(self)
        self.show()
        return 0                      # Rejected — 호출한 쪽은 '취소' 길로 빠진다

    QDialog.exec = fake_exec
    QMessageBox.exec = fake_exec
    msgs = []

    def _fake_static(kind):
        def f(*a, **k):
            msgs.append((kind, str(a[1] if len(a) > 1 else ""), str(a[2] if len(a) > 2 else "")))
            return QMessageBox.StandardButton.No if kind == "question" else QMessageBox.StandardButton.Ok
        return staticmethod(f)

    for _k in ("information", "warning", "critical", "question"):
        setattr(QMessageBox, _k, _fake_static(_k))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
    QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))

    def via_exec(fn):
        """앱 처리기를 그대로 부르고, 그 안에서 exec() 하려던 대화상자를 돌려준다."""
        n0 = len(captured)
        fn()
        pump(0.3)
        new = [d for d in captured[n0:] if not isinstance(d, QMessageBox)]
        if not new:
            raise RuntimeError("대화상자가 뜨지 않음 (메시지: %s)" % (msgs[-1:] or "-"))
        return new[0]

    # ── 검사 ────────────────────────────────────────────────────────────
    style = app.style()
    ind_w = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth) + \
        style.pixelMetric(QStyle.PixelMetric.PM_CheckBoxLabelSpacing)

    def plain(text, rich=False):
        if not text:
            return ""
        if rich or ("<" in text and ">" in text):
            d = QTextDocument()
            d.setHtml(text)
            return d.toPlainText()
        return text.replace("&&", "\x00").replace("&", "").replace("\x00", "&")

    def text_px(w, text):
        fm = w.fontMetrics()
        return max((fm.horizontalAdvance(ln) for ln in text.split("\n")), default=0)

    def shown(w, top):
        return w.isVisible() and w.isVisibleTo(top) and w.width() > 0

    def path_of(w, top):
        parts = []
        p = w
        while p is not None and p is not top:
            nm = p.objectName()
            if nm:
                parts.append(nm)
                break
            p = p.parentWidget()
        return parts[0] if parts else ""

    def _pos(w, top):
        from PyQt6.QtCore import QPoint
        p = w.mapTo(top, QPoint(0, 0))
        return [p.x(), p.y()]

    def check_clipped(top):
        out = []
        for w in top.findChildren(QWidget):
            if not shown(w, top):
                continue
            text = None
            # 단추 여백은 앱 스타일시트가 좁게(좌우 약 2px) 잡는다 — 실측(스크린샷 대조)으로 4px.
            #   8px 로 두면 '편집'·'Tree'·'Delete' 처럼 실제로 다 보이는 단추까지 잡혔다.
            extra = 4
            if isinstance(w, QAbstractButton):
                text = plain(w.text())
                if not text.strip():
                    continue                        # 아이콘만 있는 단추
                if isinstance(w, (QCheckBox, QRadioButton)):
                    extra += ind_w
                elif not w.icon().isNull():
                    extra += w.iconSize().width() + 4
                if isinstance(w, QToolButton) and w.toolButtonStyle().name == "ToolButtonIconOnly":
                    continue
            elif isinstance(w, QLabel):
                if w.wordWrap() or w.pixmap() is not None and not w.pixmap().isNull():
                    continue
                text = plain(w.text(), w.textFormat().name == "RichText")
                if not text.strip():
                    continue
                extra = 2 * w.margin() + 2 * max(w.indent(), 0) + 2
            elif isinstance(w, QComboBox):
                if w.isEditable():
                    continue
                text = w.currentText()
                if not text.strip():
                    continue
                extra = 8 + 20                      # 좌우 여백 + 화살표 자리(실측: 'Modified' 70px 에서 잘림)
            else:
                continue
            need_txt = text_px(w, text) + extra
            need_hint = w.sizeHint().width()
            if need_hint > w.width() + 1 and need_txt > w.width():
                out.append({"class": type(w).__name__, "text": text[:120],
                            "width": w.width(), "need_text_px": need_txt, "over_px": need_txt - w.width(),
                            "need_sizehint": need_hint, "name": path_of(w, top),
                            "pos": _pos(w, top), "tip": plain(w.toolTip())[:80]})
            elif "…" in text and w.toolTip() and len(plain(w.toolTip())) > len(text):
                out.append({"class": type(w).__name__, "text": text[:120], "elided": True,
                            "width": w.width(), "need_text_px": need_txt,
                            "need_sizehint": need_hint, "name": path_of(w, top),
                            "pos": _pos(w, top), "tip": plain(w.toolTip())[:80]})
        return out

    def check_hscroll(top):
        out = []
        for sa in top.findChildren(QScrollArea):
            if shown(sa, top) and sa.horizontalScrollBar().isVisible():
                inner = sa.widget()
                out.append({"name": sa.objectName() or type(sa.parentWidget()).__name__,
                            "viewport_w": sa.viewport().width(),
                            "content_w": inner.width() if inner else None,
                            "content_min_w": inner.minimumSizeHint().width() if inner else None})
        return out

    def visible_texts(top):
        """(종류, 글) — 화면에 보이는 글. 메뉴 막대 아래 메뉴 항목도 포함."""
        items = [("window_title", top.windowTitle())]
        for w in top.findChildren(QWidget):
            if not shown(w, top):
                continue
            if isinstance(w, QFontComboBox):
                continue
            if isinstance(w, QAbstractButton):
                items.append((type(w).__name__, plain(w.text())))
            elif isinstance(w, QLabel):
                items.append(("QLabel", plain(w.text(), w.textFormat().name == "RichText")))
            elif isinstance(w, QGroupBox):
                items.append(("QGroupBox", w.title()))
            elif isinstance(w, QTabBar):
                items += [("QTabBar", w.tabText(i)) for i in range(w.count())]
            elif isinstance(w, QComboBox):
                for i in range(w.count()):
                    # 프린터 용지 이름은 OS 프린터 드라이버가 준다(앱 문구가 아니다) — 종류를 따로 적는다
                    kind = ("QComboBox(OS 프린터 용지 이름)" if isinstance(w.itemData(i), QPageSize)
                            else "QComboBox")
                    items.append((kind, w.itemText(i)))
            elif isinstance(w, QLineEdit):
                items.append(("placeholder", w.placeholderText()))
            elif isinstance(w, (QTextBrowser, QTextEdit)) and w.isReadOnly():
                for ln in w.toPlainText().splitlines():
                    items.append((type(w).__name__, ln))
        if isinstance(top, QMainWindow) and top.menuBar() is not None:
            def walk(menu, pre):
                for a in menu.actions():
                    if a.isSeparator() or not a.isVisible():
                        continue
                    items.append(("menu", pre + plain(a.text())))
                    if a.menu() is not None:
                        walk(a.menu(), pre + plain(a.text()) + " > ")
            for a in top.menuBar().actions():
                if a.isVisible():
                    items.append(("menubar", plain(a.text())))
                    if a.menu() is not None:
                        walk(a.menu(), plain(a.text()) + " > ")
        return items

    def check_hangul(top):
        if lang == "ko":
            return []
        out, seen = [], set()
        for kind, t in visible_texts(top):
            t = (t or "").strip()
            if not t or not HANGUL.search(t):
                continue
            if t in font_families or t in lang_names or any(b in t for b in BILINGUAL_OK):
                continue
            if (kind, t) in seen:
                continue
            seen.add((kind, t))
            out.append({"kind": kind, "text": t[:160]})
        return out

    def _managed(lay, out):
        """레이아웃 나무(중첩 레이아웃 포함)가 배치하는 위젯 모으기. 쌓기 레이아웃은 한 장만 보이니 뺀다."""
        if lay is None or isinstance(lay, QStackedLayout):
            return out
        for i in range(lay.count()):
            it = lay.itemAt(i)
            if it.widget() is not None:
                out.append(it.widget())
            elif it.layout() is not None:
                _managed(it.layout(), out)
        return out

    def check_overlap(top):
        """같은 부모 위젯의 레이아웃(중첩 포함)이 배치한 형제끼리 겹치면 잡는다."""
        out = []
        for w in [top] + top.findChildren(QWidget):
            kids = [c for c in _managed(w.layout(), []) if shown(c, top)]
            for i in range(len(kids)):
                for j in range(i + 1, len(kids)):
                    r = kids[i].geometry().intersected(kids[j].geometry())
                    if r.width() > 2 and r.height() > 2:
                        out.append({"a": "%s '%s'" % (type(kids[i]).__name__, _label(kids[i])),
                                    "b": "%s '%s'" % (type(kids[j]).__name__, _label(kids[j])),
                                    "overlap": [r.width(), r.height()], "pos": _pos(kids[j], top)})
        return out

    def check_vclip(top):
        """줄바꿈 라벨이 필요한 높이(heightForWidth)보다 낮게 배치돼 아래 줄이 잘리는 경우."""
        out = []
        for w in top.findChildren(QLabel):
            if not (shown(w, top) and w.wordWrap() and w.text().strip()):
                continue
            need = w.heightForWidth(w.width())
            if need > w.height() + 2:
                out.append({"text": plain(w.text())[:120], "width": w.width(), "height": w.height(),
                            "need_height": need, "pos": _pos(w, top)})
        return out

    def _label(w):
        for attr in ("text", "title", "currentText"):
            f = getattr(w, attr, None)
            if callable(f):
                try:
                    return plain(f())[:40]
                except Exception:
                    pass
        return w.objectName()

    # ── 붙잡고 검사 ──────────────────────────────────────────────────────
    results = []

    def record(name, top, note="", extra_grab=None):
        pump(0.5)
        png = out_dir / ("%s.png" % name)
        top.grab().save(str(png))
        r = {"name": name, "class": type(top).__name__, "title": top.windowTitle(),
             "size": [top.width(), top.height()],
             "min_hint": [top.minimumSizeHint().width(), top.minimumSizeHint().height()],
             "png": str(png), "note": note,
             "clipped": check_clipped(top), "hscroll": check_hscroll(top),
             "oversize": top.width() > SMALL_SCREEN[0] or top.height() > SMALL_SCREEN[1],
             "hangul": check_hangul(top), "overlap": check_overlap(top), "vclip": check_vclip(top)}
        if extra_grab is not None:
            p2 = out_dir / ("%s_full.png" % name)
            extra_grab.grab().save(str(p2))
            r["png_full"] = str(p2)
        results.append(r)
        print("  [OK] %-20s %4dx%-4d clip=%d vclip=%d hs=%d hangul=%d overlap=%d" % (
            name, top.width(), top.height(), len(r["clipped"]), len(r["vclip"]), len(r["hscroll"]),
            len(r["hangul"]), len(r["overlap"])), flush=True)

    def skip(name, reason):
        results.append({"name": name, "skipped": reason})
        print("  [SKIP] %-18s %s" % (name, reason), flush=True)

    def capture(name, make, note="", full=None, close=True):
        """make() → 위젯. 실패하면 이유와 함께 skip 으로 남긴다."""
        if only and name not in only:
            return None
        try:
            w = make()
            if w is None:
                raise RuntimeError("위젯 없음")
            if not w.isVisible():
                w.show()
            pump(0.6)
            record(name, w, note, full(w) if full else None)
            if close:
                try:
                    if isinstance(w, QDialog):
                        w.done(0)
                    else:
                        w.close()
                except Exception:
                    pass
                pump(0.2)
            return w
        except Exception as e:
            skip(name, "%s: %s" % (type(e).__name__, e))
            traceback.print_exc()
            return None

    # ── 샘플 문서 ────────────────────────────────────────────────────────
    import test_fixtures as _fx
    tmp = Path(tempfile.mkdtemp(prefix="polypdf_uicheck_"))
    pdf = tmp / "sample.pdf"
    shutil.copy(Path(_fx.text_pdf()), pdf)

    code = 0
    try:
        from viewer.app import MainWindow
        mw = MainWindow()
        mw._skip_save_on_close = True
        mw.resize(1400, 900)
        mw.show()
        pump(1.0)
        record("main_nodoc", mw, note="크기 1400x900 은 스크립트가 정한 값")

        mw.open_folder(tmp)                  # 폴더(책갈피 목록) + 하이퍼링크 저장소가 생긴다
        pump(0.5)
        mw.open_pdf(pdf)
        pump(1.2)
        record("main_doc", mw, note="크기 1400x900 은 스크립트가 정한 값")

        # 발표 창은 편집 모드가 아닐 때 먼저 — 뒤의 처리기 중 편집 모드로 바꾸는 것이 있다
        def _present():
            n0 = len(msgs)
            mw._open_presentation()
            pump(0.8)
            w = getattr(mw, "_present", None)
            if w is None:
                raise RuntimeError("발표 창 없음 — 현재 파일 %r, 편집 모드 %s, 메시지 %s, 붙잡은 창 %s" % (
                    mw.main_view.current_file(), mw.bookmark_tree.is_edit_mode(), msgs[n0:],
                    [type(c).__name__ for c in captured[-3:]]))
            return w
        capture("presentation", _present, note="전체화면 = 오프스크린 화면 크기")
        pump(0.5)

        from viewer.widgets.settings_dialog import SettingsDialog

        def _settings_full(d):
            sc = d.findChild(QScrollArea)
            return sc.widget() if sc is not None else None
        capture("settings", lambda: via_exec(mw.action_open_settings), full=_settings_full)
        capture("shortcuts", lambda: via_exec(mw._edit_shortcuts))
        capture("print", lambda: via_exec(mw.action_print))

        def _twoup():
            from viewer.widgets.twoup_dialog import TwoUpSettingsDialog
            return TwoUpSettingsDialog(None, mw, preset_api=mw._merge_preset_api(), sample=str(pdf))
        capture("twoup", _twoup)
        capture("merge", lambda: via_exec(mw._on_merge_files))
        capture("image_to_pdf", lambda: via_exec(mw.action_image_to_pdf))
        capture("encrypt", lambda: via_exec(mw.action_encrypt_pdf))

        def _shot_pdf():
            # 처리기는 스크린샷이 없으면 안내만 띄운다 → app.py 와 같은 인자로 직접 만든다
            from viewer.widgets.screenshot_pdf_dialog import ScreenshotPdfDialog
            return ScreenshotPdfDialog(mw._prefs, mw)
        capture("screenshot_pdf", _shot_pdf)
        capture("help", lambda: via_exec(mw._show_usage))
        capture("about", lambda: via_exec(mw._show_about))

        def _update():
            from viewer.widgets.update_dialog import UpdateDialog
            from viewer import updater as _u
            info = {"version": "9.9.9-beta.1", "tag": "v9.9.9-beta.1",
                    "changes": [{"version": "9.9.9-beta.1", "pre": True, "date": "2026-10-09",
                                 "notes": "<!-- lang:ko -->\n## 바뀐 내용\n\n- **수정** 예시 항목\n"
                                          "<!-- lang:en -->\n## What's changed\n\n- **Fix** sample item\n",
                                 "url": ""}]}
            return UpdateDialog(info, _u.current_version(), "manual", mw)
        capture("update", _update, note="가짜 릴리스 정보")
        capture("favorites", lambda: via_exec(mw._open_favorites_manager))

        def _hyper():
            return via_exec(lambda: mw._open_hyperlink_dialog(str(pdf), 0))
        capture("hyperlink", _hyper)
        capture("line_text", lambda: via_exec(mw._open_line_text_settings))
        capture("ocr_options", lambda: via_exec(mw._on_text_need_ocr))
        capture("bookmarker", lambda: via_exec(mw.action_open_bookmarker))
        capture("crop", lambda: via_exec(lambda: mw._open_crop_dialog()))     # 261010-7(마스터 §4.7.15)

        pump(0.5)

        def _edit():
            mw.raise_()
            mw.bookmark_tree.btn_edit.setChecked(True)
            pump(0.8)
            if not mw.bookmark_tree.is_edit_mode():
                raise RuntimeError("편집 모드로 들어가지 않음")
            return mw
        capture("main_edit", _edit, note="크기 1400x900 은 스크립트가 정한 값", close=False)
        mw._edit_dirty = False
    except Exception:
        traceback.print_exc()
        code = 1
    finally:
        # 창을 닫고 배경 작업(색인 등)이 멈출 틈을 준 뒤 정리 — 다른 검사와 같은 순서
        try:
            for w in app.topLevelWidgets():
                if isinstance(w, QDialog) and w.isVisible():
                    w.done(0)
            mw._edit_dirty = False
            mw.close()
        except Exception:
            pass
        pump(1.0)
        try:
            from viewer import settings_store
            shutil.rmtree(str(settings_store.settings_dir()), ignore_errors=True)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    (out_dir / "findings.json").write_text(
        json.dumps({"lang": lang, "windows": results, "messages": msgs}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print("wrote", out_dir / "findings.json", flush=True)
    # 여기서 바로 끝낸다 — 함수가 돌아가면 지역 QApplication·창이 해제되며 Qt 종료 단계에서
    # 프로세스가 비정상 코드(실측 127)로 죽는다(종료 크래시 회피, 다른 검사와 같은 os._exit).
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


# ════════════════════════════════════════════════════════════════════════
#  요약
# ════════════════════════════════════════════════════════════════════════
def write_summary(out_root: Path):
    data = {}
    for lang in LANGS:
        f = out_root / lang / "findings.json"
        if f.exists():
            data[lang] = json.loads(f.read_text(encoding="utf-8"))
    (out_root / "findings.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    L = ["# PolyPDF UI check", "", "작은 화면 기준: %dx%d" % SMALL_SCREEN, ""]
    for lang, d in data.items():
        L += ["## %s" % lang, "",
              "| 창 | 크기 | 최소 | 잘림 | 세로 잘림 | 가로스크롤 | >1366x768 | 한글 | 겹침 | 비고 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for w in d["windows"]:
            if "skipped" in w:
                L.append("| %s | — | — | — | — | — | — | — | — | SKIP: %s |" % (w["name"], w["skipped"].replace("|", "/")))
                continue
            L.append("| %s | %dx%d | %dx%d | %d | %d | %d | %s | %s | %d | %s |" % (
                w["name"], w["size"][0], w["size"][1], w["min_hint"][0], w["min_hint"][1],
                len(w["clipped"]), len(w["vclip"]), len(w["hscroll"]), "예" if w["oversize"] else "",
                len(w["hangul"]) if lang != "ko" else "—", len(w["overlap"]), w.get("note", "")))
        L.append("")
        for w in d["windows"]:
            if "skipped" in w or not (w["clipped"] or w["vclip"] or w["hscroll"] or w["hangul"] or w["overlap"]):
                continue
            L += ["### %s / %s" % (lang, w["name"]), "", "`%s`" % w["png"], ""]
            for c in w["clipped"]:
                L.append("- 잘림 %s %r @%s — 폭 %d, 글자 %d(+%d), sizeHint %d%s%s" % (
                    c["class"], c["text"], tuple(c.get("pos") or ()), c["width"], c["need_text_px"],
                    c["need_text_px"] - c["width"],
                    c["need_sizehint"], (" (생략부호)" if c.get("elided") else "")
                    + (" — 경계값(<=4px), 스크린샷으로 확인" if c["need_text_px"] - c["width"] <= 4 else ""),
                    (" · 툴팁 %r" % c["tip"]) if c.get("tip") else ""))
            for v in w["vclip"]:
                L.append("- 세로 잘림 QLabel %r @%s — 높이 %d, 필요 %d (폭 %d)" % (
                    v["text"], tuple(v["pos"]), v["height"], v["need_height"], v["width"]))
            for h in w["hscroll"]:
                L.append("- 가로 스크롤: %s 보이는 폭 %s, 내용 %s(최소 %s)" % (
                    h["name"], h["viewport_w"], h["content_w"], h["content_min_w"]))
            for h in w["hangul"]:
                L.append("- 한글 [%s] %r" % (h["kind"], h["text"]))
            for o in w["overlap"]:
                L.append("- 겹침 %s ↔ %s %s @%s" % (o["a"], o["b"], o["overlap"], tuple(o.get("pos") or ())))
            L.append("")
    (out_root / "summary.md").write_text("\n".join(L), encoding="utf-8")
    print("wrote", out_root / "summary.md")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lang", choices=LANGS)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--only", default="", help="쉼표로 구분한 창 이름만 (예: settings,print)")
    a = ap.parse_args()
    out_root = Path(a.out)
    out_root.mkdir(parents=True, exist_ok=True)
    if a.lang:
        run_one(a.lang, out_root, [x for x in a.only.split(",") if x] or None)   # 안에서 os._exit
    # 언어마다 하위 프로세스 — 창은 만들 때 언어를 읽는다
    code = 0
    for lang in LANGS:
        print("=== %s ===" % lang, flush=True)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--lang", lang, "--out", str(out_root),
                            "--only", a.only],
                           cwd=str(PUBLIC), env=env)
        code = code or r.returncode
    write_summary(out_root)
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
