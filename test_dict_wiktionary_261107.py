# -*- coding: utf-8 -*-
"""261107-27(사용자 지시 '영한, 영영 추천 사전' → 'Send it') — kaikki.org Wiktionary JSONL 가져오기. 단어장 SOT §5.1.

A. wiktextract 알아보기 — .jsonl·.gz 는 True, CSV 는 False
B. 고르기 — 영어 한 낱말만(고유명사·다른 언어·여러 낱말·깨진 줄·redirect 뺌), 영어 풀이·예문·한국어 번역(낱말 위·senses 안)
C. 배경 연결로 넣기 — 낱말 수·한국어 비율, lookup 으로 뜻이 나온다, 출처 = 일반 사전·참고문헌(CC BY-SA)
D. 다시 가져오면 겹치지 않는다
E. 취소하면 반쯤 넣은 출처가 남지 않는다
F. 한국어판(한글 풀이) → wiktionary_ko, def_ko
G. 스포팅 목록(all_terms(multiword=True))은 한 낱말 큰 사전을 읽지 않는다 — 여러 낱말 용어는 그대로
H. [가져오기] 가 JSONL 을 이 길로(용어집 창을 띄우지 않고 확인 한 번), 끝나면 한국어 비율을 알린다
수정 전 코드: 모듈이 없고 [가져오기] 가 JSONL 을 용어집 창으로 보낸다 → 실패.
"""
import os, sys, json, gzip, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog

QStandardPaths.setTestModeEnabled(True)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

app = QApplication.instance() or QApplication(sys.argv)
root = Path(tempfile.mkdtemp(prefix="polypdf_wikt_"))

LINES = [
    {"word": "dog", "lang": "English", "lang_code": "en", "pos": "noun",
     "senses": [{"glosses": ["A mammal of the family Canidae."],
                 "examples": [{"text": "The dog barked."}, {"text": "A good dog."}, {"text": "Third one."}]}],
     "translations": [{"lang": "Korean", "lang_code": "ko", "word": "개"},
                      {"lang": "French", "lang_code": "fr", "word": "chien"}]},
    {"word": "dog", "lang": "English", "lang_code": "en", "pos": "verb",
     "senses": [{"glosses": ["To follow persistently."],
                 "translations": [{"lang_code": "ko", "word": "따라다니다"}]}]},
    {"word": "run", "lang": "English", "lang_code": "en", "pos": "verb",
     "senses": [{"glosses": ["To move swiftly on foot."]}]},
    {"word": "London", "lang": "English", "lang_code": "en", "pos": "name",
     "senses": [{"glosses": ["The capital of England."]}]},
    {"word": "chien", "lang": "French", "lang_code": "fr", "pos": "noun",
     "senses": [{"glosses": ["dog"]}]},
    {"word": "ice cream", "lang": "English", "lang_code": "en", "pos": "noun",
     "senses": [{"glosses": ["A frozen dessert."]}]},
    {"word": "zzz", "redirect": "sleep"},
    {"word": "empty", "lang_code": "en", "pos": "adj", "senses": [{}]},
]

def write_jsonl(path, objs, extra_bad=True):
    with open(path, "w", encoding="utf-8") as f:
        for o in objs:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        if extra_bad:
            f.write("not json at all\n\n")

jl = root / "kaikki.org-dictionary-English.jsonl"
write_jsonl(jl, LINES)
gz = root / "sample.jsonl.gz"
with gzip.open(gz, "wt", encoding="utf-8") as f:
    for o in LINES:
        f.write(json.dumps(o, ensure_ascii=False) + "\n")
csv = root / "g.csv"
csv.write_text("term_ko,term_en\n개,dog\n", encoding="utf-8")

try:
    from viewer.study import wiktionary_import as wi
except Exception as e:                       # 수정 전 코드
    chk(False, "모듈 viewer.study.wiktionary_import", repr(e))
    print(f"\nFAIL {len(fails)}: {fails}")
    sys.exit(1)

# ---- A ----
chk(wi.is_wiktextract(jl) and wi.is_wiktextract(gz) and not wi.is_wiktextract(csv), "A1 .jsonl·.gz 는 알아보고 CSV 는 아님")

# ---- B ----
ents = list(wi.iter_entries(jl))
words = [e["term_en"] for e in ents]
chk(words == ["dog", "dog", "run"], "B1 영어 한 낱말만(고유명사·프랑스어·여러 낱말·redirect·빈 뜻·깨진 줄 뺌)", str(words))
d0 = ents[0]
chk(d0["def_en"] == "(noun) A mammal of the family Canidae." and d0["def_ko"] == "번역: 개" and d0["term_ko"] == "",
    "B2 영어 풀이 (품사)·한국어 번역은 def_ko, term_ko 는 비움", repr(d0))
chk(d0["examples"].split("\n") == ["The dog barked.", "A good dog."], "B3 예문 앞 2개", repr(d0["examples"]))
chk(ents[1]["def_ko"] == "번역: 따라다니다", "B4 senses 안의 한국어 번역도", repr(ents[1]["def_ko"]))
chk(ents[2]["def_ko"] == "", "B5 한국어 없는 낱말은 def_ko 비움")

# ---- C ----
from viewer.study.dict_store import DictStore
db = root / "dict.db"
ui = DictStore(db)                            # 화면 쪽 연결이 열린 채로
st = wi.import_file(db, jl)
chk(st == {"source_id": "wiktionary_en", "words": 3, "with_ko": 2, "with_en": 3}, "C1 낱말 수·한국어 수", str(st))
hits = [h for h in ui.lookup("dog") if h["source_id"] == "wiktionary_en"]
chk(len(hits) == 2 and any("번역: 개" in h["def_ko"] for h in hits), "C2 lookup('dog') — 품사 둘, 한국어 번역", str(len(hits)))
src = ui.get_source("wiktionary_en") or {}
chk(src.get("kind") == "base" and not src.get("is_termbase") and "CC BY-SA 4.0" in (src.get("reference") or "")
    and src.get("enabled") == 1, "C3 일반 사전·참고문헌 CC BY-SA·켜짐", str(src))

# ---- C4 항목 수 캐시 — 다른 연결·이 연결이 쓰면 다시 센다 ----
def n_of(sid):
    return next((s["n_entries"] for s in ui.list_sources() if s["source_id"] == sid), None)
chk(n_of("wiktionary_en") == 3, "C4 list_sources 항목 수", str(n_of("wiktionary_en")))
other = DictStore(db)
other.add_entry(source_id="wiktionary_en", term_en="cat", def_en="x")
other.close()
chk(n_of("wiktionary_en") == 4, "C5 다른 연결이 쓰면 다시 센다", str(n_of("wiktionary_en")))
ui.add_entry(term_en="mine", def_en="y")
chk(n_of("user") == 1 and n_of("wiktionary_en") == 4, "C6 이 연결이 쓰면(사용자 표 포함) 다시 센다", str(n_of("user")))

# ---- D ----
wi.import_file(db, gz)
chk(ui.count("wiktionary_en") == 3, "D1 다시 가져오면 겹치지 않음(.gz)", str(ui.count("wiktionary_en")))

# ---- E 취소 ----
big = root / "big.jsonl"
write_jsonl(big, [dict(LINES[2], word=f"word{chr(97 + i % 26)}{chr(97 + i // 26 % 26)}{chr(97 + i // 676 % 26)}") for i in range(6000)])
old_batch = wi.BATCH
wi.BATCH = 500
ui.delete_source("wiktionary_en")
calls = {"n": 0}
def _cancel_second(done, total):
    calls["n"] += 1
    return calls["n"] < 3                     # 0·2000 줄은 계속, 4000 줄에서 취소 — 그때까지 넣은 묶음이 있다
try:
    wi.import_file(db, big, _cancel_second)
    chk(False, "E1 취소면 ImportCancelled")
except wi.ImportCancelled:
    chk(True, "E1 취소면 ImportCancelled")
wi.BATCH = old_batch
chk(ui.get_source("wiktionary_en") is None and ui.count("wiktionary_en") == 0, "E2 반쯤 넣은 출처가 남지 않음")

# ---- F 한국어판 ----
ko = root / "ko-extract.jsonl"
write_jsonl(ko, [{"word": "apple", "lang": "영어", "lang_code": "en", "pos": "noun",
                  "senses": [{"glosses": ["사과"]}]},
                 {"word": "사과", "lang": "한국어", "lang_code": "ko", "pos": "noun",
                  "senses": [{"glosses": ["과일의 하나"]}]}])
st_ko = wi.import_file(db, ko)
h = [x for x in ui.lookup("apple") if x["source_id"] == "wiktionary_ko"]
chk(st_ko["source_id"] == "wiktionary_ko" and h and h[0]["def_ko"] == "(noun) 사과" and not h[0]["def_en"],
    "F1 한국어판 → wiktionary_ko, 한글 풀이는 def_ko", str(st_ko))

# ---- G 스포팅 ----
ui.add_source("tb", "도로", kind="base", is_termbase=True)
ui.add_entry(source_id="tb", term_en="asphalt concrete", term_ko="아스팔트 콘크리트")
wi.import_file(db, jl)
mw = ui.all_terms(multiword=True)
chk({r["source_id"] for r in mw} == {"tb"} and len(mw) == 1, "G1 스포팅 목록은 띄어쓰기 있는 표제어만", str([(r['source_id'], r['term_en']) for r in mw]))
from viewer.study.term_spotter import term_list
chk(term_list(ui.all_terms()) == term_list(mw), "G2 스포팅 결과는 종전과 같다")

# ---- H [가져오기] ----
from viewer.study_controller import StudyMixin
import viewer.widgets.glossary_import_dialog as gid
opened = []
gid.GlossaryImportDialog.exec = lambda self: (opened.append(1), QDialog.DialogCode.Rejected)[1]
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(jl), ""))
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), QMessageBox.StandardButton.Yes)[1])
infos = []
QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: infos.append("WARN " + (a[2] if len(a) > 2 else "")))


class Host(StudyMixin):
    def __init__(self):
        self._prefs = {}
        self._dict_store = ui
        self._study_pdf = None
        self._spot_terms_cache = None
        self.main_view = type("MV", (), {"current_page": lambda _s: 0})()
        self.status = type("St", (), {"showMessage": lambda *_a, **_k: None})()
    def _refresh_study_panel(self, page):
        pass
    def _refresh_dict_sources_menu(self):
        pass


ui.delete_source("wiktionary_en")
host = Host()
host._action_import_glossary()
chk(not opened, "H1 JSONL 은 용어집 창을 띄우지 않는다")
chk(len(asked) == 1 and "CC BY-SA" in asked[0], "H2 확인 한 번(출처 표기 포함)", str(asked)[:120])
chk(ui.count("wiktionary_en") == 3, "H3 넣었다", str(ui.count("wiktionary_en")))
chk(any("한국어가 있는 낱말 2개" in x and "66.7%" in x for x in infos), "H4 끝나면 한국어 비율을 알린다", str(infos)[:200])
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(root / "bad.jsonl"), ""))
(root / "bad.jsonl").write_text("hello\n", encoding="utf-8")
infos.clear()
host._action_import_glossary()
chk(any(x.startswith("WARN") for x in infos) and not opened, "H5 wiktextract 가 아닌 JSONL 은 알리고 멈춘다", str(infos))
# ---- J [Wiktionary 받기] — 가짜 네트워크(실제로 받지 않는다) ----
import io as _io, urllib.error
ko_lines = [{"word": f"word{chr(97 + i % 26)}{chr(97 + i // 26 % 26)}", "lang": "영어", "lang_code": "en", "pos": "noun",
             "senses": [{"glosses": [f"낱말 {i}"]}]} for i in range(300)]
GZ = gzip.compress("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in ko_lines).encode("utf-8"))
wi.MIN_DOWNLOAD_BYTES = 100                   # 합성 파일은 작다
urls = []

class FakeResp:
    def __init__(self, data, length=None):
        self._b = _io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}
    def read(self, n):
        return self._b.read(min(n, 1000))
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

def serve(data, length=None, exc=None):
    def _open(url, timeout=30):
        urls.append(url)
        if exc is not None:
            raise exc
        return FakeResp(data, length)
    wi._urlopen = _open

dl_dir = root / "_download"
def leftovers():
    return sorted(p.name for p in dl_dir.glob("*")) if dl_dir.exists() else []

for sid in ("wiktionary_ko", "wiktionary_en"):
    ui.delete_source(sid)
asked.clear(); infos.clear()
serve(GZ)
host._action_download_wiktionary()
chk(urls == [wi.KO_EDITION_URL] and "ko-extract.jsonl.gz" in wi.KO_EDITION_URL, "J1 상수 주소 한 곳(한국어판)", str(urls))
chk(asked and "약 26MB" in asked[-1] and wi.KO_EDITION_URL in asked[-1] and "CC BY-SA" in asked[-1],
    "J2 받기 전에 무엇을(이름·출처·크기·출처 표기) 묻는다", str(asked)[:160])
chk(ui.count("wiktionary_ko") == 300 and leftovers() == [], "J3 받아 넣고 받은 파일은 지운다", f"{ui.count('wiktionary_ko')} {leftovers()}")

def fresh():
    ui.delete_source("wiktionary_ko"); infos.clear()

fresh()
host._wiktionary_progress = lambda d, t, _l: False      # 곧바로 [취소]
serve(GZ)
r = host._action_download_wiktionary()
del host._wiktionary_progress
chk(r and r.get("cancelled") and ui.get_source("wiktionary_ko") is None and leftovers() == [], "J4 취소 — 넣지 않고 반쯤 받은 파일도 없다", str(r))

fresh()
serve(GZ, length=len(GZ) + 5000)                         # 끊김: 덜 받음
r = host._action_download_wiktionary()
chk(r and r.get("err") and ui.get_source("wiktionary_ko") is None and leftovers() == [] and any("크기" in x for x in infos),
    "J5 받은 크기가 다르면 넣지 않는다", str(infos)[:160])

fresh()
serve(b"<html>not found</html>" * 20)
r = host._action_download_wiktionary()
chk(r and r.get("err") and ui.get_source("wiktionary_ko") is None and leftovers() == [] and any("gzip" in x for x in infos),
    "J6 gzip 이 아니면 넣지 않는다", str(infos)[:160])

fresh()
serve(None, exc=urllib.error.URLError("getaddrinfo failed"))
r = host._action_download_wiktionary()
chk(r and r.get("err") and ui.get_source("wiktionary_ko") is None and any("인터넷에 연결할 수 없습니다" in x for x in infos),
    "J7 인터넷이 없으면 그렇게 알린다", str(infos)[:160])

from viewer import i18n
fresh(); asked.clear(); urls.clear()
i18n._lang = "en"
serve(GZ)
host._action_download_wiktionary()
i18n._lang = "ko"
chk(not asked and not urls and ui.get_source("wiktionary_ko") is None, "J8 한국어 화면이 아니면 아무것도 하지 않는다(@korea_only 처리기)")

from viewer.widgets.dict_manager_dialog import DictManagerPanel
called = []
host._action_download_wiktionary = lambda *a, **k: called.append(1)
pnl = DictManagerPanel(ui, {}, host=host, mode="default")
btn = getattr(pnl, "btn_wikt", None)
btn is not None and btn.click()
chk(btn is not None and called == [1] and "CC BY-SA" in btn.toolTip(), "J9 사전 쪽 [Wiktionary 받기] 단추(출처 표기 포함)")
ui.close()

print("\nALL PASS" if not fails else f"\nFAIL {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
