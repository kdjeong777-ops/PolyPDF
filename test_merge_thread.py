# -*- coding: utf-8 -*-
"""260611-33: 병합을 백그라운드 스레드로 — 응답성·취소·일반 병합 정확성."""
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

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow, _MergeThread
mw = MainWindow()

tmp = Path(tempfile.mkdtemp(prefix="polypdf_mthr_"))
for nm in ("A.pdf", "B.pdf"):
    d = fitz.open()
    for i in range(3):
        d.new_page(width=400, height=600).insert_text((40, 80), f"{nm}{i}")
    d.save(str(tmp / nm)); d.close()
items = [{"type": "pdf", "path": str(tmp / "A.pdf"), "name": "A"},
         {"type": "pdf", "path": str(tmp / "B.pdf"), "name": "B"}]

# 1) _run_merge_job 정상 — 별도 스레드에서 실행, 결과 ok
out = str(tmp / "merged.pdf")
prog_max = {"v": 0}
# 진행 신호를 가로채 최대 진행률 확인
res = mw._run_merge_job(lambda progress: mw._do_normal_merge(items, out, False, progress),
                        "테스트 병합")
chk(res.get("ok") and not res.get("err") and not res.get("cancelled"), "스레드 병합 성공", str(res))
chk(os.path.exists(out), "병합 출력 생성")
d = fitz.open(out)
chk(d.page_count == 6, "페이지 수 = 3+3", str(d.page_count))
d.close()

# 2) 진행률이 끝에서만 100% — 마지막 라벨 '저장 중'에서 done==total
seen = []
class _Probe(_MergeThread):
    pass
def job2(progress):
    return mw._do_normal_merge(items, str(tmp / "m2.pdf"), False,
                               lambda dn, tt, lb: (seen.append((dn, tt, lb)) or progress(dn, tt, lb)))
res2 = mw._run_merge_job(job2, "진행 확인")
chk(res2.get("ok"), "두번째 병합 성공")
mids = [d for (d, t, l) in seen[:-1]]
last = seen[-1]
chk(all(d < last[1] for d in mids) and last[0] == last[1] and "저장" in last[2],
    "중간엔 100% 아님, 마지막에 저장=100%", str(seen[-1]))

# 3) 취소 → cancelled
def job3(progress):
    return mw._do_normal_merge(items, str(tmp / "m3.pdf"), False,
                               lambda dn, tt, lb: False)   # 즉시 취소
res3 = mw._run_merge_job(job3, "취소 테스트")
chk(res3.get("cancelled") and not res3.get("ok"), "취소 시 cancelled", str(res3))

# 4) 예외 → err
def job4(progress):
    raise RuntimeError("강제 오류")
res4 = mw._run_merge_job(job4, "오류 테스트")
chk(res4.get("err") == "강제 오류" and not res4.get("ok"), "예외 시 err 전달", str(res4))

# 5) 병합 배치 사용자 스타일(프리셋) 저장/불러오기/삭제 + _apply_prefs 보존 (260611-36)
mw._merge_save_preset("스타일A", {"nup": 6, "page_size": "Letter", "crop_top": 9})
mw._merge_save_preset("스타일B", {"nup": 2})
names = [p.get("name") for p in mw._merge_get_presets()]
chk(names == ["스타일A", "스타일B"], "프리셋 저장(이름)", str(names))
mw._merge_save_preset("스타일A", {"nup": 2})   # 같은 이름 덮어쓰기
a = next(p for p in mw._merge_get_presets() if p["name"] == "스타일A")
chk(a["nup"] == 2 and len([p for p in mw._merge_get_presets() if p["name"] == "스타일A"]) == 1,
    "같은 이름 프리셋 덮어쓰기")
# _apply_prefs(빈 dict)에도 보존
from viewer.widgets.settings_dialog import SettingsDialog
mw._apply_prefs(SettingsDialog(mw._prefs).result_prefs())
chk(len(mw._merge_get_presets()) == 2, "프리셋이 설정 저장 후에도 보존")
mw._merge_delete_preset("스타일B")
chk([p["name"] for p in mw._merge_get_presets()] == ["스타일A"], "프리셋 삭제")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
