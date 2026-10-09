# -*- coding: utf-8 -*-
"""261009-16: 한국어 띄어쓰기(kiwi)는 자식 프로세스에서 — 응답성 SOT §4 ③·§6 · 텍스트 창 SOT §3.7.10.

beta.219 설치본 재실측(응답성 SOT §9.1)에서 남은 정지 1회(2.28초): kiwi 를 짓는 동안(0.74초)과 첫 `space()`(0.48초)
GIL 을 쥐어, 색인과 겹치면 메인이 둘 다를 기다렸다. 같은 프로세스 안에서는 배경 스레드여도 못 막는다.

각 경우는 **새 프로세스**에서 돈다(모듈 상태·자식 프로세스가 섞이지 않게).
A. 실제 경로(`_join_sep` → `_ko_wants_space`)가 자식에게 묻는다 — 이 프로세스에는 kiwipiepy 가 실리지 않고,
   그동안 다른 스레드가 0.3초 넘게 막히지 않으며, 판정은 이 프로세스의 kiwi 와 같다
B. UI 스레드는 자식의 준비를 기다리지 않는다(곧바로 기하 규칙) — 그 사이 자식은 뜬다
C. 부모가 `os._exit` 로 끝나면 자식도 끝난다(남지 않는다)
D. 자식을 못 띄우면 워커는 종전대로 이 프로세스의 kiwi 로 판정한다(품질 유지), UI 스레드는 짓지 않는다
E. 다른 스레드가 묻는 중이면 UI 스레드는 `UI_WAIT_S`(0.2초)만 기다리고 이번만 기하 규칙으로 물러선다
"""
import os, sys, time, subprocess
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PAIRS = [("이 문서는 띄어쓰기가", "없는 문장입니다"), ("정체성이 분명한 성향적", "관점을 가장"),
         ("시세조사", "결과를 반영하여"), ("의무사", "용대상"), ("아스팔트 혼합물의", "다짐 특성을")]


def case_a():
    import threading
    g = {"worst": 0.0, "last": time.perf_counter(), "run": True}

    def hb():
        while g["run"]:
            now = time.perf_counter(); g["worst"] = max(g["worst"], now - g["last"]); g["last"] = now
            time.sleep(0.005)
    threading.Thread(target=hb, daemon=True).start(); time.sleep(0.2)
    from viewer import text_extract2 as tx
    got = [tx._join_sep(a, b, False) for a, b in PAIRS]
    g["run"] = False
    loaded = "kiwipiepy" in sys.modules
    from viewer.kiwi_space import make_kiwi          # 비교용 — 이 프로세스의 kiwi(자식과 같은 설정)
    k = make_kiwi()
    tx._KIWI["obj"] = k
    from viewer import kiwi_space as ks
    ks._state["bad"] = True                          # 이제부터 이 프로세스의 kiwi 로
    want = [tx._join_sep(a, b, False) for a, b in PAIRS]
    print("RESULT", round(g["worst"], 3), int(loaded), int(got == want), repr(got), repr(want))


def case_b():
    from viewer import text_extract2 as tx, kiwi_space as ks
    ks.set_ui_thread()
    t = time.perf_counter()
    r = tx._join_sep("이 문서는 띄어쓰기가", "없는 문장입니다", False)
    dt = time.perf_counter() - t
    ok = ks._ready.wait(60) and ks.ready()
    r2 = tx._join_sep("이 문서는 띄어쓰기가", "없는 문장입니다", False)
    print("RESULT", "|".join([str(round(dt, 3)), repr(r), str(int(ok)), repr(r2)]))


def case_c():
    from viewer import text_extract2 as tx, kiwi_space as ks
    tx._ko_wants_space("이 문서는", "없는 문장")
    print("RESULT", ks._state["proc"].pid, int(ks.ready()))
    sys.stdout.flush()
    os._exit(0)


def case_d():
    from viewer import text_extract2 as tx, kiwi_space as ks
    ks._command = lambda addr: [os.path.join(HERE, "no_such_polypdf.exe"), addr]
    import threading
    res = {}
    th = threading.Thread(target=lambda: res.setdefault("w", tx._join_sep("이 문서는 띄어쓰기가", "없는 문장입니다", False)))
    ks.set_ui_thread()
    ui = tx._join_sep("이 문서는 띄어쓰기가", "없는 문장입니다", False)     # UI: 기다리지 않음 → 기하(붙임)
    th.start(); th.join(60)
    w2 = tx._ko_wants_space("이 문서는 띄어쓰기가", "없는 문장입니다")       # UI 스레드 — 실패 뒤에도 짓지 않는다
    print("RESULT", "|".join([str(int(ks.failed())), repr(ui), repr(res.get("w")), str(int(tx._KIWI["obj"] is not None)), str(int(w2))]))


def case_e():
    from viewer import text_extract2 as tx, kiwi_space as ks
    ks.start(); ks._ready.wait(60)
    ks.set_ui_thread()
    ks._io_lock.acquire()                            # 다른 스레드가 묻는 중(자식이 바쁨)인 것처럼
    t = time.perf_counter()
    r = tx._ko_wants_space("이 문서는 띄어쓰기가", "없는 문장입니다")
    dt = time.perf_counter() - t
    ks._io_lock.release()
    r2 = tx._ko_wants_space("이 문서는 띄어쓰기가", "없는 문장입니다")
    print("RESULT", "|".join([str(int(ks.ready())), str(round(dt, 3)), str(int(r)), str(int(r2))]))


if len(sys.argv) > 2 and sys.argv[1] == "--case":
    {"a": case_a, "b": case_b, "c": case_c, "d": case_d, "e": case_e}[sys.argv[2]]()
    sys.stdout.flush()
    os._exit(0)

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def run(case):
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "--case", case],
                       capture_output=True, text=True, encoding="utf-8", timeout=240)
    lines = [l for l in r.stdout.splitlines() if l.startswith("RESULT")]
    return (lines[-1].split(" ", 1)[1] if lines else ""), (r.stderr or "")[-400:]


out, err = run("a")
p = out.split(" ", 3)
chk(len(p) == 4, "A 실행됨", err)
if len(p) == 4:
    chk(p[1] == "0", "A 이 프로세스에는 kiwipiepy 가 실리지 않는다(자식 프로세스에 묻는다)", out)
    chk(float(p[0]) < 0.3, "A 자식이 kiwi 를 짓는 동안 다른 스레드가 0.3초 넘게 막히지 않는다(종전 1.2초)", out)
    chk(p[2] == "1", "A 판정은 이 프로세스의 kiwi 와 같다", out)

out, err = run("b")
p = out.split("|")
chk(len(p) == 4, "B 실행됨", err)
if len(p) == 4:
    chk(float(p[0]) < 0.1, "B UI 스레드는 자식의 준비를 기다리지 않는다", out)
    chk(p[1] == "''", "B 준비 전 UI 스레드는 기하 규칙(꽉 찬 줄 = 붙임)", out)
    chk(p[2] == "1", "B 자식은 뒤에서 준비된다", out)
    chk(p[3] == "' '", "B 준비 뒤에는 kiwi 판정(어절 경계를 띄운다 — 기하 규칙은 붙인다)", out)

out, err = run("c")
p = out.split(" ")
chk(len(p) == 2 and p[1] == "1", "C 자식이 준비됐다", out + err)
if len(p) == 2 and p[0].isdigit():
    time.sleep(2.0)
    t = subprocess.run(["tasklist", "/FI", "PID eq %s" % p[0], "/NH", "/FO", "CSV"],
                       capture_output=True, text=True)
    chk('"%s"' % p[0] not in t.stdout, "C 부모가 os._exit 로 끝나면 자식도 끝난다", t.stdout.strip())

out, err = run("d")
p = out.split("|")
chk(len(p) == 5, "D 실행됨", err)
if len(p) == 5:
    chk(p[0] == "1", "D 자식을 못 띄우면 실패로 표시", out)
    chk(p[1] == "''", "D 그때 UI 스레드는 기다리지 않고 기하 규칙", out)
    chk(p[3] == "1" and p[2] == "' '", "D 워커는 이 프로세스의 kiwi 로 물러선다(품질 유지)", out)
    chk(p[4] == "0", "D UI 스레드는 이 프로세스의 kiwi 도 부르지 않는다(짓는 정지)", out)

out, err = run("e")
p = out.split("|")
chk(len(p) == 4 and p[0] == "1", "E 실행됨(자식 준비)", out + err)
if len(p) == 4:
    chk(float(p[1]) < 0.5, "E 다른 스레드가 묻는 중이면 UI 스레드는 0.2초만 기다리고 물러선다", out)
    chk(p[2] == "0" and p[3] == "1", "E 그때만 기하 규칙, 다음에는 다시 kiwi", out)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
