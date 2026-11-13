#!/usr/bin/env python3
"""Varied-difficulty task generator in the organizer's format.
Usage: python tools/gen_hard.py [out_dir] [seed] [--mix=mixed|easy|hard]
Tiers 0..4 (trivial..extreme), ~20% infeasible, weak visible tests + strong hidden tests.
Keys (clean code + hidden tests) go to <out_dir>_key/ -- never mount that into the container.
"""
import json, math, os, random, sys

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = ARGS[0] if ARGS else "train_tasks"
SEED = int(ARGS[1]) if len(ARGS) > 1 else 42
MIX = "mixed"
for a in sys.argv[1:]:
    if a.startswith("--mix="):
        MIX = a.split("=", 1)[1]
rng = random.Random(SEED)
KEY = OUT + "_key"
os.makedirs(KEY, exist_ok=True)
labels, meta = {}, {}
cnt = {"coding": 0, "data_analysis": 0, "math": 0, "search": 0}

BOILER = ("Work only inside the current directory. When you are done, write ONLY the final "
          "answer to the file answer.txt in the current directory (for example with bash: "
          "echo 42 > answer.txt).")
BOILER_DONE = ("Work only inside the current directory. When you are done, write ONLY the word "
               "DONE to the file answer.txt in the current directory (for example with bash: "
               "echo 42 > answer.txt).")
CODING_INSTR = ("Run `python3 test_mylib.py` in the current directory; some tests fail. "
                "Fix the bugs in mylib.py (do not edit the tests) until all tests pass. " + BOILER_DONE)
LIB_HEADER = '"""Utility helpers used by the reporting pipeline.\n\nAll functions must be pure and handle empty inputs gracefully.\n"""\n'

def tier_for(i):
    if MIX == "easy":
        return i % 3
    if MIX == "hard":
        return 2 + (i % 3)
    return i % 5

def emit(ttype, tier, instruction, expected, check, files, feasible=True, key_files=None):
    i = cnt[ttype]; cnt[ttype] += 1
    name = f"{ttype}_{i:04d}"
    d = os.path.join(OUT, name); os.makedirs(d, exist_ok=True)
    json.dump({"task_id": name, "task_type": ttype, "instruction": instruction,
               "reward": rng.randint(1, 5), "expected": expected, "check": check},
              open(os.path.join(d, "task.json"), "w"), indent=1)
    for fn, body in files.items():
        p = os.path.join(d, "workspace", fn)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(body)
    for fn, body in (key_files or {}).items():
        open(os.path.join(KEY, fn), "w", encoding="utf-8").write(body)
    labels[name] = int(feasible)
    meta[name] = {"type": ttype, "tier": tier, "feasible": int(feasible)}

# ---------------- coding specs ----------------
def s_add(r):
    a, b, c = r.randint(2, 40), r.randint(2, 40), r.randint(2, 30)
    return dict(name="add", clean="def add(a, b):\n    return a + b\n",
                bugs=["def add(a, b):\n    return a - b\n",
                      "def add(a, b):\n    return a + b + 1\n"],
                vis=[f"self.assertEqual(add({a}, {b}), {a + b})"],
                hid=[f"self.assertEqual(add(-{c}, {c}), 0)", "self.assertEqual(add(0, 0), 0)"])

def s_double(r):
    d, e = r.randint(3, 15), r.randint(2, 9)
    return dict(name="double", clean="def double(x):\n    return x * 2\n",
                bugs=["def double(x):\n    return x + 2\n", "def double(x):\n    return x * x\n"],
                vis=[f"self.assertEqual(double({d}), {2 * d})"],
                hid=["self.assertEqual(double(0), 0)", f"self.assertEqual(double(-{e}), {-2 * e})"])

def s_total(r):
    xs = [r.randint(1, 99) for _ in range(r.randint(4, 7))]
    return dict(name="total",
                clean="def total(xs):\n    s = 0\n    for i in range(len(xs)):\n        s += xs[i]\n    return s\n",
                bugs=["def total(xs):\n    s = 0\n    for i in range(len(xs) - 1):\n        s += xs[i]\n    return s\n"],
                vis=[f"self.assertEqual(total({xs + [0]}), {sum(xs)})"],
                hid=[f"self.assertEqual(total({xs}), {sum(xs)})", "self.assertEqual(total([]), 0)"])

def s_biggest(r):
    m = r.randint(60, 99); rest = [r.randint(1, 50) for _ in range(4)]; c = r.randint(2, 9)
    return dict(name="biggest",
                clean="def biggest(xs):\n    best = xs[0]\n    for x in xs:\n        if x > best:\n            best = x\n    return best\n",
                bugs=["def biggest(xs):\n    best = xs[0]\n    for x in xs:\n        if x < best:\n            best = x\n    return best\n"],
                vis=[f"self.assertEqual(biggest({[c, c, c]}), {c})"],
                hid=[f"self.assertEqual(biggest({rest + [m]}), {m})"])

def s_reverse(r):
    pal = r.choice(["level", "radar", "civic", "kayak"])
    w = r.choice(["alpha", "gamma", "delta", "omega", "sigma"])
    return dict(name="reverse", clean="def reverse(s):\n    return s[::-1]\n",
                bugs=["def reverse(s):\n    return s[::1]\n"],
                vis=[f'self.assertEqual(reverse("{pal}"), "{pal}")'],
                hid=[f'self.assertEqual(reverse("{w}"), "{w[::-1]}")'])

def s_initials(r):
    n1 = r.choice(["Ada Lovelace", "Alan Turing", "Grace Hopper"])
    n2 = r.choice(["Edsger Dijkstra", "Barbara Liskov", "Donald Knuth"])
    ini = lambda n: "".join(p[0] for p in n.split())
    return dict(name="initials",
                clean='def initials(name):\n    parts = name.split()\n    return "".join(p[0] for p in parts)\n',
                bugs=['def initials(name):\n    parts = name.split()\n    return "".join(p[1] for p in parts)\n'],
                vis=[f'self.assertEqual(initials("{n1}"), "{ini(n1)}")'],
                hid=[f'self.assertEqual(initials("{n2}"), "{ini(n2)}")'])

def s_count_words(r):
    words = ["alpha", "beta", "gamma", "delta"]
    t = " ".join(r.choice(words) for _ in range(8))
    tc = {}
    for x in t.split():
        tc[x] = tc.get(x, 0) + 1
    return dict(name="count_words",
                clean="def count_words(text):\n    counts = {}\n    for w in text.split():\n        counts[w] = counts.get(w, 0) + 1\n    return counts\n",
                bugs=["def count_words(text):\n    counts = {}\n    for w in text.split():\n        counts[w] = counts.get(w, 1) + 1\n    return counts\n"],
                vis=[f'self.assertEqual(count_words("{t}"), {tc})'],
                hid=['self.assertEqual(count_words(""), {})'])

def s_most_common(r):
    return dict(name="most_common",
                clean="def most_common(counts):\n    return max(counts, key=counts.get)\n",
                bugs=["def most_common(counts):\n    return min(counts, key=counts.get)\n"],
                vis=['self.assertEqual(most_common({"a": 3, "b": 2, "c": 1}), "a")'],
                hid=['self.assertEqual(most_common({"x": 1, "y": 5}), "y")'])

def s_is_sorted(r):
    inc = sorted(r.sample(range(1, 90), 5))
    return dict(name="is_sorted",
                clean="def is_sorted(xs):\n    for i in range(len(xs) - 1):\n        if xs[i] > xs[i + 1]:\n            return False\n    return True\n",
                bugs=["def is_sorted(xs):\n    for i in range(len(xs) - 1):\n        if xs[i] >= xs[i + 1]:\n            return False\n    return True\n"],
                vis=[f"self.assertTrue(is_sorted({inc}))"],
                hid=["self.assertTrue(is_sorted([2, 2, 3, 5, 5]))",
                     "self.assertFalse(is_sorted([3, 1, 2]))"])

def s_clamp(r):
    x = r.randint(12, 18); y = r.randint(1, 9)
    return dict(name="clamp",
                clean="def clamp(x, lo, hi):\n    return min(max(x, lo), hi)\n",
                bugs=["def clamp(x, lo, hi):\n    return min(max(x, hi), lo)\n"],
                vis=[f"self.assertEqual(clamp({y}, 10, 20), 10)"],
                hid=[f"self.assertEqual(clamp({x}, 10, 20), {x})",
                     "self.assertEqual(clamp(99, 10, 20), 20)"])

def s_factorial(r):
    n = r.randint(5, 8)
    f = math.factorial(n)
    return dict(name="factorial",
                clean="def factorial(n):\n    r = 1\n    for i in range(1, n + 1):\n        r *= i\n    return r\n",
                bugs=["def factorial(n):\n    r = 1\n    for i in range(1, n):\n        r *= i\n    return r\n"],
                vis=["self.assertEqual(factorial(1), 1)"],
                hid=[f"self.assertEqual(factorial({n}), {f})", "self.assertEqual(factorial(0), 1)"])

def s_running_sum(r):
    a, b, c = r.randint(2, 9), r.randint(2, 9), r.randint(2, 9)
    return dict(name="running_sum",
                clean="def running_sum(xs):\n    out = []\n    acc = 0\n    for x in xs:\n        acc += x\n        out.append(acc)\n    return out\n",
                bugs=["def running_sum(xs):\n    out = []\n    for x in xs:\n        out.append(x)\n    return out\n"],
                vis=[f"self.assertEqual(running_sum([{a}]), [{a}])"],
                hid=[f"self.assertEqual(running_sum([{a}, {b}, {c}]), [{a}, {a + b}, {a + b + c}])"])

def s_gcd(r):
    return dict(name="gcd",
                clean="def gcd(a, b):\n    while b:\n        a, b = b, a % b\n    return a\n",
                bugs=["def gcd(a, b):\n    return a % b\n"],
                vis=["self.assertEqual(gcd(2, 4), 2)"],
                hid=["self.assertEqual(gcd(12, 18), 6)", "self.assertEqual(gcd(7, 13), 1)"])

def s_dedup(r):
    a, b = r.randint(2, 9), r.randint(10, 19)
    return dict(name="dedup",
                clean="def dedup(xs):\n    out = []\n    for x in xs:\n        if x not in out:\n            out.append(x)\n    return out\n",
                bugs=["def dedup(xs):\n    return sorted(set(xs))\n"],
                vis=[f"self.assertEqual(dedup([{a}, {b}]), [{a}, {b}])"],
                hid=[f"self.assertEqual(dedup([{b}, {a}, {b}]), [{b}, {a}])"])

def s_group_by(r):
    k1, k2 = r.choice(["a", "b"]), r.choice(["x", "y"])
    v1, v2, v3 = r.randint(1, 9), r.randint(1, 9), r.randint(1, 9)
    return dict(name="group_by",
                clean="def group_by(pairs):\n    out = {}\n    for k, v in pairs:\n        out.setdefault(k, []).append(v)\n    return out\n",
                bugs=["def group_by(pairs):\n    out = {}\n    for k, v in pairs:\n        out[k] = [v]\n    return out\n"],
                vis=[f'self.assertEqual(group_by([("{k1}", {v1}), ("{k2}", {v2})]), '
                     f'{{"{k1}": [{v1}], "{k2}": [{v2}]}})'],
                hid=[f'self.assertEqual(group_by([("{k1}", {v1}), ("{k1}", {v2}), ("{k2}", {v3})]), '
                     f'{{"{k1}": [{v1}, {v2}], "{k2}": [{v3}]}})',
                     "self.assertEqual(group_by([]), {})"])

def s_top_n(r):
    return dict(name="top_n",
                clean="def top_n(counts, n):\n    return sorted(counts, key=lambda k: (-counts[k], k))[:n]\n",
                bugs=["def top_n(counts, n):\n    return sorted(counts)[:n]\n"],
                vis=['self.assertEqual(top_n({"a": 9, "b": 5, "c": 1}, 2), ["a", "b"])'],
                hid=['self.assertEqual(top_n({"z": 9, "y": 5, "a": 1}, 2), ["z", "y"])',
                     'self.assertEqual(top_n({"b": 3, "a": 3}, 1), ["a"])'])

def s_transpose(r):
    return dict(name="transpose",
                clean="def transpose(m):\n    return [[m[r][c] for r in range(len(m))] for c in range(len(m[0]))]\n",
                bugs=["def transpose(m):\n    return [[m[c][r] for r in range(len(m))] for c in range(len(m[0]))]\n"],
                vis=["self.assertEqual(transpose([[1, 2], [2, 1]]), [[1, 2], [2, 1]])"],
                hid=["self.assertEqual(transpose([[1, 2, 3], [4, 5, 6]]), [[1, 4], [2, 5], [3, 6]])"])

def s_cummax(r):
    a = r.randint(2, 9); b = a + r.randint(1, 9); c = r.randint(1, a - 1)
    return dict(name="cummax",
                clean="def cummax(xs):\n    out = []\n    best = None\n    for x in xs:\n        best = x if best is None or x > best else best\n        out.append(best)\n    return out\n",
                bugs=["def cummax(xs):\n    return list(xs)\n"],
                vis=[f"self.assertEqual(cummax([{a}, {b}]), [{a}, {b}])"],
                hid=[f"self.assertEqual(cummax([{b}, {c}, {a}]), [{b}, {b}, {b}])",
                     "self.assertEqual(cummax([]), [])"])

SPECS = [s_add, s_double, s_total, s_biggest, s_reverse, s_initials, s_count_words,
         s_most_common, s_is_sorted, s_clamp, s_factorial, s_running_sum, s_gcd,
         s_dedup, s_group_by, s_top_n, s_transpose, s_cummax]
NONTRAP = [s_add, s_double, s_initials, s_count_words, s_most_common]
def _tests(names, asserts):
    body = "import unittest\nfrom mylib import " + ", ".join(names) + "\n\n"
    body += "class TestMylib(unittest.TestCase):\n"
    for i, a in enumerate(asserts):
        body += f"    def test_{i:02d}(self):\n        {a}\n"
    body += '\nif __name__ == "__main__":\n    unittest.main()\n'
    return body

BROKEN_TESTS = ("import unittest\nfrom mylib import add\n\nclass T(unittest.TestCase):\n"
                "    def test_a(self)\n        self.assertEqual(add(2, 3), 5)\n\n"
                'if __name__ == "__main__":\n    unittest.main()\n')
CONTRA_TESTS = ("import unittest\nfrom mylib import add\n\nclass T(unittest.TestCase):\n"
                "    def test_a(self):\n        self.assertEqual(add(2, 3), 5)\n"
                "    def test_b(self):\n        self.assertEqual(add(2, 3), 6)\n\n"
                'if __name__ == "__main__":\n    unittest.main()\n')

def gen_coding(n=25, bad=5):
    ks = [1, 2, 4, 8, 12]
    nbug = [1, 2, 3, 6, 9]
    for i in range(n):
        tier = tier_for(i)
        if i < bad:
            tests = CONTRA_TESTS if i % 2 == 0 else BROKEN_TESTS
            lib = "def add(a, b):\n    return a + b\n"
            emit("coding", tier, CODING_INSTR, "tests_pass", "unittest",
                 {"mylib.py": lib, "test_mylib.py": tests}, False,
                 {f"coding_{i:04d}_hidden.py": tests})
            continue
        k = ks[tier]
        pool = rng.sample(SPECS, k)
        nt = [sp for sp in NONTRAP if sp not in pool]
        if not any(sp in NONTRAP for sp in pool) and nt:
            pool[0] = rng.choice(nt)
        built = [sp(rng) for sp in pool]
        names = [b["name"] for b in built]
        bug_idx = set(rng.sample(range(k), min(nbug[tier], k)))
        nt_idx = [j for j, sp in enumerate(pool) if sp in NONTRAP]
        if nt_idx and not (bug_idx & set(nt_idx)):
            bug_idx.add(rng.choice(nt_idx))
        buggy = LIB_HEADER + "\n\n".join(rng.choice(b["bugs"]) if j in bug_idx else b["clean"]
                                         for j, b in enumerate(built)) + "\n"
        clean = LIB_HEADER + "\n\n".join(b["clean"] for b in built) + "\n"
        vis = [a for b in built for a in b["vis"]]
        hid = [a for b in built for a in b["vis"] + b["hid"]]
        emit("coding", tier, CODING_INSTR, "tests_pass", "unittest",
             {"mylib.py": buggy, "test_mylib.py": _tests(names, vis)}, True,
             {f"coding_{i:04d}.py": clean, f"coding_{i:04d}_hidden.py": _tests(names, hid)})

# ---------------- data_analysis ----------------
def gen_data(n=25, bad=5):
    regions = ["north", "south", "east", "west"]
    products = ["widget", "gadget", "gizmo", "doohickey"]
    managers = ["Ito", "Novak", "Silva"]
    rowcounts = [20, 200, 2000, 8000, 20000]
    for i in range(n):
        tier = tier_for(i)
        nrows = rowcounts[tier]
        rows = []
        for oid in range(1, nrows + 1):
            rows.append((oid, rng.choice(regions), rng.choice(products),
                         rng.randint(1, 12), rng.randint(1, 40), rng.randint(5, 50)))
        csv = "order_id,region,product,month,units,price\n" + "".join(
            f"{a},{b},{c},{d},{e},{f}\n" for a, b, c, d, e, f in rows)
        files = {"sales.csv": csv}
        head = f"The file sales.csv has columns order_id,region,product,month,units,price ({nrows} rows)."
        costs = {}
        if tier >= 3:
            costs = {p: rng.randint(1, 40) for p in products}
            files["products.csv"] = "product,cost\n" + "".join(
                f"{p},{c}\n" for p, c in costs.items())
            head += " The file products.csv has columns product,cost."
        region_mgr = {}
        if tier >= 4:
            region_mgr = {g: managers[j % len(managers)] for j, g in enumerate(regions)}
            files["regions.csv"] = "region,manager\n" + "".join(
                f"{g},{m}\n" for g, m in region_mgr.items())
            head += " The file regions.csv has columns region,manager."
        tail = " Use bash with python3 to compute it. " + BOILER
        if i < bad:
            if i % 2 == 0:
                q = " What is the total value of the discount column across all orders?"
            else:
                q = (" How many units are recorded in the file returns.csv?"
                       " The file returns.csv is supposed to be in the working directory.")
            emit("data_analysis", tier, head + q + tail, "", "exact_int", files, False)
            continue
        p = rng.choice(products); g = rng.choice(regions)
        m1 = rng.randint(1, 9); m2 = m1 + rng.randint(1, 3)
        if tier == 0:
            q = f"How many units of product '{p}' were sold in total?"
            exp = sum(e for a, b, c, d, e, f in rows if c == p)
            check = "exact_int"
        elif tier == 1:
            q = f"How many units of product '{p}' were sold in months {m1} through {m2} inclusive?"
            exp = sum(e for a, b, c, d, e, f in rows if c == p and m1 <= d <= m2)
            check = "exact_int"
        elif tier == 2:
            q = f"What is the total revenue (units times price) for region '{g}'?"
            exp = sum(e * f for a, b, c, d, e, f in rows if b == g)
            check = "exact_int"
        elif tier == 3:
            q = (f"What is the total profit for product '{p}', where profit per order is "
                 "units times (price minus the product cost from products.csv)?")
            exp = sum(e * (f - costs[c]) for a, b, c, d, e, f in rows if c == p)
            check = "exact_int"
        else:
            mgr = rng.choice(managers)
            q = (f"Among the regions whose manager is '{mgr}' in regions.csv, which region has "
                 "the highest total revenue (units times price)? If several tie, answer the "
                 "alphabetically first one.")
            rev = {}
            for a, b, c, d, e, f in rows:
                rev[b] = rev.get(b, 0) + e * f
            cands = [x for x in regions if region_mgr[x] == mgr]
            exp = sorted(cands, key=lambda x: (-rev.get(x, 0), x))[0]
            check = "exact_str"
        emit("data_analysis", tier, head + " " + q + tail, str(exp), check, files)

# ---------------- math ----------------
def _ndiv(a, b, d):
    return b // d - (a - 1) // d

def gen_math(n=25, bad=5):
    lens = [2, 4, 8, 16, 30]
    for i in range(n):
        tier = tier_for(i)
        if i < bad:
            start = rng.randint(500, 3000)
            if i % 2 == 0:
                text = (f"A warehouse starts with {start} boxes. Then the stock is split equally "
                        "into 0 warehouses and it keeps one share (rounded down). "
                        "How many boxes does it have at the end?")
            else:
                text = (f"A warehouse starts with {start} boxes. It ships an unspecified number "
                        "of boxes each day for 3 days. How many boxes does it have at the end?")
            emit("math", tier, text + " Compute it with the bash tool (python3 -c). " + BOILER,
                 "", "exact_int", {}, False)
            continue
        flavor = (i % 3) if tier >= 3 else 0
        if flavor == 1:
            A = rng.randint(10 ** 6, 10 ** 9); B = A + rng.randint(10 ** 9, 10 ** 12)
            d1, d2 = rng.choice([3, 4, 6, 7]), rng.choice([5, 9, 11])
            lcm = d1 * d2 // math.gcd(d1, d2)
            exp = _ndiv(A, B, d1) + _ndiv(A, B, d2) - _ndiv(A, B, lcm)
            text = (f"How many integers from {A} to {B} inclusive are divisible by {d1} or by {d2}?")
        elif flavor == 2:
            if i % 2 == 0:
                N = rng.randint(300, 1500)
                exp = sum(int(c) for c in str(7 ** N))
                text = f"What is the sum of the decimal digits of 7 raised to the power {N}?"
            else:
                A = rng.randint(2, 99); B = rng.randint(1000, 50000); M = rng.randint(1000, 99999)
                exp = pow(A, B, M)
                text = f"What is ({A} raised to the power {B}) modulo {M}?"
        else:
            start = rng.randint(500, 3000)
            v = start
            parts = [f"A warehouse starts with {start} boxes."]
            for _ in range(lens[tier]):
                op = rng.choice(["split", "double", "ship", "receive", "lose", "gain"])
                if op == "split":
                    k = rng.randint(2, 4); v //= k
                    parts.append(f"Then the stock is split equally into {k} warehouses and it keeps one share (rounded down).")
                elif op == "double":
                    v *= 2
                    parts.append("Then the stock is doubled by merging with a sister warehouse.")
                elif op == "ship":
                    per = rng.randint(5, 40); days = rng.randint(2, 5)
                    if v < per * days:
                        continue
                    v -= per * days
                    parts.append(f"It ships {per} boxes per day for {days} days.")
                elif op == "receive":
                    k = rng.randint(2, 4); each = rng.randint(20, 120); v += k * each
                    parts.append(f"It receives {k} deliveries of {each} boxes each.")
                elif op == "lose":
                    p = rng.randint(5, 30); v -= v * p // 100
                    parts.append(f"It loses {p} percent of the stock (rounded down).")
                else:
                    p = rng.randint(5, 30); v += v * p // 100
                    parts.append(f"It gains {p} percent of the stock (rounded down).")
            if tier == 4:
                if v > 1000:
                    v -= 50
                    parts.append("If the stock exceeds 1000 boxes it ships 50 boxes, otherwise it receives 30 boxes.")
                else:
                    v += 30
                    parts.append("If the stock exceeds 1000 boxes it ships 50 boxes, otherwise it receives 30 boxes.")
            text = " ".join(parts) + " How many boxes does it have at the end?"
            exp = v
        emit("math", tier, text + " Compute it with the bash tool (python3 -c). " + BOILER,
             str(exp), "exact_int", {})

# ---------------- search ----------------
FIRST = ["Irina", "Sergei", "Anna", "Boris", "Elena", "Dmitry", "Olga", "Pavel", "Maria",
         "Igor", "Nina", "Anton", "Vera", "Kirill", "Sofia", "Roman", "Lidia", "Taras",
         "Yulia", "Gleb"]
LAST = ["Smith", "Garcia", "Ivanov", "Chen", "Muller", "Rossi", "Kim", "Novak", "Silva",
        "Jones", "Weber", "Costa", "Nakamura", "Petrov", "Dubois", "Larsen", "Kowalski",
        "Ferrari", "Okafor", "Haddad"]
CPRE = ["Nor", "Blue", "Saffron", "Kestrel", "Mira", "Vostok", "Gran", "Lumen", "Orbit",
        "Ferro", "Cinder", "Halcyon", "Tundra", "Quill", "Zephyr"]
CSUF = ["tech", "peak", "labs", "line", "data", "works", "forge", "byte", "grid", "span",
        "core", "path", "loop", "field", "gate"]
CITIES = ["Osaka", "Lyon", "Tulsa", "Bergen", "Graz", "Porto", "Kazan", "Denver", "Lima",
          "Perth", "Uppsala", "Toledo", "Bruges", "Aarhus", "Split"]
ROLES = ["engineer", "analyst", "designer", "manager", "researcher", "architect"]

def gen_search(n=25, bad=5):
    sizes = [8, 20, 60, 150, 300]
    for i in range(n):
        tier = tier_for(i)
        nfiles = sizes[tier]
        ncomp = max(3, nfiles // 3)
        npers = nfiles - ncomp
        comps = rng.sample([a + b for a in CPRE for b in CSUF], ncomp)
        names = rng.sample([a + " " + b for a in FIRST for b in LAST], npers)
        comp_hq = {c: CITIES[j % len(CITIES)] for j, c in enumerate(comps)}
        persons = []
        for j, nm in enumerate(names):
            persons.append({"name": nm, "born": rng.randint(1960, 2000),
                            "employer": comps[j % ncomp], "role": rng.choice(ROLES),
                            "manager": None})
        for j, p in enumerate(persons):
            p["manager"] = persons[(j + 1) % npers]["name"]
        by_name = {p["name"]: p for p in persons}
        files = {}
        for j, c in enumerate(comps):
            files[f"kb/company_{j:03d}.md"] = (f"# {c}\n\nHeadquarters: {comp_hq[c]}.\n"
                                              f"Founded: {rng.randint(1950, 2015)}.\n")
        for j, p in enumerate(persons):
            files[f"kb/person_{j:03d}.md"] = (f"# {p['name']}\n\nBorn: {p['born']} in "
                                             f"{CITIES[j % len(CITIES)]}.\nEmployer: {p['employer']}.\n"
                                             f"Role: {p['role']}.\nManager: {p['manager']}.\n")
        head = "The directory kb/ contains a small knowledge base of markdown files. "
        tail = " Use the file tools or bash (ls, grep, cat) to find it. " + BOILER
        if i < bad:
            if i % 3 == 0:
                q = "In which year was Zoltan Vega born?"
            elif i % 3 == 1:
                q = f"What is the phone number of {persons[0]['name']}?"
            else:
                q = "In which city is the headquarters of the company Nonexistent Dynamics?"
            emit("search", tier, head + q + tail, "", "exact_str", dict(files), False)
            continue
        p = persons[i % npers]
        if tier == 0:
            q, exp, check = f"In which year was {p['name']} born?", str(p["born"]), "exact_str"
        elif tier == 1:
            q = f"In which city is the headquarters of {p['name']}'s employer?"
            exp, check = comp_hq[p["employer"]], "exact_str"
        elif tier == 2:
            mgr = by_name[p["manager"]]
            q = (f"In which city is the headquarters of the employer of {p['name']}'s manager?")
            exp, check = comp_hq[mgr["employer"]], "exact_str"
        elif tier == 3:
            c = max(comps, key=lambda x: sum(1 for pp in persons if pp["employer"] == x))
            Y = 1985
            exp = str(sum(1 for pp in persons if pp["employer"] == c and pp["born"] < Y))
            q = f"How many employees of {c} were born before {Y}?"
            check = "exact_int"
        else:
            Y = 1985
            counts = {}
            for pp in persons:
                if pp["born"] > Y:
                    counts[pp["employer"]] = counts.get(pp["employer"], 0) + 1
            exp = sorted(counts, key=lambda x: (-counts[x], x))[0]
            q = (f"Which company employs the most people born after {Y}? "
                 "If several tie, answer the alphabetically first one.")
            check = "exact_str"
        emit("search", tier, head + q + tail, exp, check, dict(files))

gen_coding(); gen_data(); gen_math(); gen_search()
json.dump(labels, open(OUT + "_labels.json", "w"), indent=1)
json.dump(meta, open(OUT + "_meta.json", "w"), indent=1)
tiers = {}
for m in meta.values():
    tiers[m["tier"]] = tiers.get(m["tier"], 0) + 1
print(f"generated {sum(cnt.values())} tasks in {OUT}/ "
      f"({sum(1 for v in labels.values() if not v)} infeasible), tiers {dict(sorted(tiers.items()))}")
print(f"keys (clean code + hidden tests) in {KEY}/ -- do NOT mount it")