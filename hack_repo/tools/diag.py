#!/usr/bin/env python3
"""Expected vs got for every task; for coding runs visible + hidden tests.
Usage: python tools/diag.py train_tasks [train_tasks_key] [--only-fail]"""
import json, os, subprocess, sys

root = os.path.abspath(sys.argv[1])
keys = root + "_key"
for a in sys.argv[2:]:
    if not a.startswith("--"):
        keys = os.path.abspath(a)
only_fail = "--only-fail" in sys.argv
meta = json.load(open(root + "_meta.json", encoding="utf-8")) if os.path.isfile(root + "_meta.json") else {}
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

def run(path, cwd):
    p = subprocess.run([sys.executable, path], cwd=cwd, capture_output=True, text=True,
                       timeout=120, env=dict(env, PYTHONPATH=cwd))
    return p.returncode, (p.stderr or p.stdout)

for name in sorted(os.listdir(root)):
    d = os.path.join(root, name)
    tj = os.path.join(d, "task.json")
    if not os.path.isfile(tj):
        continue
    m = json.load(open(tj, encoding="utf-8"))
    ws = os.path.join(d, "workspace") if os.path.isdir(os.path.join(d, "workspace")) else d
    ap = None
    for cand in (os.path.join(ws, "answer.txt"), os.path.join(d, "answer.txt")):
        if os.path.isfile(cand):
            ap = cand; break
    got = open(ap, encoding="utf-8").read().strip() if ap else None
    tier = meta.get(name, {}).get("tier", "?")
    if m["check"] == "unittest":
        rcv, errv = 0, ""
        for tf in [f for f in sorted(os.listdir(ws)) if f.startswith("test_") and f.endswith(".py")]:
            rcv, errv = run(os.path.join(ws, tf), ws)
            if rcv != 0:
                break
        hid = os.path.join(keys, name + "_hidden.py")
        rch, errh = (None, "")
        if os.path.isfile(hid):
            rch, errh = run(os.path.abspath(hid), ws)
        ok = got == "DONE" and rcv == 0 and rch in (0, None)
        if only_fail and ok:
            continue
        print(f"{name} tier={tier} answer={got!r} visible_rc={rcv} hidden_rc={rch}")
        src = errh if rch else (errv if rcv else "")
        if src:
            tail = [l.strip() for l in src.splitlines() if l.strip()][-5:]
            print("   " + " | ".join(tail)[:400])
    else:
        exp = str(m["expected"])
        if m["check"] == "exact_int":
            try:
                ok = got is not None and int(got) == int(exp)
            except ValueError:
                ok = False
        else:
            ok = got == exp
        if only_fail and ok:
            continue
        print(f"{name} tier={tier} {m['check']} expected={exp!r} got={got!r}")