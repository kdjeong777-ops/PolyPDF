# -*- coding: utf-8 -*-
"""261112-17: PDF → HWPX 의 그림이 모두 `content.hpf` manifest 에 등록되는가 (형식 변환 SOT §4.2 '저장 전 그림 목록 맞추기').

사용자 보고: "pdf를 hwpx로 변환시 그림이 깨짐 (모두 없음)" — 별첨4(37쪽) 모양 그대로 변환본에서 BinData 그림 195개·본문 참조 195개는
있었지만 manifest 에는 첫 그림 하나만 있었고, 한글 2022 로 PDF 를 찍으면 그림이 1개만 나왔다(고친 뒤 195개). python-hwpx 6.6.0 이
구역을 더한 문서를 저장할 때 문서 개체가 처음 잡은 manifest 로 덮어쓴 탓. 종전 검사(test_convert_hwpx_261014)는 BinData·<hp:pic> 만 셌다.
  A  모양 그대로(쪽마다 구역): 모든 BinData 그림이 manifest 항목(isEmbeded="1")으로 있고, 본문의 모든 binaryItemIDRef 가 manifest 에 있다
  B  편집 가능(구역 하나): 같은 조건
  C  그림이 실제로 여럿(쪽 여럿 × 그림 여럿)이다 — 검사가 빈 것으로 통과하지 않게
그림 PDF 는 `test_fixtures.image_strips_pdf()`(3쪽 · 쪽마다 그림 4개)를 검사 임시 폴더에 복사해 쓴다. **수정 전 코드로 A 실패.**
"""
import os, sys, re, shutil, tempfile, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_fixtures
from viewer import convert

OPF = "{http://www.idpf.org/2007/opf/}"
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def inspect(path):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    bins = sorted(n for n in names if n.startswith("BinData/"))
    hpf = ET.fromstring(z.read("Contents/content.hpf"))
    items = {e.get("id"): e for e in hpf.iter(f"{OPF}item")}
    by_href = {e.get("href"): e for e in items.values()}
    secs = [n for n in names if re.match(r"Contents/section\d+\.xml$", n)]
    refs = re.findall(r'binaryItemIDRef="([^"]+)"', "".join(z.read(n).decode("utf-8") for n in secs))
    return bins, items, by_href, secs, refs


ROOT = Path(tempfile.mkdtemp(prefix="convhwpxpic_test_"))
try:
    src = ROOT / "그림 문서.pdf"
    shutil.copy2(test_fixtures.image_strips_pdf(), str(src))
    for key, label in (("hwpx_shape", "A 모양 그대로"), ("hwpx_edit", "B 편집 가능")):
        out = convert.run(str(src), key)
        bins, items, by_href, secs, refs = inspect(out)
        print(f"  {label}: 구역 {len(secs)} · BinData {len(bins)} · 본문 참조 {len(refs)} · manifest 그림 "
              f"{sum(1 for h in by_href if h and h.startswith('BinData/'))}")
        chk(len(bins) >= 6 and len(refs) == len(bins), f"C {label}: 그림이 여럿이고 본문 참조 수 = BinData 수",
            f"BinData {len(bins)} · 참조 {len(refs)}")
        missing = [b for b in bins if b not in by_href]
        chk(not missing, f"{label}: 모든 BinData 그림이 manifest 에 등록됨", f"빠짐 {len(missing)}/{len(bins)}: {missing[:4]}")
        not_emb = [b for b in bins if b in by_href and by_href[b].get("isEmbeded") != "1"]
        chk(not not_emb, f"{label}: manifest 그림 항목은 isEmbeded=\"1\"", str(not_emb[:4]))
        dangling = sorted(set(r for r in refs if r not in items))
        chk(not dangling, f"{label}: 본문의 모든 그림 참조가 manifest 에 있음", f"없음 {len(dangling)}: {dangling[:4]}")
        if key == "hwpx_shape":
            chk(len(secs) >= 2, "A 모양 그대로는 쪽마다 구역(이 결함이 나는 조건)", str(len(secs)))
finally:
    shutil.rmtree(ROOT, ignore_errors=True)

if fails:
    print("FAIL", len(fails), fails)
    sys.exit(1)
print("ALL PASS")
