"""Task loading (workspace/ layout), features, cost/feasibility estimation."""
import json, math, os, re
from dataclasses import dataclass, field

TEXT_EXT = {".py", ".txt", ".csv", ".json", ".md", ".tsv", ".dat", ".yaml", ".yml", ".xml"}
DATA_EXT = {".csv", ".tsv", ".json", ".txt", ".dat", ".md", ".yaml", ".yml", ".xml"}
TYPE_MAP = {"coding": "coding", "code": "coding", "math": "math",
            "data_analysis": "data_analysis", "search": "search", "data": "data_analysis"}

@dataclass
class Task:
    id: str
    path: str
    reward: float
    category: str
    statement: str
    code_files: dict = field(default_factory=dict)
    test_files: dict = field(default_factory=dict)
    data_files: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    ws: str = "."
    est_cost: float = 800.0
    base_est: float = 800.0
    p_ok: float = 0.8
    p_success: float = 0.65
    spent: float = 0.0
    cap: float = 6000.0
    status: str = "pending"
    answer: str = ""
    target_file: str = ""
    retries: int = 0
    def priority(self):
        return self.reward * self.p_ok * self.p_success / max(self.est_cost, 150.0)
    def rel(self, path):
        if self.ws != "." and path.startswith(self.ws + "/"):
            return path[len(self.ws) + 1:]
        return path
    def exec_dir(self, base):
        return os.path.join(base, self.ws) if self.ws != "." else base

def _read(path, limit=4_000_000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""

def detect_category(meta, stmt, code, tests, data):
    v = str(meta.get("task_type", meta.get("category", ""))).lower()
    if v in TYPE_MAP:
        return TYPE_MAP[v]
    if tests:
        return "coding"
    if data:
        return "data_analysis"
    return "math" if re.search(r"\d", stmt) else "search"

def load_tasks(root):
    tasks = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        meta = {}
        for mj in ("task.json", "tasks.json"):
            p = os.path.join(d, mj)
            if os.path.isfile(p):
                try:
                    meta = json.loads(_read(p))
                except json.JSONDecodeError:
                    meta = {}
                break
        stmt = ""
        for k in ("instruction", "task", "prompt", "question", "description", "statement", "text"):
            if isinstance(meta.get(k), str) and meta[k].strip():
                stmt = meta[k]
                break
        if not stmt:
            for fn in ("task.md", "README.md", "prompt.txt", "task.txt"):
                if os.path.isfile(os.path.join(d, fn)):
                    stmt = _read(os.path.join(d, fn))
                    break
        ws = "workspace" if os.path.isdir(os.path.join(d, "workspace")) else "."
        code, tests, data = {}, {}, {}
        for dirpath, dirnames, filenames in os.walk(d):
            dirnames[:] = [x for x in dirnames if not x.startswith(".") and x != "__pycache__"]
            for fn in sorted(filenames):
                if fn.startswith(".") or fn in ("task.json", "tasks.json", "answer.txt"):
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext not in TEXT_EXT:
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, d).replace(os.sep, "/")
                if rel in ("task.md", "README.md", "prompt.txt", "task.txt"):
                    continue
                body = _read(full)
                if ext == ".py":
                    (tests if fn.startswith("test_") or fn.endswith("_test.py") else code)[rel] = body
                elif ext in DATA_EXT:
                    data[rel] = body
        if not stmt and not code and not data:
            continue
        cat = detect_category(meta, stmt, code, tests, data)
        t = Task(id=name, path=d, reward=float(meta.get("reward", 1.0) or 1.0),
                 category=cat, statement=stmt, code_files=code,
                 test_files=tests, data_files=data, ws=ws)
        if cat == "coding" and code:
            imports = " ".join(tests.values())
            named = [fn for fn in code if os.path.splitext(os.path.basename(fn))[0] in imports]
            t.target_file = named[0] if named else max(code, key=lambda f: len(code[f]))
        compute_features(t)
        local_feasibility(t)
        tasks.append(t)
    return tasks

def compute_features(t):
    stmt = t.statement
    code = "".join(t.code_files.values())
    tests = "".join(t.test_files.values())
    data = "".join(t.data_files.values())
    t.features = {
        "log_stmt": math.log1p(len(stmt)), "log_code": math.log1p(len(code)),
        "log_tests": math.log1p(len(tests)), "log_data": math.log1p(len(data)),
        "n_files": len(t.code_files) + len(t.test_files) + len(t.data_files),
        "n_tests": len(t.test_files),
        "n_numbers": len(re.findall(r"\d+", stmt)),
        "n_lines": stmt.count("\n"),
        "kw_prove": int(bool(re.search(r"\bprove|theorem\b", stmt, re.I))),
        "kw_optimize": int(bool(re.search(r"\boptimi[sz]|maximum|minimum\b", stmt, re.I))),
        "kw_missing": int(bool(re.search(r"\bmissing|absent|not exist\b", stmt, re.I))),
        "cat_coding": int(t.category == "coding"), "cat_math": int(t.category == "math"),
        "cat_search": int(t.category == "search"),
        "cat_other": int(t.category in ("data_analysis", "other")),
    }

def local_feasibility(t):
    refs = set(re.findall(r"[\w./-]+\.(?:csv|tsv|json|txt|dat|py|xlsx|md)", t.statement))
    have = set(t.code_files) | set(t.test_files) | set(t.data_files)
    have_base = {os.path.basename(x) for x in have}
    if {r for r in refs if os.path.basename(r) not in have_base}:
        t.p_ok *= 0.5
    if t.category == "coding" and (not t.test_files or not t.code_files):
        t.p_ok *= 0.3
    if t.category == "math":
        if (re.search(r"split equally into 0\b", t.statement, re.I)
                or re.search(r"\bdivid\w*\s+by\s+(?:zero|0)\b", t.statement, re.I)
                or re.search(r"\binto 0 (?:equal )?(?:parts|warehouses|groups)\b", t.statement, re.I)):
            t.p_ok *= 0.15
    if t.category in ("search", "data_analysis"):
        blob = " ".join(t.data_files.values())
        if not blob.strip():
            t.p_ok *= 0.4
        for ent in re.findall(r"'([^']+)'", t.statement):
            if ent.lower() not in blob.lower():
                t.p_ok *= 0.25
        for nm in re.findall(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b", t.statement):
            if nm not in blob:
                t.p_ok *= 0.5

DEFAULTS = {"coding": (1800, 0.60), "math": (650, 0.75),
            "data_analysis": (900, 0.70), "search": (900, 0.70), "other": (800, 0.65)}

class Estimator:
    def __init__(self, weights_path=""):
        self.w = None
        if weights_path and os.path.isfile(weights_path):
            try:
                self.w = json.loads(_read(weights_path))
            except json.JSONDecodeError:
                self.w = None
    def predict(self, t):
        base_cost, base_succ = DEFAULTS.get(t.category, DEFAULTS["other"])
        t.est_cost, t.p_success = float(base_cost), base_succ
        if self.w:
            x = [t.features.get(k, 0.0) for k in self.w["features"]]
            def dot(w): return sum(a * b for a, b in zip(x, w))
            sig = lambda z: 1 / (1 + math.exp(-max(-30, min(30, z))))
            cost = math.exp(dot(self.w["cost_w"]) + self.w["cost_b"])
            t.est_cost = max(150.0, min(12000.0, 0.5 * base_cost + 0.5 * cost))
            t.p_success = max(0.05, min(0.98, sig(dot(self.w["succ_w"]) + self.w["succ_b"])))
            if "ok_w" in self.w:
                t.p_ok = max(0.02, min(0.98, t.p_ok * sig(dot(self.w["ok_w"]) + self.w["ok_b"]) / 0.8))
        t.base_est = t.est_cost