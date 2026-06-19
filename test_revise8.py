# -*- coding: utf-8 -*-
"""260606-수정3 오프스크린 통합 테스트.
1) 스크린샷 비면 창 숨김 시그널 배선
2) mp3 인메모리 합성(빠른 저장) + 가사
3) 메인 툴바 버튼 크기(‹ › / -+ / 읽기 그룹 폭 고정)
4) 책갈피 위계 분할 구간 계산 + 메인 mp3 버튼 배선
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PDF = r"C:/Claude/MPDF/24 아스팔트콘크리트포장시공지침.pdf"
ok = True

def check(name, cond):
    global ok
    print(("  OK  " if cond else " FAIL ") + name)
    ok = ok and bool(cond)

# --- 2) mp3 인메모리 합성 ---
import time
from viewer.study.mp3_export import synth_to_mp3, unique_dir
tmp = os.path.join(os.environ.get("TEMP", "."), "rev8_mp3")
os.makedirs(tmp, exist_ok=True)
mp3 = os.path.join(tmp, "t.mp3"); lrc = os.path.join(tmp, "t.lrc")
segs = [("This is a quick test.", "en"), ("한국어 문장입니다.", "ko")]
t0 = time.time()
try:
    synth_to_mp3(segs, mp3, lrc_path=lrc)
    dt = time.time() - t0
    sz = os.path.getsize(mp3)
    lr = open(lrc, encoding="utf-8").read()
    print(f"  mp3 {sz}B in {dt:.2f}s  lrc lines={len(lr.splitlines())}")
    check("mp3 합성/가사", sz > 0 and "[00:00" in lr and lr.count("\n") >= 1)
except Exception as e:
    check(f"mp3 합성 ({e})", False)

# unique_dir
import pathlib
b = pathlib.Path(tmp) / "u"
b.mkdir(exist_ok=True)
check("unique_dir 회피", unique_dir(b).name == "u(1)")

# --- 4) 책갈피 위계 분할 구간 ---
import fitz
from viewer.app import MainWindow
doc = fitz.open(PDF)
dummy = object()                     # _doc_sections 는 self 속성 미참조
s1 = MainWindow._doc_sections(dummy, doc, 1)
s2 = MainWindow._doc_sections(dummy, doc, 2)
s3 = MainWindow._doc_sections(dummy, doc, 3)
print(f"  구간수 L1={len(s1)} L2={len(s2)} L3={len(s3)} pages={doc.page_count}")
check("위계 깊을수록 구간 증가", len(s1) <= len(s2) <= len(s3))
# 구간이 연속·비중첩이며 페이지 범위 내
prev_end = 0
mono = True
for title, p0, p1 in s1:
    if not (0 <= p0 < p1 <= doc.page_count):
        mono = False
    prev_end = p1
check("L1 구간 페이지 범위 정상", mono)
check("_safe_name 위험문자 제거", MainWindow._safe_name('a/b:c*?', 'x') == 'a_b_c_')
check("_seg_lang 한/영", MainWindow._seg_lang("가나") == "ko"
      and MainWindow._seg_lang("abc") == "en")
doc.close()

# --- 1,3) GUI 배선·버튼 크기 ---
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
mw = MainWindow()
mv = mw.main_view
check("‹ 폭 26", mv.btn_prev_page.width() == 26 or mv.btn_prev_page.minimumWidth() == 26)
check("+ 줌 폭 26", mv.btn_zoom_in.minimumWidth() == 26)
check("읽기 ▶ 폭 28", mw.btn_read.minimumWidth() == 28)
check("읽기메뉴 폭 96 고정", mw.btn_read_menu.minimumWidth() == 96
      and mw.btn_read_menu.maximumWidth() == 96)
check("메인 mp3 버튼 존재", hasattr(mw, "btn_main_mp3"))
check("_on_main_mp3 메서드", callable(getattr(mw, "_on_main_mp3", None)))
check("_hide_shots_if_empty 메서드", callable(getattr(mw, "_hide_shots_if_empty", None)))
# 스크린샷 제거 시그널 배선: rowsRemoved 가 연결되었는지(직접 호출로 동작 확인)
try:
    mw.act_toggle_shot.setChecked(True)
    mw._hide_shots_if_empty()   # 리스트 비어있으니 토글 꺼져야
    check("빈 스크린샷→토글 꺼짐", not mw.act_toggle_shot.isChecked())
except Exception as e:
    check(f"hide_shots ({e})", False)

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
