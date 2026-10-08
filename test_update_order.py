# -*- coding: utf-8 -*-
"""261008-17·-18(마스터 SOT §14.5 U13·U14): 업그레이드 순서와 '바뀐 내용' 보기.

사용자 지시:
  - "업그레이드시 다운로드를 먼저 받고, 이후에 PolyPDF를 닫고, 모두 닫혔는지 확인하고 업그레이드 하도록 순서를 조정해"
  - "업그레이드시 어떤 업그레이드인지 세부 설명내용을 볼 수 있도록 보완해"

A. collect_changes — 지금 버전 다음부터 새 버전까지, 새 버전부터. stable 채널은 프리릴리즈 제외
B. 업데이트 창 — 버전별 설명을 보이고, 설명이 링크뿐이면 릴리스 페이지를 안내
C. 도움말 → 업데이트: **받기 → (그 뒤) 설치 도우미 시작 → 창 닫힘** (실제 _upgrade_now·closeEvent 길)
D. 받기를 실패하면 설치 도우미를 시작하지 않고 창도 닫지 않는다
E. 종료할 때 '업그레이드 후 종료' 도 받은 뒤에 설치 도우미
F. 설치 도우미 스크립트: 예비 받기(1.5)가 다른 창 닫기(1.2)보다 앞
G. 릴리스 설명 스크립트가 커밋 메시지로 설명을 만든다
"""
import os, sys, faulthandler, tempfile, subprocess
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)

from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


try:
    from viewer import updater
    from viewer.widgets.update_dialog import UpdateDialog, changes_markdown

    # ── A ──
    rels = [{"tag_name": t, "body": "- 바뀜 " + t, "html_url": "https://github.com/x/r/" + t,
             "published_at": "2026-10-08T00:00:00Z"}
            for t in ("v0.45.0-beta.193", "v0.45.0-beta.194", "v0.45.0-beta.195",
                      "v0.45.0-beta.196", "components", "v0.44.0")]
    ch = updater.collect_changes(rels, "0.45.0-beta.194", True)
    chk([c["version"] for c in ch] == ["0.45.0-beta.196", "0.45.0-beta.195"],
        "A 지금 버전 다음부터 새 버전까지, 새 버전부터", str([c["version"] for c in ch]))
    chk(all(c["pre"] for c in ch), "A 베타 표시")
    chk(updater.collect_changes(rels, "0.44.0", False) == [], "A stable 채널은 프리릴리즈를 빼고, 지금보다 높은 정식이 없으면 빈 목록")

    # ── B ──
    md = changes_markdown([{"version": "0.45.0-beta.196", "pre": True, "date": "2026-10-08",
                            "notes": "**Full Changelog**: https://github.com/x/compare/a...b",
                            "url": "https://github.com/x/r/v196"},
                           {"version": "0.45.0-beta.195", "notes": "## 바뀐 내용\n\n- **수정** 무엇", "url": ""}])
    chk("v0.45.0-beta.196" in md and "베타" in md and "릴리스 페이지" in md, "B 설명이 링크뿐이면 릴리스 페이지 안내")
    chk("**수정** 무엇" in md, "B 설명 본문을 그대로 보인다")
    d = UpdateDialog({"version": "0.45.0-beta.196", "tag": "v0.45.0-beta.196", "changes": ch},
                     "0.45.0-beta.194", "manual")
    txt = d.notes.toPlainText()
    chk("바뀜 v0.45.0-beta.196" in txt and "바뀜 v0.45.0-beta.195" in txt, "B 업데이트 창에 건너뛴 버전까지 모두 보인다")
    d.done(0)

    # ── C·D·E — 실제 MainWindow 길 ──
    from viewer.app import MainWindow
    from viewer.widgets import update_dialog as _ud
    log = []
    root = tempfile.mkdtemp(prefix="polypdf_upd_test_")
    url = "https://github.com/kdjeong777-ops/PolyPDF/releases/download/v9/PolyPDF-update.zip"
    info = {"version": "9.0.0", "tag": "v9.0.0", "asset_url": url,
            "changes": [{"version": "9.0.0", "notes": "- 새 기능", "url": ""}]}
    state = {"fail": False}

    def fake_download(u, progress=None, timeout=30.0, expect_sha256=""):
        log.append("download")
        if progress:
            progress(50, 100); progress(100, 100)
        if state["fail"]:
            return None
        p = os.path.join(tempfile.mkdtemp(dir=root), "PolyPDF-update.zip")
        open(p, "wb").write(b"zip")
        return p

    updater.download_asset = fake_download
    updater.fetch_expected_sha256 = lambda info, timeout=20.0: ""
    updater.fetch_manifest = lambda info, timeout=20.0: ""
    updater.apply_update = lambda **kw: (log.append(("apply", bool(kw.get("zip_path")))), True)[1]
    QMessageBox.warning = staticmethod(lambda *a, **k: log.append("warn"))
    QMessageBox.information = staticmethod(lambda *a, **k: log.append("info"))
    updater.is_frozen = lambda: True            # 개발 실행에서도 배포본 길로(안내 상자 대신 업데이트 창)

    def reset_zip():
        z = updater.pending_zip_path()
        for suf in ("", ".ver", ".sha256"):
            try:
                os.remove(str(z) + suf if suf else str(z))
            except OSError:
                pass
        try:
            os.remove(str(z.with_suffix(".ver")))
        except OSError:
            pass

    # C
    reset_zip()
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.show(); app.processEvents()
    mw._pending_update = info
    _ud.UpdateDialog.exec = lambda self: (setattr(self, "choice", "update"), 1)[1]
    mw._on_update_result(info, True)
    app.processEvents()
    chk(log[:1] == ["download"] and ("apply", True) in log, "C 받기 → 그 뒤 설치 도우미(받은 파일로)", str(log))
    chk(log.index("download") < log.index(("apply", True)) if ("apply", True) in log else False,
        "C 순서: 받기가 설치 도우미보다 먼저")
    chk(not mw.isVisible(), "C 받은 뒤 창이 닫힌다")

    # D
    log.clear(); reset_zip(); state["fail"] = True
    mw2 = MainWindow(); mw2._skip_save_on_close = True
    mw2.show(); app.processEvents()
    mw2._pending_update = info
    mw2._on_update_result(info, True)
    app.processEvents()
    chk("download" in log and not any(isinstance(x, tuple) for x in log), "D 받기 실패 → 설치 도우미를 시작하지 않는다", str(log))
    chk(mw2.isVisible() and "warn" in log, "D 창은 닫히지 않고 안내한다", f"visible={mw2.isVisible()} log={log}")

    # E
    log.clear(); reset_zip(); state["fail"] = False
    mw2._upgrade_requested = False
    mw2.close()
    app.processEvents()
    chk(log[:1] == ["download"] and ("apply", True) in log and not mw2.isVisible(),
        "E 종료할 때 '업그레이드 후 종료' 도 받은 뒤 설치 도우미", str(log))

    # ── F ──
    ps = updater._PS_INSTALLER
    chk(ps.index("# 1.5) 다운로드") < ps.index("# 1.2) 다른 창"), "F 설치 도우미의 예비 받기가 다른 창 닫기보다 앞")

    # ── G ──
    here = os.path.dirname(os.path.abspath(__file__))
    out = subprocess.run([sys.executable, os.path.join(here, "scripts", "release_notes.py"), "v0.45.0-beta.196"],
                         capture_output=True, text=True, encoding="utf-8", cwd=here).stdout
    chk(out.startswith("<!-- lang:ko -->\n## 바뀐 내용") and "**수정**" in out and "test_" not in out
        and "Co-Authored-By" not in out and "/compare/v0.45.0-beta.193...v0.45.0-beta.196" in out,
        "G 릴리스 설명을 커밋 메시지로 만든다(검사 이름·서명 줄 제외)", out[:200])

    # ── H — 언어별 절(다국어 SOT §10.4, 261008-27) ──
    import shutil
    repo = tempfile.mkdtemp(prefix="polypdf_relnotes_")

    def g(*a):
        return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    g("commit", "-q", "--allow-empty", "-m", "first"); g("tag", "v1.0.0")
    g("commit", "-q", "--allow-empty", "-m",
      "fix: 저장 오류 고침 (1, 1.0.1)\n\n- 저장이 됩니다\n\nRelease-Note-en: Saving works again\n"
      "Release-Note-en: Faster startup\n\nCo-Authored-By: x <x@x>")
    g("commit", "-q", "--allow-empty", "-m", "feat: 한국어만 (2, 1.0.1)\n\n- 한국어 설명만")
    g("tag", "v1.0.1")
    out2 = subprocess.run([sys.executable, os.path.join(here, "scripts", "release_notes.py"), "v1.0.1"],
                          capture_output=True, text=True, encoding="utf-8", cwd=repo).stdout
    shutil.rmtree(repo, ignore_errors=True)
    secs = _ud.split_lang_sections(out2)
    chk(set(secs) == {"ko", "en"}, "H 한국어·영어 절", str(list(secs)))
    chk("저장이 됩니다" in secs.get("ko", "") and "한국어 설명만" in secs.get("ko", "")
        and "Release-Note" not in secs.get("ko", ""), "H 한국어 절은 모든 커밋, 꼬리말은 빠진다")
    chk("- Saving works again" in secs.get("en", "") and "- Faster startup" in secs.get("en", "")
        and "한국어" not in secs.get("en", "") and "What's changed" in secs.get("en", ""),
        "H 영어 절은 꼬리말 항목만(꼬리말 없는 커밋은 빠진다)")
    md_en = changes_markdown([{"version": "1.0.1", "notes": out2}], chain=["en", "ko"])
    chk("Saving works again" in md_en and "저장이 됩니다" not in md_en and "What's changed" not in md_en,
        "H 영어 화면은 영어 절을 보이고 절 머리는 지운다")
    md_old = changes_markdown([{"version": "1.0.0", "notes": "## 바뀐 내용\n\n- 옛 설명"}], chain=["en", "ko"])
    chk("옛 설명" in md_old and "한국어로만" in md_old, "H 표시 없는 옛 설명은 한국어로만 있다는 안내와 함께")
    md_ko = changes_markdown([{"version": "1.0.1", "notes": out2}], chain=["ko"])
    chk("저장이 됩니다" in md_ko and "Saving" not in md_ko and "한국어로만" not in md_ko, "H 한국어 화면은 한국어 절")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
