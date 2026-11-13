"""Budget ledger, atomic storage, tracing, rate limiting."""
import asyncio, json, os, tempfile, time
from collections import deque

TMP = tempfile.gettempdir()

class CFG:
    budget = 100_000
    time_limit = 3600
    time_margin = 150
    workers = 5
    rpm = 50
    coder = "qwen3.8-27b-noreason"
    fast = "qwen3.6-35b-a3b-noreason"
    deep = "qwen3.8-27b"
    trace_file = os.path.join(TMP, "trace.jsonl")
    out = ""
    stop_fraction = 0.97
    triage_fraction = 0.04
    time_est = {"coding": 150, "math": 60, "data_analysis": 90, "search": 90, "other": 60}

class Ledger:
    def __init__(self, budget, stop_fraction=0.97):
        self.budget = float(budget)
        self.stop_at = self.budget * stop_fraction
        self.spent = 0.0
        self.reserved = 0.0
        self.exhausted = False
        self.calls = 0
    def remaining(self):
        return self.budget - self.spent - self.reserved
    def try_reserve(self, amount):
        if self.exhausted or self.spent + self.reserved + amount > self.stop_at:
            return False
        self.reserved += amount
        return True
    def commit(self, reservation, actual):
        self.reserved = max(0.0, self.reserved - reservation)
        self.spent += actual
        self.calls += 1
        if self.spent >= self.stop_at:
            self.exhausted = True
    def cancel(self, reservation):
        self.reserved = max(0.0, self.reserved - reservation)
    def mark_exhausted(self):
        self.exhausted = True

def atomic_write(path, text):
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

class SolutionsStore:
    def __init__(self, out_env, tasks_dir):
        self.data = {}
        self.paths = []
        if out_env:
            p = out_env
            if os.path.isdir(p) or p.endswith(os.sep):
                p = os.path.join(p, "solutions.json")
            self.paths.append(p)
        self.paths.append(os.path.join(tasks_dir, "solutions.json"))
        self.paths.append(os.path.join(TMP, "solutions.json"))
    def save(self, task_id, answer, meta):
        self.data[task_id] = {"answer": answer, **meta}
        blob = json.dumps(self.data, ensure_ascii=False, indent=1)
        for p in list(self.paths):
            try:
                atomic_write(p, blob)
            except OSError:
                self.paths.remove(p)

class Trace:
    def __init__(self, path):
        self.path = path
    def write(self, rec):
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

class RateLimiter:
    def __init__(self, rpm):
        self.rpm = rpm
        self.hits = deque()
    async def acquire(self):
        while True:
            now = time.monotonic()
            while self.hits and now - self.hits[0] > 60:
                self.hits.popleft()
            if len(self.hits) < self.rpm:
                self.hits.append(now)
                return
            await asyncio.sleep(60 - (now - self.hits[0]) + 0.05)

def est_tokens(text):
    return int(len(text) / 3.5) + 8