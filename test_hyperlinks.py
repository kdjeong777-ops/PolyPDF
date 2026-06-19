"""260609-3 (C): 하이퍼링크 저장소·보안 검증 단위 테스트."""
import os, sys, tempfile
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from pathlib import Path
from viewer.hyperlinks import (
    HyperlinkStore, validate_file_target, validate_url, is_safe_to_open_file,
)

fails = []
def chk(c, m):
    print(("PASS" if c else "FAIL"), "-", m)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_hl_"))
base = tmp / "folder"; base.mkdir()
(sub := base / "media").mkdir()
# 허용 파일들
good_pdf = base / "doc.pdf"; good_pdf.write_text("x")
good_mp4 = sub / "clip.mp4"; good_mp4.write_text("x")
# 차단 파일
bad_exe = base / "run.exe"; bad_exe.write_text("x")
# 폴더 밖 파일
outside = tmp / "outside.pdf"; outside.write_text("x")
# 현재 보고 있는 PDF(키 기준)
cur = base / "main.pdf"; cur.write_text("x")

# --- 파일 검증 ---
ok, rel = validate_file_target(base, good_pdf)
chk(ok and rel == "doc.pdf", "허용 PDF → 상대경로")
ok, rel = validate_file_target(base, good_mp4)
chk(ok and rel == "media/clip.mp4", "하위폴더 mp4 허용 + 상대경로(/)")
ok, err = validate_file_target(base, bad_exe)
chk(not ok, "실행파일(.exe) 차단")
ok, err = validate_file_target(base, outside)
chk(not ok, "폴더 밖 파일 차단(경로 봉쇄)")
ok, err = validate_file_target(base, base / "nope.pdf")
chk(not ok, "존재하지 않는 파일 차단")

# --- URL 검증 ---
ok, u = validate_url("https://youtu.be/abc123")
chk(ok, "youtu.be https 허용")
ok, u = validate_url("https://www.youtube.com/watch?v=x")
chk(ok, "youtube.com 서브도메인 허용")
ok, e = validate_url("http://youtube.com/x")
chk(not ok, "http 차단(https 전용)")
ok, e = validate_url("https://evil.com/x")
chk(not ok, "허용목록 밖 도메인 차단")
ok, e = validate_url("javascript:alert(1)")
chk(not ok, "javascript: 차단")
ok, e = validate_url("https://youtube.com.evil.com/x")
chk(not ok, "유사 도메인(youtube.com.evil.com) 차단")

# --- 저장소 왕복 ---
st = HyperlinkStore(base)
ok, msg = st.add_file_link(cur, 5, "강의자료", good_pdf)
chk(ok, "add_file_link 성공")
ok, msg = st.add_url_link(cur, 5, "영상", "https://youtu.be/abc")
chk(ok, "add_url_link 성공")
ok, msg = st.add_file_link(cur, 5, "악성", bad_exe)
chk(not ok, "add_file_link 실행파일 거부")
links = st.links_for(cur, 5)
chk(len(links) == 2, "페이지 5 링크 2개")
chk(st.pages_with_links(cur) == {5}, "pages_with_links={5}")
chk(st.save(), "사이드카 저장")
chk((base / "hyperlinks.json").exists(), "hyperlinks.json 생성")

# 재로드 영속
st2 = HyperlinkStore(base)
chk(len(st2.links_for(cur, 5)) == 2, "재로드 후 링크 유지")
# 실행 직전 재검증
abspath = is_safe_to_open_file(base, "doc.pdf")
chk(abspath and Path(abspath) == good_pdf.resolve(), "is_safe_to_open_file 통과")
chk(is_safe_to_open_file(base, "../outside.pdf") is None, "실행직전 .. 우회 차단")
chk(is_safe_to_open_file(base, "run.exe") is None, "실행직전 exe 차단")
# 삭제
chk(st2.remove_link(cur, 5, 0), "remove_link")
chk(len(st2.links_for(cur, 5)) == 1, "삭제 후 1개")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
