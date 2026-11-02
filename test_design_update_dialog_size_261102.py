# -*- coding: utf-8 -*-
"""261102-5: 업데이트 확인 창 — 크기는 내용에 맞춘다 (화면 디자인 SOT §2.19, 사용자 지시 '내용에 비해 너무 크다').

실제 UpdateDialog 를 ko·en 으로 띄워(오프스크린, 실제 글꼴) 잰다.
A. 확인 중·결과 한 줄 — 폭이 MSG_W 범위, 높이는 그 폭에서 필요한 높이(빈 칸 없음, 종전 640×520)
B. 두 줄짜리 알림(가져오지 못함)도 글이 잘리지 않는다
C. 바뀐 내용이 짧으면 설명 칸에 스크롤 없이 다 보이고 높이는 NOTES_H 안
D. 바뀐 내용이 길면 높이는 NOTES_H 위끝·화면 SCREEN_FRAC 를 넘지 않고 설명 칸만 스크롤
E. 떠 있는 창이 확인 중 → 결과로 커질 때 가운데가 그대로
F. 모든 상태에서 글·체크·단추가 창 안에 있고 잘리지 않는다
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication, QLabel, QCheckBox, QPushButton
from PyQt6.QtGui import QFont

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_update_dialog_size_261102_%d" % os.getpid())
app.setFont(QFont("Malgun Gothic", 9))
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump():
    for _ in range(6):
        app.processEvents()


def not_cut(d, tag):
    """보이는 글·체크·단추가 창 안에 있고, 줄바꿈 라벨은 필요한 높이를 받았다."""
    bad = []
    for w in d.findChildren((QLabel, QCheckBox, QPushButton)):
        if not w.isVisible() or not w.isVisibleTo(d):
            continue
        r = w.geometry()
        r.moveTopLeft(w.mapTo(d, r.topLeft() - r.topLeft()))
        if r.right() > d.width() or r.bottom() > d.height():
            bad.append("%s 창 밖 %s" % (w.text()[:20], r))
        need = w.heightForWidth(w.width()) if isinstance(w, QLabel) and w.wordWrap() else w.sizeHint().height()
        if w.height() + 1 < need:
            bad.append("%s 높이 %d < %d" % (w.text()[:20], w.height(), need))
        if not isinstance(w, QLabel) and w.width() + 1 < w.sizeHint().width():
            bad.append("%s 폭 %d < %d" % (w.text()[:20], w.width(), w.sizeHint().width()))
    chk(not bad, "F [%s] 글·체크·단추가 창 안·잘림 없음" % tag, str(bad))


from viewer import i18n
from viewer.i18n import tr
opts = {"auto_download": True, "beta": True}
short = ("<!-- lang:ko -->\n## 바뀐 내용\n- 업데이트 확인 창 크기\n- 맞춤 콤보 화살표\n"
         "<!-- lang:en -->\n## What's changed\n- Update dialog size\n- Fit combo arrow\n")


def info(n):
    return {"version": "1.1.0-beta.3", "tag": "v1.1.0-beta.3",
            "changes": [{"version": "1.1.0-beta.%d" % (3 + i), "pre": True, "date": "2026-11-02", "notes": short}
                        for i in range(n)]}


for lang in ("ko", "en"):
    i18n.install(app, lang)
    from viewer.widgets.update_dialog import UpdateDialog as D
    d = D(None, "1.1.0-beta.2", "check", None, options=opts)
    d.show(); pump()
    lay = d.layout()
    lo, hi = D.MSG_W
    # A. 확인 중
    chk(lo <= d.width() <= hi, "A [%s] 확인 중 폭이 MSG_W 범위" % lang, "%dx%d" % (d.width(), d.height()))
    chk(abs(d.height() - lay.totalHeightForWidth(d.width())) <= 2, "A [%s] 확인 중 높이 = 필요한 높이(빈 칸 없음)" % lang,
        "%d vs %d" % (d.height(), lay.totalHeightForWidth(d.width())))
    not_cut(d, lang + " 확인 중")
    # E. 확인 중 → 결과(커짐) 때 가운데 유지
    c0 = d.frameGeometry().center()
    d.show_result(info(1), "1.1.0-beta.2"); pump()
    c1 = d.frameGeometry().center()
    chk(abs(c0.x() - c1.x()) <= 2 and abs(c0.y() - c1.y()) <= 2, "E [%s] 커질 때 가운데 그대로" % lang, "%s → %s" % (c0, c1))
    # C. 짧은 바뀐 내용
    nlo, nhi = D.NOTES_H
    chk(d.width() == D.NOTES_W and nlo <= d.height() <= nhi, "C [%s] 새 버전 창 크기 NOTES_W·NOTES_H 안" % lang,
        "%dx%d" % (d.width(), d.height()))
    chk(d.notes.verticalScrollBar().maximum() == 0, "C [%s] 짧은 설명은 스크롤 없이 다 보인다" % lang,
        str(d.notes.verticalScrollBar().maximum()))
    not_cut(d, lang + " 새 버전")
    # B. 두 줄 알림
    d.show_message(tr("업데이트 정보를 가져오지 못했습니다.\n인터넷 연결과 저장소 설정을 확인하세요.").replace("\n", "<br>")); pump()
    chk(lo <= d.width() <= hi and abs(d.height() - lay.totalHeightForWidth(d.width())) <= 2,
        "B [%s] 두 줄 알림 — 폭 범위·높이 = 필요한 높이" % lang, "%dx%d" % (d.width(), d.height()))
    not_cut(d, lang + " 두 줄 알림")
    # D. 긴 바뀐 내용
    d.show_result(info(30), "1.1.0-beta.2"); pump()
    cap = min(nhi, int(d.screen().availableGeometry().height() * D.SCREEN_FRAC))
    chk(d.height() == cap, "D [%s] 긴 설명 — 높이는 위끝(%d)" % (lang, cap), str(d.height()))
    chk(d.notes.verticalScrollBar().maximum() > 0, "D [%s] 긴 설명은 설명 칸만 스크롤" % lang)
    not_cut(d, lang + " 긴 설명")
    d.close()
    # 처음부터 결과로 여는 창(종료 때 'close')도 같은 규칙
    d2 = D(info(1), "1.1.0-beta.2", "close", None)
    d2.show(); pump()
    chk(d2.width() == D.NOTES_W and d2.height() <= nhi, "C [%s] 종료 때 창도 내용 크기" % lang, "%dx%d" % (d2.width(), d2.height()))
    not_cut(d2, lang + " 종료 때")
    d2.close()

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
