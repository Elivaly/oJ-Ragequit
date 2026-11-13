#!/usr/bin/env python3
"""Usage: python tools/grade.py train_tasks [train_tasks_key]"""
import json, os, subprocess, sys

root = os.path.abspath(sys.argv[1])
keys = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else root + "_key")
meta = {}
if os.path.isfile(root + "_meta.json"):
    meta = json.load(open(root + "_meta.json", encoding="utf-8"))
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
total = got = n = ok = 0
feas_total = feas_ok = 0
per_tier = {}

def run_py(path, cwd):
    e = dict(env, PYTHONPATH=cwd)
    return subprocess.run([sys.executable, path], cwd=cwd, capture_output=True,
                          text=True, timeout=120, env=e).returncode

for name in sorted(os.listdir(root)):
    d = os.path.join(root, name)
    tj = os.path.join(d, "task.json")
    if not os.path.isfile(tj):
        continue
    m = json.load(open(tj, encoding="utf-8"))
    n += 1; total += m["reward"]
    info = meta.get(name, {"tier": 0, "feasible": 1})
    tier = info["tier"]
    st = per_tier.setdefault(tier, [0, 0, 0])
    st[1] += 1
    if info["feasible"]:
        feas_total += 1
    ws = os.path.join(d, "workspace") if os.path.isdir(os.path.join(d, "workspace")) else d
    ans = None
    for ap in (os.path.join(ws, "answer.txt"), os.path.join(d, "answer.txt")):
        if os.path.isfile(ap):
            ans = open(ap, encoding="utf-8").read().strip(); break
    passed = False
    if ans is not None:
        if m["check"] == "unittest":
            if ans == "DONE":
                tests = [f for f in sorted(os.listdir(ws))
                         if f.startswith("test_") and f.endswith(".py")]
                passed = bool(tests) and all(run_py(os.path.join(ws, t), ws) == 0 for t in tests)
                hidden = os.path.join(keys, name + "_hidden.py")
                if passed and os.path.isfile(hidden):
                    passed = run_py(os.path.abspath(hidden), ws) == 0
        elif m["check"] == "exact_int":
            try:
                passed = int(ans) == int(m["expected"])
            except (ValueError, TypeError):
                passed = False
        else:
            passed = ans == str(m["expected"])
    if passed:
        ok += 1; got += m["reward"]; st[0] += 1; st[2] += m["reward"]
        if info["feasible"]:
            feas_ok += 1
    print(f"{'OK  ' if passed else 'FAIL'} {name} tier={tier} reward={m['reward']}"
          + ("" if info["feasible"] else "  (infeasible)"))
print(f"\nsolved {ok}/{n}, reward {got}/{total}")
print(f"feasible solved {feas_ok}/{feas_total}")
for t in sorted(per_tier):
    a, b, r = per_tier[t]
    print(f"  tier {t}: {a}/{b} solved, reward {r}")