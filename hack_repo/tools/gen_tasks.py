#!/usr/bin/env python3
"""~100 tasks in the organizer's format (task.json + workspace/), + feasibility labels.
Usage: python tools/gen_tasks.py [out_dir] [seed]"""
import json, os, random, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "train_tasks"
rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 42)
BOILER = ("Work only inside the current directory. When you are done, write ONLY the final "
          "answer to the file answer.txt in the current directory (for example with bash: "
          "echo 42 > answer.txt).")
BOILER_DONE = ("Work only inside the current directory. When you are done, write ONLY the word "
               "DONE to the file answer.txt in the current directory (for example with bash: "
               "echo 42 > answer.txt).")
labels, cnt = {}, {"coding": 0, "data_analysis": 0, "math": 0, "search": 0}
KEY = OUT + "_key"; os.makedirs(KEY, exist_ok=True)

def emit(ttype, instruction, expected, check, files, feasible=True):
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
    labels[name] = int(feasible)

CODING_TEMPLATES = [
    ("def add(a, b):\n    return a - b\n\ndef double(x):\n    return x + 2\n",
     "def add(a, b):\n    return a + b\n\ndef double(x):\n    return x * 2\n",
     "import unittest\nfrom mylib import add, double\n\nclass TestOps(unittest.TestCase):\n"
     "    def test_add(self):\n        self.assertEqual(add({a}, {b}), {ab})\n"
     "        self.assertEqual(add(-{c}, {c}), 0)\n"
     "    def test_double(self):\n        self.assertEqual(double({d}), {d2})\n\n"
     'if __name__ == "__main__":\n    unittest.main()\n'),
    ("def total(xs):\n    s = 0\n    for i in range(len(xs) - 1):\n        s += xs[i]\n    return s\n\n"
     "def biggest(xs):\n    best = xs[0]\n    for x in xs:\n        if x < best:\n            best = x\n    return best\n",
     "def total(xs):\n    s = 0\n    for i in range(len(xs)):\n        s += xs[i]\n    return s\n\n"
     "def biggest(xs):\n    best = xs[0]\n    for x in xs:\n        if x > best:\n            best = x\n    return best\n",
     "import unittest\nfrom mylib import total, biggest\n\nclass TestStats(unittest.TestCase):\n"
     "    def test_total(self):\n        self.assertEqual(total({xs}), {s})\n"
     "    def test_biggest(self):\n        self.assertEqual(biggest({xs}), {m})\n\n"
     'if __name__ == "__main__":\n    unittest.main()\n'),
    ("def reverse(s):\n    return s[::1]\n\ndef initials(name):\n    parts = name.split()\n"
     '    return "".join(p[1] for p in parts)\n',
     "def reverse(s):\n    return s[::-1]\n\ndef initials(name):\n    parts = name.split()\n"
     '    return "".join(p[0] for p in parts)\n',
     "import unittest\nfrom mylib import reverse, initials\n\nclass TestStr(unittest.TestCase):\n"
     '    def test_reverse(self):\n        self.assertEqual(reverse("{w}"), "{wr}")\n'
     '    def test_initials(self):\n        self.assertEqual(initials("{n}"), "{ni}")\n\n'
     'if __name__ == "__main__":\n    unittest.main()\n'),
    ("def count_words(text):\n    counts = {}\n    for w in text.split():\n"
     "        counts[w] = counts.get(w, 1) + 1\n    return counts\n\n"
     "def most_common(counts):\n    return min(counts, key=counts.get)\n",
     "def count_words(text):\n    counts = {}\n    for w in text.split():\n"
     "        counts[w] = counts.get(w, 0) + 1\n    return counts\n\n"
     "def most_common(counts):\n    return max(counts, key=counts.get)\n",
     "import unittest\nfrom mylib import count_words, most_common\n\nclass TestCount(unittest.TestCase):\n"
     '    def test_count(self):\n        self.assertEqual(count_words("{t}"), {tc})\n'
     '    def test_most_common(self):\n        self.assertEqual(most_common(count_words("{t}")), "{mc}")\n\n'
     'if __name__ == "__main__":\n    unittest.main()\n'),
]
CODING_INSTR = ("Run `python3 test_mylib.py` in the current directory; some tests fail. "
                "Fix the bugs in mylib.py (do not edit the tests) until all tests pass. " + BOILER_DONE)

def gen_coding(n=25, bad=4):
    words = ["alpha", "beta", "gamma", "delta", "omega", "sigma"]
    names = ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Edsger Dijkstra"]
    for i in range(n):
        if i < bad:
            tests = ("import unittest\nfrom mylib import add\n\nclass T(unittest.TestCase):\n"
                     "    def test_a(self):\n        self.assertEqual(add(2, 3), 5)\n"
                     "    def test_b(self):\n        self.assertEqual(add(2, 3), 6)\n\n"
                     'if __name__ == "__main__":\n    unittest.main()\n')
            emit("coding", CODING_INSTR, "tests_pass", "unittest",
                 {"mylib.py": "def add(a, b):\n    return a + b\n", "test_mylib.py": tests}, False)
            continue
        buggy, clean, tests = CODING_TEMPLATES[i % len(CODING_TEMPLATES)]
        a, b, c, d = rng.randint(2, 30), rng.randint(2, 30), rng.randint(2, 20), rng.randint(2, 15)
        xs = [rng.randint(1, 99) for _ in range(rng.randint(4, 7))]
        w = rng.choice(words); n_ = rng.choice(names)
        t = " ".join(rng.choice(words) for _ in range(8))
        tc = {}
        for x in t.split():
            tc[x] = tc.get(x, 0) + 1
        mc = max(tc, key=tc.get)
        tests = tests.format(a=a, b=b, ab=a + b, c=c, d=d, d2=2 * d, xs=xs, s=sum(xs), m=max(xs),
                             w=w, wr=w[::-1], n=n_, ni="".join(p[0] for p in n_.split()),
                             t=t, tc=tc, mc=mc)
        emit("coding", CODING_INSTR, "tests_pass", "unittest",
             {"mylib.py": buggy, "test_mylib.py": tests})
        open(os.path.join(KEY, f"coding_{i:04d}.py"), "w").write(clean)

def gen_data(n=25, bad=5):
    regions = ["north", "south", "east", "west"]; products = ["widget", "gadget", "gizmo", "doohickey"]
    for i in range(n):
        nrows = rng.choice([20, 50, 120, 300]); rows = []
        for oid in range(1, nrows + 1):
            rows.append({"order_id": oid, "region": rng.choice(regions), "product": rng.choice(products),
                         "month": rng.randint(1, 12), "units": rng.randint(1, 40), "price": rng.randint(5, 50)})
        csv = "order_id,region,product,month,units,price\n" + "".join(
            f"{r['order_id']},{r['region']},{r['product']},{r['month']},{r['units']},{r['price']}\n" for r in rows)
        head = f"The file sales.csv has columns order_id,region,product,month,units,price ({nrows} rows). "
        tail = " Use bash with python3 to compute it. " + BOILER
        if i < bad:
            q = ("How many units of product 'sprocket' were sold in months 1 through 6 inclusive?"
                 if i % 2 == 0 else "What is the total value of the discount column across all orders?")
            emit("data_analysis", head + q + tail, "", "exact_int", {"sales.csv": csv}, False)
            continue
        kind = i % 4; p = rng.choice(products); r_ = rng.choice(regions)
        m1 = rng.randint(1, 9); m2 = m1 + rng.randint(1, 3)
        if kind == 0:
            q = f"How many units of product '{p}' were sold in months {m1} through {m2} inclusive?"
            exp = sum(x["units"] for x in rows if x["product"] == p and m1 <= x["month"] <= m2)
        elif kind == 1:
            q = f"What is the total revenue (units times price) for region '{r_}'?"
            exp = sum(x["units"] * x["price"] for x in rows if x["region"] == r_)
        elif kind == 2:
            q = f"How many orders contain product '{p}'?"; exp = sum(1 for x in rows if x["product"] == p)
        else:
            q = f"How many units were sold in month {m1} in total?"
            exp = sum(x["units"] for x in rows if x["month"] == m1)
        emit("data_analysis", head + q + tail, str(exp), "exact_int", {"sales.csv": csv})

def gen_math(n=25, bad=4):
    for i in range(n):
        start = rng.randint(500, 3000)
        if i < bad:
            text = (f"A warehouse starts with {start} boxes. Then the stock is split equally "
                    "into 0 warehouses and it keeps one share (rounded down). "
                    "How many boxes does it have at the end?")
            emit("math", text + " Compute it with the bash tool (python3 -c). " + BOILER, "", "exact_int", {}, False)
            continue
        v = start; parts = [f"A warehouse starts with {start} boxes."]
        for _ in range(rng.randint(2, 6)):
            op = rng.choice(["split", "double", "ship", "receive"])
            if op == "split":
                k = rng.randint(2, 4); v //= k
                parts.append(f"Then the stock is split equally into {k} warehouses and it keeps one share (rounded down).")
            elif op == "double":
                v *= 2; parts.append("Then the stock is doubled by merging with a sister warehouse.")
            elif op == "ship":
                per = rng.randint(5, 40); days = rng.randint(2, 5)
                if v < per * days: continue
                v -= per * days; parts.append(f"It ships {per} boxes per day for {days} days.")
            else:
                k = rng.randint(2, 4); each = rng.randint(20, 120); v += k * each
                parts.append(f"It receives {k} deliveries of {each} boxes each.")
        text = " ".join(parts) + " How many boxes does it have at the end?"
        emit("math", text + " Compute it with the bash tool (python3 -c). " + BOILER, str(v), "exact_int", {})

def gen_search(n=25, bad=5):
    first = ["Irina", "Sergei", "Anna", "Boris", "Elena", "Dmitry", "Olga", "Pavel"]
    last = ["Smith", "Garcia", "Ivanov", "Chen", "Muller", "Rossi", "Kim", "Novak"]
    cities = ["Osaka", "Lyon", "Tulsa", "Bergen", "Graz", "Porto", "Kazan", "Denver"]
    comps = ["Nortech", "Bluepeak", "Saffron Labs", "Kestrel AI", "Miraline", "Vostok Data"]
    roles = ["engineer", "analyst", "designer", "manager", "researcher"]
    persons, files, comp_hq = [], {}, {}
    for j in range(8):
        name = f"{first[j]} {last[j]}"; year = rng.randint(1960, 2000)
        comp = comps[j % len(comps)]; role = rng.choice(roles)
        persons.append((name, year, comp, role))
        files[f"kb/person_{j:02d}.md"] = f"# {name}\n\nBorn: {year} in {cities[j]}.\nEmployer: {comp}.\nRole: {role}.\n"
    for j, comp in enumerate(comps):
        hq = cities[(j + 3) % len(cities)]; comp_hq[comp] = hq
        files[f"kb/company_{j:02d}.md"] = f"# {comp}\n\nHeadquarters: {hq}.\nFounded: {rng.randint(1950, 2015)}.\n"
    head = "The directory kb/ contains a small knowledge base of markdown files. "
    tail = " Use the file tools or bash (ls, grep, cat) to find it. " + BOILER
    for i in range(n):
        if i < bad:
            q = ("In which year was Zoltan Vega born?" if i % 2 == 0
                 else f"What is the phone number of {persons[0][0]}?")
            emit("search", head + q + tail, "", "exact_str", dict(files), False)
            continue
        name, year, comp, role = persons[i % len(persons)]; kind = i % 3
        if kind == 0: q, exp = f"In which year was {name} born?", str(year)
        elif kind == 1: q, exp = f"In which city is the headquarters of {name}'s employer?", comp_hq[comp]
        else: q, exp = f"What is the role of {name}?", role
        emit("search", head + q + tail, exp, "exact_str", dict(files))

gen_coding(); gen_data(); gen_math(); gen_search()
json.dump(labels, open(OUT + "_labels.json", "w"), indent=1)
print(f"generated {sum(cnt.values())} tasks in {OUT}/ ({sum(1 for v in labels.values() if not v)} infeasible); "
      f"clean coding keys in {KEY}/")