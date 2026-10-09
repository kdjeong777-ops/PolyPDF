"""PolyPDF - 진입점."""
from __future__ import annotations
import sys
import os
import shutil
from pathlib import Path


def _ensure_module_search_path() -> None:
    """`viewer` 패키지 위치를 sys.path 에 보장.

    - 일반 실행: main.py 가 있는 폴더(= 프로젝트 루트)를 sys.path 에 추가.
    - PyInstaller --onefile: 부팅 시 `_MEIPASS` 임시 폴더에 해제된 모듈 위치를 추가.

    빌드시 `--hidden-import viewer.app` 이 있어도 PyInstaller 가
    local `viewer` 패키지를 표준 import 로 못 찾으면 일부 모듈이 번들에서 누락될 수 있음.
    그 경우 _MEIPASS 안에 viewer/ 가 풀려 있으므로 sys.path 추가만으로 복구 가능.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller onefile 부팅 후 해제 디렉토리
        base = getattr(sys, '_MEIPASS', None) or os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    if base and base not in sys.path:
        sys.path.insert(0, base)


_ensure_module_search_path()

# 261009-16(응답성 SOT §4 ③): 한국어 띄어쓰기(kiwi) 자식 프로세스로 불렸으면 — PyQt 를 싣기 **전에** 여기서 끝낸다.
#   kiwi 를 짓는 1.2초 동안 GIL 을 쥐어 창이 섰다. 다른 프로세스면 GIL 을 나누지 않는다(`viewer/kiwi_space.py`).
if __name__ == "__main__" and len(sys.argv) >= 3 and sys.argv[1] == "--kiwi-space-server":
    from viewer.kiwi_space import serve
    serve(sys.argv[2])
    os._exit(0)
# 261009-19(응답성 SOT §4 ③): 색인 자식 프로세스 — 같은 까닭(PyMuPDF 의 C 호출이 GIL 을 쥔다). 창은 띄우지 않는다.
if __name__ == "__main__" and len(sys.argv) >= 3 and sys.argv[1] == "--index-server":
    from viewer.index_proc import serve as _index_serve
    _index_serve(sys.argv[2])
    os._exit(0)

# 260606-28: 무거운 import(fitz/viewer.app→kiwipiepy·study 등)는 스플래시 표시 후로
# 미뤄 클릭 즉시 중앙 아이콘이 뜨도록 함. 여기선 가벼운 PyQt 만 선로딩.
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from viewer.resources_path import resource_path


def _profile() -> str:
    """261009-19(마스터 §14.2.1·§14.5 U19): `POLYPDF_PROFILE=test` 면 앱 이름이 `PolyPDF-test` — 설정·색인·창 기록·QSettings 가
    **사용자 실제 폴더와 갈린다**. 시험 도구가 실제 설정을 백업·복원·삭제하다 사용자 색인을 지운 일이 있었다
    (Claude 앱 셸은 설정 폴더 복사본을 보는데 삭제는 실제 폴더에 닿았다). 영문·숫자·`-_` 만, 32자까지."""
    import re
    return re.sub(r"[^A-Za-z0-9_-]", "", os.environ.get("POLYPDF_PROFILE", ""))[:32]


def _migrate_appdata() -> None:
    """v1.6.15: 프로그램명 변경(Smart PDF Viewer→PolyPDF)으로 AppData 경로가
    바뀌므로, 기존 settings.json/index.db/스크린샷을 신 폴더로 1회 복사.

    setApplicationName 호출 이후에만 정확한 신 경로를 얻을 수 있음.
    구 폴더는 보존(삭제 안 함). 실패해도 앱은 계속.
    """
    if _profile():
        return                       # 261009-19: 시험 프로필은 옛 폴더를 끌어오지 않는다
    try:
        from PyQt6.QtCore import QStandardPaths
        new_dir = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation))
        old_dir = new_dir.parent / "Smart PDF Viewer"
        if old_dir.exists() and not (new_dir / "settings.json").exists():
            new_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(old_dir, new_dir, dirs_exist_ok=True)
    except Exception:
        pass


def _study_selftest(pdf_path: str) -> None:
    """frozen 진단: study 파이프라인(OCR+kiwipiepy+vocab)을 GUI 없이 실행해 로그 기록.
    POLYPDF_STUDY_SELFTEST=<pdf> 로 트리거. 네이티브 크래시 시 로그의 마지막 줄이 죽은 지점."""
    import time, traceback
    log = Path(os.environ.get("POLYPDF_STUDY_SELFTEST_LOG",
                              str(Path(pdf_path).with_suffix(".selftest.log"))))

    def w(m):
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {m}\n")

    try:
        log.write_text("", encoding="utf-8")
        w(f"frozen={getattr(sys,'frozen',False)} meipass={getattr(sys,'_MEIPASS',None)}")
        import fitz
        from viewer.study import ocr, vocab as V
        from viewer.study.study_store import StudyStore, file_key_for
        info = ocr.ensure_tesseract()
        w(f"tesseract ok={info.get('ok')} ver={info.get('version')} err={info.get('error')}")
        db = log.with_suffix(".db")
        if db.exists():
            db.unlink()
        store = StudyStore(db)
        fk = file_key_for(pdf_path)
        doc = fitz.open(pdf_path)
        w(f"opened {doc.page_count}p")
        store.set_meta(fk, str(pdf_path), doc.page_count, "kor")
        for i in [0, 1, 299, 300, 301, 437]:
            if i < doc.page_count:
                r = ocr.build_page(doc, i, lang="kor", dpi=300)
                store.save_page(fk, i, r["text"], dpi=r["dpi"], engine=r["engine"],
                                source=r["source"], conf=r["conf"], words=r["words"], lang="kor")
                w(f"page {i+1}: src={r['source']} words={len(r['words'])}")
        w("build_vocab start (kiwipiepy)...")
        s = V.build_vocab(store, fk, "kor")
        w(f"build_vocab OK: {s}")
        store.close()
        doc.close()
        w("SELFTEST DONE OK")
    except Exception:
        w("SELFTEST EXC:\n" + traceback.format_exc())


ERROR_LOG_NAME = "error.log"
ERROR_LOG_MAX = 1_000_000          # 이보다 커지면 비우고 새로 적는다(설정 폴더를 불리지 않게)


def _install_language(app) -> None:
    """261008(다국어 SOT §3.6): 화면 언어를 정하고 번역·Qt 기본 번역을 설치한다.

    ★ `setApplicationName` **뒤**여야 한다 — 설정 폴더가 앱 이름으로 정해진다(마스터 §14.2.1).
    ★ 창을 만들기 **전**이어야 한다 — 창은 문구를 `__init__` 에서 정한다(그래서 언어 변경은 재시작).
    설정은 `peek_pref` 로 언어만 읽는다(`load()` 의 마이그레이션·백업을 두 번 하지 않게).
    설정에 언어가 없으면 처음 정하는 규칙(설정 파일 있음 → ko, 없음 → 설치 언어·OS 언어)."""
    try:
        from viewer import i18n, settings_store
        code = settings_store.peek_pref("language")
        if not code:
            code = i18n.initial_language(settings_store.settings_path().exists())
        i18n.install(app, code)
    except Exception:
        pass                 # 언어를 못 정해도 한국어(원문)로 뜬다


def _install_excepthook() -> None:
    """261008-1(마스터 §14.7.3, 사용자 결정): 처리 안 된 Python 예외가 **앱을 끄지 않게**.

    PyQt6 은 `sys.excepthook` 이 기본값이면 Qt 슬롯 안의 처리 안 된 예외에서 `qFatal` 을
    부른다 → `Qt6Core.dll … 0xC0000409` 로 창이 그냥 사라진다. 같은 '꺼짐' 을 260915-3(채우기 틱),
    260930-4(클립보드 사진), 261008-1(이름 변경)에 겪었다 — 원인은 매번 다른 한 줄이었다.
    원인은 그때그때 고치되, 그 한 줄이 사용자의 작업 전체를 날리지 않도록 **기록하고 계속**한다.
      - 기록: 설정 폴더 `error.log`(시각·예외·호출 경로). 다음 원인 찾기의 근거다.
      - 알림: 열린 창의 상태줄에 한 줄. 대화상자는 띄우지 않는다(같은 예외가 연달아 나면 창이 쌓인다).
    ※ 테스트는 저마다 `sys.excepthook` 을 바꿔 예외를 모은다 — 이것은 앱 진입점에서만 건다.
    """
    import traceback
    import time

    def _hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        try:
            sys.stderr.write(text)
        except Exception:
            pass
        try:
            from PyQt6.QtCore import QStandardPaths
            d = Path(QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation))
            d.mkdir(parents=True, exist_ok=True)
            log = d / ERROR_LOG_NAME
            mode = "w" if log.exists() and log.stat().st_size > ERROR_LOG_MAX else "a"
            with open(log, mode, encoding="utf-8") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}\n")
        except Exception:
            pass
        try:
            for w in QApplication.topLevelWidgets():
                sb = getattr(w, "status", None)
                if sb is not None and hasattr(sb, "showMessage") and w.isVisible():
                    sb.showMessage(f"오류가 났지만 계속합니다: {etype.__name__}: {value} "
                                   f"(설정 폴더 {ERROR_LOG_NAME})", 10000)
                    break
        except Exception:
            pass

    sys.excepthook = _hook


def _make_splash(icon_path):
    """260606-28: 실행 즉시 화면 중앙에 뜨는 아이콘 스플래시.

    onedir 빌드라 부트로더 추출 지연은 없고, 체감 지연은 무거운 import
    (fitz/kiwipiepy/study)에서 발생 → QApplication 직후 이 스플래시를 띄우면
    클릭 즉시 '실행 중' 피드백이 보인다. 본 창이 뜨면 스르륵 사라진다.
    """
    from PyQt6.QtWidgets import QSplashScreen
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QBrush
    from PyQt6.QtCore import QRect, QSize
    W, H = 300, 340
    canvas = QPixmap(W, H)
    canvas.fill(QColor(0, 0, 0, 0))            # 투명 배경
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # 둥근 카드
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(40, 40, 44)))
    p.drawRoundedRect(QRect(0, 0, W, H), 18, 18)
    # 아이콘
    icon_drawn = False
    if icon_path:
        ip = QPixmap(icon_path)
        if not ip.isNull():
            ip = ip.scaled(QSize(160, 160), Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((W - ip.width()) // 2, 56, ip)
            icon_drawn = True
    if not icon_drawn:
        p.setPen(QColor(235, 235, 235))
        f = QFont(); f.setPointSize(40); f.setBold(True); p.setFont(f)
        p.drawText(QRect(0, 56, W, 160), Qt.AlignmentFlag.AlignCenter, "PDF")
    # 제목 / 안내
    p.setPen(QColor(240, 240, 240))
    f = QFont(); f.setPointSize(20); f.setBold(True); p.setFont(f)
    p.drawText(QRect(0, 228, W, 36), Qt.AlignmentFlag.AlignCenter, "PolyPDF")
    p.setPen(QColor(170, 170, 175))
    f2 = QFont(); f2.setPointSize(11); p.setFont(f2)
    p.drawText(QRect(0, 270, W, 28), Qt.AlignmentFlag.AlignCenter, "실행 중…")
    p.end()

    splash = QSplashScreen(
        canvas,
        Qt.WindowType.SplashScreen | Qt.WindowType.WindowStaysOnTopHint)
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    return splash


def _fade_out_splash(app, splash, win):
    """본 창이 뜨면 스플래시를 부드럽게 페이드아웃 후 닫음."""
    from PyQt6.QtCore import QTimer
    state = {"op": 1.0}
    timer = QTimer(win)

    def _step():
        state["op"] -= 0.10
        if state["op"] <= 0:
            timer.stop()
            try:
                splash.finish(win)
            except Exception:
                splash.close()
        else:
            splash.setWindowOpacity(state["op"])

    timer.timeout.connect(_step)
    timer.start(28)                 # ~10스텝 ≈ 0.28초
    win._splash_fade_timer = timer  # GC 방지
    win._splash_ref = splash


def main():
    _st = os.environ.get("POLYPDF_STUDY_SELFTEST")
    if _st:
        # 셀프테스트 경로는 fitz 가 필요 — 지연 import
        _study_selftest(_st)
        return
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass
    app = QApplication(sys.argv)

    # 260915-3(마스터 §4.9, 사용자 지시): 탐색기에서 PDF 여러 개를 골라 열면 Windows 가 파일마다
    #   따로 실행한다 → 먼저 뜬 실행(대표)에게 파일을 넘기고 이 실행은 창 없이 끝난다.
    #   스플래시·무거운 준비 **전에** 해야 창이 번쩍이지 않는다.
    pdf_args = [a for a in sys.argv[1:] if a.lower().endswith(".pdf") and os.path.exists(a)]
    gather = None
    if pdf_args:
        try:
            from viewer.open_gather import OpenGather, hand_off
            gather = OpenGather()
            if not gather.claim():
                gather = None
                if hand_off(pdf_args):
                    os._exit(0)
        except Exception:
            gather = None

    # 260606-29: ★ QApplication 직후 — 무엇보다 먼저 스플래시(앱이름/아이콘/마이그레이션
    #            보다 앞). repaint() 로 동기 즉시 페인트 → 체감 지연 최소화.
    _ico = resource_path("icon.png")
    splash = None
    try:
        splash = _make_splash(_ico)
        splash.show()
        splash.repaint()           # 동기 페인트(이벤트 루프 대기 없이 즉시)
        app.processEvents()
    except Exception:
        splash = None

    # 스플래시가 뜬 뒤 나머지 초기 설정(모두 가벼움)
    app.setApplicationName("PolyPDF" + ("-" + _profile() if _profile() else ""))   # 261009-19: 시험 프로필은 다른 폴더
    app.setOrganizationName("LocalTools")
    if _ico:
        app.setWindowIcon(QIcon(_ico))    # v1.6.1 G1: 작업표시줄/타이틀바 아이콘

    _migrate_appdata()       # v1.6.15: 구 'Smart PDF Viewer' AppData 1회 이전
    _install_excepthook()    # 261008-1(§14.7.3): 처리 안 된 예외로 창이 사라지지 않게(앱 이름 뒤 — 기록 폴더)
    _install_language(app)   # 261008(다국어 SOT §3.6): 앱 이름 뒤·창 만들기 전 — 화면 언어 + Qt 기본 번역

    # --- 여기서부터 무거운 로딩(스플래시가 보이는 동안 진행) ---
    import fitz                                  # v1.3.0 C: PyMuPDF AA 레벨
    try:
        fitz.TOOLS.set_aa_level(8)
    except Exception:
        pass
    from viewer.app import MainWindow

    win = MainWindow()
    # 261009-14(응답성 SOT §4.2·§12): 인자로 받은 PDF 가 있으면 지난 세션을 복원하지 않는다. 복원이 인자 열기보다 먼저
    #   줄을 서서 '이미 연 것이 있으면 덮지 않는다' 가드가 작동하지 않았다 — 지난 폴더(다운로드)를 메인에서 훑느라
    #   4.4초 선 뒤에야 요청한 파일을 열었다(설치본 실측). 이벤트 루프가 돌기 전이라 복원보다 앞선다.
    win._startup_has_args = bool(pdf_args)
    win.show()
    if splash is not None:
        _fade_out_splash(app, splash, win)
    # 260611-11: 인자로 받은 PDF 열기 — '연결 프로그램/기본 PDF 뷰어'로 더블클릭/Open with 지원.
    try:
        if pdf_args:
            from PyQt6.QtCore import QTimer
            state = {"opened": False}

            def _open_initial():
                # 260915-3(§4.9): 이 실행의 파일 + 그새 넘겨받은 파일을 한 번에(여럿이면 파일 모드 목록)
                files = list(pdf_args) + (list(gather.pending) if gather is not None else [])
                state["opened"] = True
                if len(files) > 1:
                    win.open_pdfs(files)
                else:
                    win.open_pdf(Path(files[0]))
                if gather is not None:
                    gather.close_after()          # 창이 뜬 뒤 잠깐만 더 받는다

            if gather is not None:
                gather.filesReceived.connect(
                    lambda fs: win.add_pdfs(fs) if state["opened"] else None)
            QTimer.singleShot(0, _open_initial)
    except Exception:
        pass
    code = app.exec()

    # 260628-14: ★ 종료 크래시 회피 — 이벤트 루프가 끝난 뒤 **즉시** 프로세스를 끝낸다.
    #
    #   증상: 창을 정상적으로 닫아도 Windows 이벤트 로그에 매번
    #     `PolyPDF.exe … Qt6Core.dll … 0xC0000409`(STATUS_STACK_BUFFER_OVERRUN) 가 쌓이고
    #     WER 보고가 뜬다(2026-08-29 사용자 보고, 설치본·개발본 양쪽 재현).
    #     오프스크린 테스트에서 겪은 것과 **같은 원인**으로, 거기서도 `os._exit` 로 우회했다(§14.7).
    #
    #   여기는 `app.exec()` 가 반환한 뒤 = **모든 저장이 끝나고**(closeEvent 에서 QSettings·
    #   settings.json 기록) 남은 일이 Qt 객체 소멸뿐인 지점이다. 그 소멸이 바로 죽는 곳이라
    #   건너뛴다. ※ closeEvent 안에서 부르면 안 된다 — `mw.close()` 를 쓰는 오프스크린
    #     테스트까지 프로세스가 죽고, Qt 콜백 안에서의 ExitProcess 는 오히려 더 위험하다
    #     (실제로 테스트 5개가 깨져 이 자리로 옮겼다).
    #   ※ `os._exit` 는 atexit 를 건너뛴다. 그렇다고 `atexit._run_exitfuncs()` 를 부르면
    #     **그 안에서 바로 이 크래시가 난다**(2026-08-29 표식 추적으로 확인 — app.exec() 반환
    #     직후 표식은 찍히고 그 다음 표식이 안 찍혔다). PyQt 등이 등록한 정리가 결국 같은
    #     Qt teardown 을 타기 때문이다. → **일괄 실행하지 않는다.**
    #     우리 쪽 정리(인쇄 임시폴더)는 closeEvent 에서 이미 끝낸다.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


if __name__ == "__main__":
    main()
