# -*- coding: utf-8 -*-
"""우클릭 메뉴 한 틀 — 여섯 메뉴(PDF·사진 × 책갈피창·썸네일창·본문) + 꾸밈 개체 메뉴 (디자인 SOT §2.9.8, 261107-2).

실제 MainWindow(오프스크린, 시험 프로필 — 마스터 §14.7.2 의 3). 메뉴는 `QMenu.exec` 를 가로채 메뉴 객체를 그대로 본다(하위까지).
A. 여섯 메뉴 모두 묶음 차례(`ctx_menu.GROUPS`)가 거꾸로 가지 않는다 — 항목마다 `ctx_group`
B. 디자인 SOT §2.9.8 의 4 표의 ○ 줄이 메뉴마다 있다(밖·`파일 ▸`·`저장 ▸` 안 자리까지)
C. 이름 — 어느 깊이에도 '…'·'...' 로 끝나는 항목이 없고, 옛 이름('돌리기'·'OCR로'·'공유용 사본 (위치 지움)'·'내보내기'·'변경 적용')이 없다
D. 삭제는 그 묶음 끝(쪽 삭제 = 모양 끝, 파일 삭제 = 파일 끝)
E. 나눈 항목 — 실제 메뉴를 띄워(가로채지 않고) Enter = 글자 일, → = 하위 열림, 글자 클릭 = 글자 일, ▸ 위 마우스 = 하위 열림,
   글자 일을 할 수 없으면 글자 클릭이 하위를 연다(사진 '저장')
F. 꾸밈 개체 메뉴 — 묶음 차례·'글쓰기 입력 설정'/'도형 입력 설정' 이름, **사진 본문도 개체 메뉴가 먼저**(종전에는 사진 메뉴가 먼저 떴다)
G. 썸네일 '다른 이름으로 저장' 은 책갈피창과 같은 저장 길(`_action_save_as`) — 옛 '변경 적용 — 새 PDF로 저장' 따로 길은 없다
수정 전 코드로 실패한다(묶음 속성 없음·'…' 이름·저장 ▸ 없음·사진 개체 메뉴 안 뜸).
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, QTimer, Qt
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_ctx_menu_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "우클릭 메뉴 한 틀", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=15.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


GROUPS = ("zip", "print", "copy", "shape", "file", "save", "view", "tool", "end")
seen = {"menu": None}
_orig_exec = QMenu.exec


def fake_exec(self, *a, **k):
    seen["menu"] = self
    return None


def label(a):
    return a.text().split("\t")[0].strip()


def tops(menu):
    return [a for a in menu.actions() if not a.isSeparator()]


def sub_of(menu, prefix):
    for a in tops(menu):
        if a.menu() is not None and label(a).startswith(prefix):
            return a.menu()
    return None


def all_labels(menu, depth=0):
    out = []
    for a in tops(menu):
        out.append(label(a))
        if a.menu() is not None:
            out.extend(all_labels(a.menu(), depth + 1))
    return out


def has(menu, want):
    """want 은 '글' 또는 '글|글'(둘 중 하나) — 앞부분이 같으면 있다."""
    labs = [label(a) for a in tops(menu)]
    return any(any(t == w or t.startswith(w) for t in labs) for w in want.split("|"))


def check_menu(name, menu, top_want, file_want=(), save_want=(), gone=()):
    chk(menu is not None, "%s 메뉴가 떴다" % name)
    if menu is None:
        return
    # A 묶음 차례
    gs = [a.property("ctx_group") for a in tops(menu)]
    chk(all(g in GROUPS for g in gs), "A %s 모든 항목에 묶음(ctx_group)" % name, str([(label(a), a.property("ctx_group")) for a in tops(menu)][:12]))
    idx = [GROUPS.index(g) for g in gs if g in GROUPS]
    chk(idx == sorted(idx), "A %s 묶음 차례가 거꾸로 가지 않는다" % name, str(list(zip([label(a) for a in tops(menu)], gs))))
    # B 표의 줄
    miss = [w for w in top_want if not has(menu, w)]
    chk(not miss, "B %s 밖 줄" % name, "없음: %s / 있는 것: %s" % (miss, [label(a) for a in tops(menu)]))
    if file_want:
        fm = sub_of(menu, "파일")
        chk(fm is not None, "B %s '파일 ▸'" % name)
        if fm is not None:
            miss = [w for w in file_want if not has(fm, w)]
            chk(not miss, "B %s '파일 ▸' 안 줄" % name, "없음: %s / %s" % (miss, [label(a) for a in tops(fm)]))
    if save_want:
        sv = [a for a in tops(menu) if a.property("ctx_save")]
        chk(len(sv) == 1 and sv[0].property("ctx_group") == "save" and label(sv[0]) == "저장",
            "B %s '저장 ▸' 하나(글자 '저장', 저장 묶음)" % name, str([label(a) for a in sv]))
        if sv:
            miss = [w for w in save_want if not has(sv[0].menu(), w)]
            chk(not miss, "B %s '저장 ▸' 안 줄" % name, "없음: %s / %s" % (miss, [label(a) for a in tops(sv[0].menu())]))
    # C 이름
    labs = all_labels(menu)
    dots = [t for t in labs if t.endswith("…") or t.endswith("...")]
    chk(not dots, "C %s 이름 끝 '…'·'...' 없음" % name, str(dots))
    old = [t for t in labs if any(o in t for o in ("돌리기", "OCR로", "위치 지움", "내보내기", "변경 적용", "별도 저장"))]
    chk(not old, "C %s 옛 이름 없음" % name, str(old))
    # 261107-16(사용자 지시 '경로복사는 삭제 — 파일 탐색기로 열 수 있으므로'): 어느 깊이에도 없다 — 키 Ctrl+Shift+C 로만
    chk("경로 복사" not in labs, "C %s '경로 복사' 줄 없음(261107-16)" % name, str([t for t in labs if "경로" in t]))
    for g in gone:
        chk(not has(menu, g), "B %s 에 '%s' 없음" % (name, g), str([label(a) for a in tops(menu)]))
    # D 삭제는 묶음 끝
    for a in tops(menu):
        if label(a).startswith("삭제") or label(a) == "파일·책갈피 삭제":
            g = a.property("ctx_group")
            same = [label(x) for x in tops(menu) if x.property("ctx_group") == g]
            chk(same[-1] == label(a) or same[-1] in ("폴더 이름 변경", "폴더 삭제"),
                "D %s 삭제는 '%s' 묶음 끝" % (name, g), str(same))


tmp = Path(tempfile.mkdtemp(prefix="polypdf_ctx_menu_"))
try:
    from PIL import Image
    import test_fixtures
    from viewer.i18n import korea_only_visible
    pdf = tmp / "가 문서.pdf"
    shutil.copy(test_fixtures.text_pdf(), pdf)
    Image.new("RGB", (800, 400), (200, 60, 60)).save(tmp / "a 사진.jpg", "JPEG")
    Image.new("RGB", (600, 300), (60, 160, 60)).save(tmp / "b 사진.jpg", "JPEG")
    pa, pb = str(tmp / "a 사진.jpg"), str(tmp / "b 사진.jpg")
    KO = korea_only_visible()

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw.open_folder(tmp); pump(lambda: any(Path(str(n.data(0, bt.DATA_FILE))).name == pdf.name for n in bt._iter_file_nodes()))

    def node(name):
        for it in bt._iter_file_nodes():
            if Path(str(it.data(0, bt.DATA_FILE))).name == name:
                return it
        return None

    def tree_menu(name):
        it = node(name)
        bt.tree.scrollToItem(it)
        seen["menu"] = None
        bt._on_tree_context_menu(bt.tree.visualItemRect(it).center())
        return seen["menu"]

    QMenu.exec = fake_exec
    mw._on_bookmark_activated(str(pdf), 0)
    pump(lambda: mw.main_view.current_file() and Path(mw.main_view.current_file()).name == pdf.name)
    pump(lambda: mw.page_thumbs.list.count() > 0)
    bt.set_edit_mode(True); pump(timeout=0.3)

    TOOLS_KO = ["단어장 생성", "번역", "번역 용어집 교정"] if KO else []
    FILE_SUB = ["파일 탐색기 열기", "폴더로 복사", "폴더로 이동", "파일·책갈피 이름 변경", "OCR 로 글자층 생성", "일괄 OCR",
                "책갈피 생성", "해시태그 편집", "현재 폴더를 즐겨찾기에 추가", "현재 파일을 즐겨찾기에 추가"] + TOOLS_KO
    SAVE_PDF = ["저장", "다른 이름으로 저장", "평탄화 사본", "용량 줄인 사본", "개인정보 지운 사본", "전달 묶음", "PDF 저장", "변환"]

    # ── PDF 책갈피창 ──
    m = tree_menu(pdf.name)
    check_menu("PDF 책갈피창", m,
               ["인쇄", "파일 회전", "파일 탐색기 열기", "새 폴더 만들기", "폴더로 복사", "폴더로 이동", "파일·책갈피 이름 변경",
                "파일·책갈피 삭제", "2단 보기|옆 창에 열기", "발표보기", "책갈피 모두 펼치기", "책갈피 모두 접기", "OCR 로 읽기",
                "OCR 로 글자층 생성", "일괄 OCR", "책갈피 생성", "서명", "해시태그 편집",
                "현재 폴더를 즐겨찾기에 추가", "현재 파일을 즐겨찾기에 추가"] + TOOLS_KO,
               save_want=SAVE_PDF)
    if m is not None:
        labs = [label(a) for a in tops(m)]
        tl = [t for t in labs if t.startswith("OCR") or t in ("일괄 OCR", "책갈피 생성")]
        chk(tl[:4] == ["OCR 로 읽기", "OCR 로 글자층 생성", "일괄 OCR", "책갈피 생성"], "B PDF 책갈피창 도구 맨 앞 OCR 셋 차례(§5.2 의 3)", str(tl))

    # ── PDF 썸네일창 ──
    pt = mw.page_thumbs
    it0 = pt.list.item(0)
    pt.list.clearSelection(); it0.setSelected(True)
    seen["menu"] = None
    pt._on_list_menu(pt.list.visualItemRect(it0).center())
    m = seen["menu"]
    check_menu("PDF 썸네일창", m,
               ["인쇄 (1쪽)", "복사 (1쪽)", "스크린샷으로 복사", "붙여넣기", "스크린샷 붙여넣기", "클립보드 붙여넣기", "새 페이지 넣기",
                "왼쪽 90° 회전", "오른쪽 90° 회전", "180° 회전", "크롭 (", "크롭 해제", "숨김 (", "숨김 해제", "삭제 (",
                "2단 보기|1단 보기", "발표보기", "OCR 로 읽기", "서명", "책갈피 추가", "하이퍼링크 등록"],
               file_want=FILE_SUB, save_want=SAVE_PDF)
    if m is not None:
        sv = [a for a in tops(m) if a.property("ctx_save")]
        cv = sub_of(sv[0].menu(), "변환") if sv else None
        chk(cv is not None and len(tops(cv)) >= 1, "B PDF 썸네일창 저장 ▸ '변환 ▸'(고른 쪽 형식)")

    # ── PDF 본문 ──
    seen["menu"] = None
    mv = mw.main_view
    mw._on_viewer_context_menu(mv.mapToGlobal(mv.rect().center()))
    m = seen["menu"]
    check_menu("PDF 본문", m,
               ["인쇄", "복사", "스크린샷으로 복사", "텍스트 복사", "블럭설정 후 텍스트 복사", "붙여넣기", "스크린샷 붙여넣기",
                "클립보드 붙여넣기", "사진 붙여넣기", "새 페이지 넣기", "왼쪽 90° 회전", "오른쪽 90° 회전", "180° 회전", "크롭 (",
                "크롭 해제", "숨김 (", "숨김 해제", "삭제", "2단 보기|1단 보기", "발표보기", "OCR 로 읽기", "여기에 서명",
                "책갈피 추가", "하이퍼링크 등록", "도형 입력 설정", "글쓰기 입력 설정"],
               file_want=FILE_SUB, save_want=SAVE_PDF)

    # G 썸네일 '다른 이름으로 저장' = 책갈피창과 같은 길
    called = []
    _osa = mw._action_save_as
    mw._action_save_as = lambda *a, **k: called.append(k.get("file_path"))
    m = None
    seen["menu"] = None
    pt._on_list_menu(pt.list.visualItemRect(it0).center())
    m = seen["menu"]
    sv = [a for a in tops(m) if a.property("ctx_save")] if m is not None else []
    a_sa = next((a for a in tops(sv[0].menu()) if label(a) == "다른 이름으로 저장"), None) if sv else None
    if a_sa is not None:
        a_sa.trigger(); pump(timeout=0.3)
    chk(called and Path(str(called[-1])).name == pdf.name, "G 썸네일 '다른 이름으로 저장' → _action_save_as(본문 파일)", str(called))
    mw._action_save_as = _osa
    chk(not hasattr(mw, "_on_apply_page_edits") and not hasattr(pt, "applyPageEditsRequested"),
        "G 옛 '변경 적용 — 새 PDF로 저장' 따로 길이 없다")

    # F 꾸밈 개체 메뉴(PDF)
    for kind, want_end in (("text", "글쓰기 입력 설정"), ("line", "도형 입력 설정"), ("image", None)):
        seen["menu"] = None
        mw._deco_context_menu(mv.mapToGlobal(mv.rect().center()), kind)
        m = seen["menu"]
        labs = [label(a) for a in tops(m)] if m else []
        gs = [GROUPS.index(a.property("ctx_group")) for a in tops(m) if a.property("ctx_group") in GROUPS] if m else []
        chk(m is not None and gs == sorted(gs) and len(gs) == len(labs), "F 개체 메뉴(%s) 묶음 차례" % kind, str(labs))
        if want_end:
            chk(labs and labs[-1] == want_end, "F 개체 메뉴(%s) 끝 '%s'" % (kind, want_end), str(labs))
        dots = [t for t in all_labels(m) if t.endswith("…") or t.endswith("...")] if m else ["?"]
        chk(not dots and not any("선과 텍스트" in t for t in labs), "F 개체 메뉴(%s) 이름" % kind, str(dots + labs))

    # ── 사진 모드 ──
    mw._set_photo_mode(True)
    pump(lambda: node("a 사진.jpg") is not None and node("b 사진.jpg") is not None)
    mw._on_bookmark_activated(pa, 0); pump(timeout=0.5)
    PHOTO_TOP = ["인쇄", "사진 복사", "왼쪽 90° 회전", "오른쪽 90° 회전", "180° 회전", "원래 방향", "크롭", "크롭 해제",
                 "파일 탐색기 열기", "폴더로 복사", "폴더로 이동", "이름 변경", "삭제", "2단 보기|옆 창에 열기", "발표보기",
                 "OCR 로 읽기", "사진 정보", "지도에서 위치 보기", "일괄 작업", "해시태그 편집", "현재 폴더를 즐겨찾기에 추가",
                 "현재 파일을 즐겨찾기에 추가"]
    SAVE_PHOTO = ["저장", "평탄화 사본", "개인정보 지운 사본", "PDF 저장", "변환"]
    PHOTO_GONE = ["공유용 사본", "방향 저장", "평탄화", "PDF 로 만들기", "다른 이름으로 저장"]
    m = tree_menu("a 사진.jpg")
    check_menu("사진 책갈피창", m, PHOTO_TOP + ["새 폴더 만들기", "보기설정"], save_want=SAVE_PHOTO, gone=PHOTO_GONE)
    strip = mw._photo_strip_widget()
    pump(lambda: len(strip.paths()) >= 2, timeout=8)
    seen["menu"] = None
    mw._photo_strip_menu(pa, QPoint(10, 10))
    m = seen["menu"]
    check_menu("사진 썸네일창", m, PHOTO_TOP + ["보기설정"], save_want=SAVE_PHOTO + ["줄의 사진"], gone=PHOTO_GONE + ["열기"])
    if m is not None:
        chk(not any(label(a) == "열기" for a in tops(m)), "B 사진 썸네일창 '열기' 없음(누르면 열린다)")
    seen["menu"] = None
    mw._on_viewer_context_menu(mv.mapToGlobal(mv.rect().center()))
    m = seen["menu"]
    check_menu("사진 본문", m, PHOTO_TOP + ["텍스트 복사", "블럭설정 후 텍스트 복사", "스크린샷 붙여넣기", "클립보드 붙여넣기",
                                            "사진 붙여넣기", "도형 입력 설정", "글쓰기 입력 설정"],
               save_want=SAVE_PHOTO, gone=PHOTO_GONE)

    # F 사진 본문도 개체 메뉴가 먼저(261107-2 — 종전에는 사진 메뉴가 먼저 떠 개체 메뉴가 안 떴다)
    _dt = mv.deco_menu_target
    mv.deco_menu_target = lambda gp: "text"
    seen["menu"] = None
    mw._on_viewer_context_menu(mv.mapToGlobal(mv.rect().center()))
    m = seen["menu"]
    labs = [label(a) for a in tops(m)] if m else []
    chk("선택 글상자 삭제" in labs and "사진 복사" not in labs, "F 사진 본문 — 개체 위 우클릭은 개체 메뉴", str(labs))
    mv.deco_menu_target = _dt
    QMenu.exec = _orig_exec

    # ── E 나눈 항목 — 실제 메뉴(가로채지 않음) ──
    from viewer.widgets.ctx_menu import CtxMenu, add_save_menu, SPLIT_ARROW_W
    done = []

    def build(can_save=True):
        mm = CtxMenu()
        mm.group("print"); mm.addAction("인쇄")
        add_save_menu(mm, save={"cb": lambda: done.append("save"), "enabled": can_save},
                      copies=[{"text": "평탄화 사본", "cb": lambda: done.append("flat")}], key="Ctrl+S")
        mm.group("view"); mm.addAction("2단 보기")
        sp = [a for a in tops(mm) if a.property("ctx_save")][0]
        return mm, sp

    def run(mm, drive, ms=60):
        res = {}
        QTimer.singleShot(ms, lambda: drive(res))
        QTimer.singleShot(4000, mm.close)                    # 막히지 않게
        res["ret"] = mm.exec(QPoint(80, 80))
        pump(timeout=0.3)
        return res

    # E1 ↑↓ 로 와서 Enter = 글자(저장)
    mm, sp = build()

    def d1(res):
        mm.setActiveAction(sp)
        QTest.keyClick(mm, Qt.Key.Key_Return)
    r = run(mm, d1)
    chk(done == ["save"] and not mm.isVisible(), "E1 Enter = 글자 일(저장) · 메뉴 닫힘", str(done))
    done.clear()
    # E2 → = 하위 열기
    mm, sp = build()

    def d2(res):
        mm.setActiveAction(sp)
        QTest.keyClick(mm, Qt.Key.Key_Right)
        pump(timeout=0.3)
        res["open"] = sp.menu().isVisible()
        mm.close()
    r = run(mm, d2)
    chk(r.get("open") and not done, "E2 → = 하위 열림(글자 일 안 함)", str((r, done)))
    # E3 글자 클릭 = 글자 일
    mm, sp = build()

    def d3(res):
        g = mm.actionGeometry(sp)
        QTest.mouseClick(mm, Qt.MouseButton.LeftButton, pos=QPoint(g.left() + 20, g.center().y()))
    r = run(mm, d3)
    chk(done == ["save"], "E3 글자 클릭 = 글자 일(저장)", str(done))
    done.clear()
    # E4 ▸ 위에 마우스를 올리면 하위가 열린다
    mm, sp = build()

    def d4(res):
        g = mm.actionGeometry(sp)
        QTest.mouseMove(mm, QPoint(g.right() - SPLIT_ARROW_W // 2, g.center().y()))
        pump(lambda: sp.menu().isVisible(), timeout=2.0)
        res["open"] = sp.menu().isVisible()
        mm.close()
    r = run(mm, d4)
    chk(r.get("open") and not done, "E4 ▸ 위 마우스 = 하위 열림", str((r, done)))
    # E5 글자 일을 할 수 없으면(사진 '저장' — 돌린 JPEG 아님) 글자 클릭이 하위를 연다
    mm, sp = build(can_save=False)

    def d5(res):
        g = mm.actionGeometry(sp)
        QTest.mouseClick(mm, Qt.MouseButton.LeftButton, pos=QPoint(g.left() + 20, g.center().y()))
        pump(lambda: sp.menu().isVisible(), timeout=2.0)
        res["open"] = sp.menu().isVisible()
        mm.close()
    r = run(mm, d5)
    chk(r.get("open") and not done, "E5 글자 일을 못 하면 글자 클릭이 하위를 연다", str((r, done)))
    # E6 하위 항목을 고르면 그 일(메뉴 exec 가 그 항목을 돌려준다)
    mm, sp = build()

    def d6(res):
        mm.setActiveAction(sp)
        QTest.keyClick(mm, Qt.Key.Key_Right)
        pump(lambda: sp.menu().isVisible(), timeout=2.0)
        sub = sp.menu()
        flat = next(a for a in tops(sub) if label(a) == "평탄화 사본")
        sub.setActiveAction(flat)
        QTest.keyClick(sub, Qt.Key.Key_Return)
    r = run(mm, d6)
    pump(timeout=0.3)
    chk(done == ["flat"] and r.get("ret") is not None and label(r["ret"]) == "평탄화 사본", "E6 하위 '평탄화 사본' 고름 = 그 일 한 번",
        str((done, r)))

    mw.close()
finally:
    QMenu.exec = _orig_exec
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL PASS" if not fails else "FAILED: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
