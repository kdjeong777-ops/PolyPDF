# -*- coding: utf-8 -*-
"""261108-26: 본문 읽기 네 모드를 **실제 길**로 — 단추 ▾ 메뉴에서 구간 고르기 → 단추 누르기 → 읽기 → 쪽 넘김 (영상·음성 SOT §1.5).

사용자 보고: "TTS시 '전체', '전체연속'는 전체 페이지를 읽는 건데, 현재 페이지만 읽고 마쳐. 현재 페이지만 읽는거는
'1회' 또는 '연속'이야. … '전체연속'은 끝까지 읽고 처음부터 다시 읽는거야. '연속'은 해당페이지를 끝가지 읽고 처음부터
다시 읽는 거야"

쪽 목록 함수(`_page_plan`) 만 보는 test_read_modes 는 통과했다 — 그래서 이 검사는 창을 띄우고 메뉴·단추·타이머를
그대로 거친다. 소리는 내지 않는다(가짜 TTS — 말은 곧바로 끝난 것으로).
"""
import os, sys, tempfile, shutil, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QStandardPaths, QCoreApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_read_modes_path_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


class FakeTts:
    """말은 곧바로 끝난다. 무엇을 읽었는지만 적는다."""
    def __init__(self):
        self.said = []

    def available(self):
        return True

    def speak_reading(self, text):
        self.said.append(text)
        return True

    def speak(self, text, lang="eng", queue=False):
        self.said.append(text)
        return True

    def is_speaking(self):
        return False

    def saw_speaking(self):
        return True

    def stop(self):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


PAGES = 3
root = tempfile.mkdtemp(prefix="polypdf_readpath_")
try:
    src = os.path.join(root, "doc.pdf")
    d = fitz.open()
    for i in range(PAGES):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((72, 110), "Page number %d is here." % (i + 1), fontsize=12)
        pg.insert_text((72, 140), "This sentence belongs to page %d." % (i + 1), fontsize=12)
    d.save(src); d.close()

    from viewer.app import MainWindow
    from viewer.study import tts_engine as _te
    _te._ready = False          # 261108-33: 개발 폴더에 자연 음성이 설치돼 있어도 이 검사는 가짜 SAPI 로(엔진 고르기는 test_tts_neural)
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1800, 1000); mw.show(); app.processEvents()
    tts = FakeTts()
    mw._study_get_tts = lambda: tts
    mw._maybe_offer_ocr = lambda *a, **k: False
    mw._load_main(HistoryItem(src, 0, "", "bookmark")); QTest.qWait(800)
    m = mw.main_view
    ra = mw.read_aloud
    btn = mw.btn_read
    chk(m.current_file() is not None and ra._page_count() == PAGES,
        "준비 — 본문에 %d쪽 PDF" % PAGES, "page_count=%s" % ra._page_count())

    def pick(label):
        """단추의 ▾ 메뉴에서 그 구간을 누른다(사용자 길 — 액션 trigger)."""
        menu = btn.menu()
        for a in menu.actions():
            if a.isCheckable() and a.text() == label:
                a.trigger(); app.processEvents()
                return True
        return False

    def run(label, start_page, budget_s=6.0, stop_after_pages=None):
        """구간 고르기 → 그 쪽에서 단추 누르기 → 끝나거나 쪽 수가 차면 그친다. 읽은 쪽 차례를 돌려준다."""
        if ra.is_active():
            ra.stop()
        tts.said.clear()
        m.go_to_page(start_page); QTest.qWait(150)
        ok = pick(label)
        btn.click(); app.processEvents()
        seen = []
        t0 = time.time()
        while time.time() - t0 < budget_s:
            QTest.qWait(40)
            p = ra._reading_page if ra.is_active() else None
            if p is not None and (not seen or seen[-1] != p):
                seen.append(p)
            if not ra.is_active():
                break
            if stop_after_pages and len(seen) >= stop_after_pages:
                break
        active = ra.is_active()
        if active:
            ra.stop()
        return ok, seen, active

    print("=== 1회 — 지금 쪽 한 번, 멈춘다 ===")
    ok, seen, active = run("1회", 1)
    chk(ok and ra.mode == "1회", "1회 — 메뉴에서 고르면 모드가 바뀐다", ra.mode)
    chk(seen == [1] and not active, "1회 — 2쪽만 읽고 멈춘다", str(seen))
    chk(btn.text().strip() == "1회", "1회 — 단추 글자가 지금 구간", btn.text())

    print("=== 연속 — 지금 쪽을 되풀이 ===")
    ok, seen, active = run("연속", 1, stop_after_pages=99, budget_s=2.5)
    chk(ok and ra.mode == "연속", "연속 — 모드", ra.mode)
    n2 = sum(1 for s in tts.said if "page 2" in s)
    chk(seen == [1] and active and n2 >= 2, "연속 — 2쪽을 되풀이(멈추지 않는다)",
        "seen=%s active=%s 2쪽 문장 %d번" % (seen, active, n2))

    print("=== 전체 — 지금 쪽~끝, 멈추고 시작한 쪽으로 ===")
    ok, seen, active = run("전체", 1)
    chk(ok and ra.mode == "전체", "전체 — 모드", ra.mode)
    chk(seen == [1, 2] and not active, "전체 — 2쪽부터 끝(3쪽)까지 읽고 멈춘다", str(seen))
    chk(m.current_page() == 1, "전체 — 끝나면 시작한 쪽으로", str(m.current_page()))

    print("=== 전체연속 — 지금 쪽~끝 뒤 1쪽~끝 되풀이 ===")
    ok, seen, active = run("전체연속", 1, stop_after_pages=5, budget_s=8.0)
    chk(ok and ra.mode == "전체연속", "전체연속 — 모드", ra.mode)
    chk(seen[:5] == [1, 2, 0, 1, 2], "전체연속 — 2·3쪽 뒤 1쪽부터 되풀이", str(seen))

    print("=== 설정 복원 뒤 단추·메뉴가 모드와 맞는다 ===")
    # 저장된 구간이 '전체' 인 채로 창이 뜨면 단추 글자·메뉴 체크도 '전체' 여야 한다
    #   (글자만 '전체' 이고 속 모드가 다르면 사용자는 '전체' 로 읽는 줄 안다)
    #   설정 복원은 `self.read_aloud.mode = ra["mode"]` 한 줄 — 단추를 만든 뒤에 온다(_build_ui → _restore_settings)
    ra.mode = "1회"
    app.processEvents()
    for i, b in enumerate(getattr(mw, "_read_btns", [btn])):
        menu = b.menu()
        checked = [a.text() for a in menu.actions() if a.isCheckable() and a.isChecked()
                   and a.text() in ("1회", "연속", "전체", "전체연속")]
        chk(b.text().strip() == "1회" and checked == ["1회"],
            "복원 — 모드가 바뀌면 %d번 창 단추 글자·메뉴 체크가 따라온다" % (i + 1),
            "글자=%s 체크=%s" % (b.text(), checked))
    # 2번 창 단추 메뉴에서 고르면 1번 창 단추도
    bs = getattr(mw, "_read_btns", [])
    if len(bs) > 1:
        for a in bs[1].menu().actions():
            if a.isCheckable() and a.text() == "연속":
                a.trigger()
        app.processEvents()
        chk(bs[0].text().strip() == "연속", "다른 창 단추에서 고른 구간이 이 창 단추 글자에도", bs[0].text())
    # 실제 복원 길 — '1회' 로 두고 창을 닫으면(설정 저장) 다시 띄운 창의 단추 글자도 '1회' 여야 한다
    ra.mode = "1회"
    mw.close(); app.processEvents(); QTest.qWait(200)
    mw2 = MainWindow(); mw2.show(); app.processEvents(); QTest.qWait(200)
    chk(mw2.read_aloud.mode == "1회", "다시 띄움 — 저장된 구간이 복원된다", mw2.read_aloud.mode)
    chk(mw2.btn_read.text().strip() == "1회",
        "다시 띄움 — 단추 글자가 복원된 구간(종전: 기본 '전체' 로 보이고 1회로 읽었다)", mw2.btn_read.text())
    mw2.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
