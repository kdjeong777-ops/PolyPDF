"""260609-3 (C): 하이퍼링크 앱 통합 테스트 (offscreen)."""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from viewer.app import MainWindow

SRC_PDF = r"C:\Claude\MPDF\24 아스팔트콘크리트포장시공지침.pdf"

fails = []
def chk(c, m):
    print(("PASS" if c else "FAIL"), "-", m)
    if not c: fails.append(m)

# 폴더에 PDF + 작업파일 + 실행파일 준비
folder = Path(tempfile.mkdtemp(prefix="polypdf_hlint_"))
pdf = folder / "main.pdf"; shutil.copy(SRC_PDF, pdf)
movie = folder / "clip.mp4"; movie.write_text("x")
exe = folder / "bad.exe"; exe.write_text("x")
report = folder / "report.pdf"; shutil.copy(SRC_PDF, report)   # 비미디어 파일(기본앱 경로 검증용)

app = QApplication.instance() or QApplication(sys.argv)
# offscreen: 모달 메시지박스는 블록되므로 무력화
from PyQt6.QtWidgets import QMessageBox
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
mw = MainWindow(); mw.resize(1100, 800); mw.show(); app.processEvents()

# 폴더 컨텍스트 + 파일 로드
mw._folder = folder
mw._mv[0].load_document(str(pdf)); app.processEvents()
mw._refresh_page_hyperlinks(0)

st = mw._ensure_hyperlink_store()
chk(st is not None, "폴더에 HyperlinkStore 생성")

# 파일 링크(허용)·실행파일(거부)·URL(허용)
ok, _ = st.add_file_link(str(pdf), 0, "동영상", str(movie))
chk(ok, "mp4 파일 링크 등록")
ok, _ = st.add_file_link(str(pdf), 0, "악성", str(exe))
chk(not ok, "exe 등록 거부")
ok, _ = st.add_url_link(str(pdf), 0, "영상", "https://youtu.be/abc")
chk(ok, "youtube URL 등록")
ok, _ = st.add_url_link(str(pdf), 0, "나쁨", "http://evil.com")
chk(not ok, "비허용 URL 거부")

# 오버레이 갱신 → 버튼 2개(파일+URL)
mw._mv[0].go_to_page(0); app.processEvents()
mw._refresh_page_hyperlinks(0); app.processEvents()
n = len(mw._mv[0]._hl_buttons)
chk(n == 2, f"페이지0 오버레이 버튼 2개 (got {n})")
chk(mw._mv[0]._hl_overlay.isVisible(), "오버레이 표시")

# 다른 페이지로 가면 버튼 사라짐
mw._mv[0].go_to_page(3); app.processEvents()
mw._refresh_page_hyperlinks(0)
chk(len(mw._mv[0]._hl_buttons) == 0, "링크 없는 페이지 → 버튼 0")

# 실행: 파일/URL 각각 opener 가 호출되는지(monkeypatch)
opened = []
import viewer.app as appmod
from PyQt6.QtGui import QDesktopServices
orig = QDesktopServices.openUrl
QDesktopServices.openUrl = staticmethod(lambda u: opened.append(u.toString()) or True)
try:
    mw._launch_hyperlink({"kind": "file", "target": "report.pdf"})   # 비미디어 → 기본앱
    mw._launch_hyperlink({"kind": "url", "target": "https://youtu.be/abc"})
    # 260611-85: 미디어(사진/동영상) 링크는 기본앱이 아니라 전체화면 오버레이로
    before = len(opened)
    mw._launch_hyperlink({"kind": "file", "target": "clip.mp4"})
    chk(len(opened) == before, "미디어 링크는 기본앱 호출 안 함(전체화면 오버레이)")
    chk(getattr(mw, "_media_overlay", None) is not None, "미디어 오버레이 생성됨")
    ov = getattr(mw, "_media_overlay", None)
    if ov is not None:
        ov.close()
    # 보안: 폴더밖/실행파일/비허용URL은 열리지 않음
    before = len(opened)
    mw._launch_hyperlink({"kind": "file", "target": "bad.exe"})
    mw._launch_hyperlink({"kind": "file", "target": "../escape.pdf"})
    mw._launch_hyperlink({"kind": "url", "target": "http://evil.com"})
    chk(len(opened) == before, "보안 위반 링크는 실행 안 됨")
    chk(any("report.pdf" in o for o in opened), "비미디어 파일 링크 실행(기본앱)")
    chk(any("youtu.be" in o for o in opened), "URL 링크 실행(브라우저)")
finally:
    QDesktopServices.openUrl = orig

# 저장/재로드
chk(st.save(), "사이드카 저장")
chk((folder / "hyperlinks.json").exists(), "hyperlinks.json 생성")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
mw.close()
