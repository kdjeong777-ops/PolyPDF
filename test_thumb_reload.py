# -*- coding: utf-8 -*-
"""260901: 스크린샷(이미지) 보기 → 원본 PDF 복귀 시 페이지 썸네일이 비던 문제 회귀 검사.

원인: 이미지 표시 경로가 `list.clear()` 만 하고 `_doc/_doc_path/_doc_mtime` 을 남겨,
같은 PDF 로 돌아오면 load_document 의 '같은 파일' 가드에 걸려 재채움이 생략됐다.
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_reload_"))
pdf = tmp / "T.pdf"
d = fitz.open()
for i in range(3):
    d.new_page(width=400, height=600).insert_text((40, 80), f"page {i}")
d.save(str(pdf)); d.close()

# 스크린샷 산출물(이미지) 대역 — 실제 앱은 PNG 를 main_view.load_image 로 연다.
png = tmp / "shot.png"
pm = fitz.open(str(pdf)); pm.load_page(0).get_pixmap(dpi=48).save(str(png)); pm.close()

app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.thumbs_list import PageThumbs
pt = PageThumbs(); pt.resize(150, 700); pt.show(); app.processEvents()

# 1) 원본 PDF 로드
pt.load_document(str(pdf)); app.processEvents()
chk(pt.list.count() == 3, "① PDF 로드 → 썸네일 3쪽", f"count={pt.list.count()}")
first_item = pt.list.item(0)

# 2) 같은 파일 재로드는 여전히 생략(2중 리프레시 방지 가드 유지)
pt.load_document(str(pdf)); app.processEvents()
chk(pt.list.item(0) is first_item, "② 같은 파일 재로드는 생략(항목 유지)")

# 3) 스크린샷 보기 = clear_document() — 상태까지 초기화되고 핸들이 풀린다
pt.clear_document(); app.processEvents()
chk(pt.list.count() == 0, "③ 이미지 표시 → 썸네일 비움", f"count={pt.list.count()}")
chk(pt._doc is None and pt._doc_path is None and pt._doc_mtime is None,
    "③ 문서 상태·핸들까지 초기화")
chk(pt._ext_docs == {}, "③ 붙여넣기 스테이징 캐시도 해제(파일 잠금 방지)")

# 4) ★ 원본 PDF 로 복귀 → 썸네일이 다시 채워져야 한다(버그 재현 지점)
pt.load_document(str(pdf)); app.processEvents()
chk(pt.list.count() == 3, "④ 원본 PDF 복귀 → 썸네일 재채움", f"count={pt.list.count()}")

# 5) 2차 안전망: 바깥에서 list.clear() 만 해도(옛 코드 경로) 재채움된다
pt.list.clear()
pt.load_document(str(pdf)); app.processEvents()
chk(pt.list.count() == 3, "⑤ 목록만 비운 경우에도 가드가 걸리지 않음",
    f"count={pt.list.count()}")

# 6) 렌더까지 실제로 되는지(빈 아이콘이 아님)
pt._render_visible(); app.processEvents()
chk(not pt.list.item(0).icon().isNull(), "⑥ 복귀 후 썸네일 이미지 렌더됨")

# 7) 앱 경로 검증 — 이미지 분기가 clear_document() 를 쓰는지(상태 초기화 누락 재발 방지)
src = Path(__file__).with_name("viewer") / "app.py"
txt = src.read_text(encoding="utf-8")
chk("self.page_thumbs.list.clear()" not in txt,
    "⑦ app.py 에 page_thumbs.list.clear() 직접 호출 없음(clear_document 로 일원화)")
chk(txt.count("self.page_thumbs.clear_document()") >= 3,
    "⑦ clear_document() 로 3곳(_load_main 이미지·_clear_workspace·핸들해제) 통일",
    f"count={txt.count('self.page_thumbs.clear_document()')}")

pt.close()
print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
