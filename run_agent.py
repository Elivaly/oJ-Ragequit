#!/usr/bin/env python3
"""Budget-aware task-selection harness built on openJiuwen."""
import argparse, asyncio, json, os, signal, sys, time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
from harness.core import CFG, TMP, Ledger, SolutionsStore, Trace
from harness.tasks import load_tasks, Estimator
from harness.solver import solve

def setup_env():
    os.environ.setdefault("HOME", TMP)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", "/app/.tiktoken")

async def triage(tasks, gw, ledger):
    """Advisory only: lowers priority, NEVER removes a task from the queue."""
    cap = ledger.budget * CFG.triage_fraction
    spent0 = ledger.spent
    CH = 18
    for i in range(0, len(tasks), CH):
        if ledger.spent - spent0 > cap or ledger.exhausted:
            break
        chunk = tasks[i:i + CH]
        lines = []
        for j, t in enumerate(chunk):
            s = " ".join(t.statement.split())[:420]
            files = ",".join(list(t.code_files) + list(t.test_files) + list(t.data_files))[:120]
            lines.append(f"[{j}] cat={t.category} files=({files}) :: {s}")
        prompt = ("TRIAGE. For each task judge whether it is solvable given the listed files. "
                  "ok=0 ONLY if you are certain it is impossible (contradiction, or the required "
                  "data is clearly absent). If you cannot see the data, answer ok=1. "
                  "tok=estimated output tokens to solve (200..8000). Reply ONLY a JSON array: "
                  '[{"i":0,"ok":1,"tok":600},...]\n\n' + "\n".join(lines))
        r = await gw.call([{"role": "user", "content": prompt}], model=CFG.fast,
                          max_tokens=1100, purpose="triage", timeout=120)
        if not r.ok:
            break
        try:
            txt = r.text.strip()
            arr = json.loads(txt[txt.find("["):txt.rfind("]") + 1])
        except Exception:
            continue
        for item in arr:
            try:
                t = chunk[int(item["i"])]
                ok = int(item.get("ok", 1))
                tok = float(item.get("tok", t.est_cost))
                t.p_ok = max(0.12, t.p_ok * 0.45) if ok == 0 else max(t.p_ok, 0.85)
                t.est_cost = max(150.0, min(12000.0, 0.7 * t.est_cost + 0.3 * tok))
                t.base_est = t.est_cost
            except Exception:
                continue

def pick(queue, ledger, t0, time_limit):
    for t in queue:
        if t.status != "pending":
            continue
        if ledger.remaining() < t.est_cost * 1.05:
            continue
        if time.time() - t0 + CFG.time_est.get(t.category, 60) > time_limit - CFG.time_margin:
            continue
        t.status = "running"
        return t
    return None

async def run(tasks_dir, budget, time_limit, workers, gw=None, do_triage=True):
    setup_env()
    tasks_dir = os.path.abspath(tasks_dir)
    ledger = Ledger(budget, CFG.stop_fraction)
    trace = Trace(CFG.trace_file or os.path.join(tasks_dir, "trace.jsonl"))
    store = SolutionsStore(CFG.out, tasks_dir)
    tasks = load_tasks(tasks_dir)
    if not tasks:
        print("no tasks found")
        return
    est = Estimator(os.path.join(APP_DIR, "models", "estimator.json"))
    for t in tasks:
        est.predict(t)
    print(f"[plan] {len(tasks)} tasks, budget={budget}, "
          f"estimator={'trained' if est.w else 'heuristic'}")    
    qualifier = len(tasks) <= 5 or budget <= 15000
    if gw is None:
        if not os.environ.get("LLM_BASE_URL") or not os.environ.get("LLM_API_KEY"):
            print("[fatal] LLM_BASE_URL / LLM_API_KEY are empty -- aborting before any work")
            return
        from harness.llm import Gateway
        gw = Gateway(ledger, trace)
        probe = await gw.call([{"role": "user", "content": "Reply with OK."}],
                              model=CFG.fast, max_tokens=8, purpose="preflight", timeout=60)
        if not probe.ok:
            print(f"[fatal] preflight failed ({probe.error}) -- check key / base_url / network")
            return
        print("[plan] preflight OK")
    t0 = time.time()
    if do_triage and not qualifier and budget >= 20000:
        await triage(tasks, gw, ledger)
    rewards = sorted(t.reward for t in tasks)
    p60 = rewards[int(len(rewards) * 0.6)]
    frac = 0.45 if len(tasks) <= 5 else 0.12
    for t in tasks:
        base = max(1200.0, min(7000.0, 3 * t.est_cost))
        t.cap = max(400.0, min(base, budget * frac))
    def allow_deep(t):
        if qualifier:
            return ledger.remaining() > 800
        return t.reward >= p60 and ledger.remaining() > 6000
    queue = list(tasks)          # nothing is permanently skipped
    stop = asyncio.Event()
    cat_ratio = {}
    async def worker(wid):
        while not stop.is_set() and not ledger.exhausted:
            queue.sort(key=lambda t: -t.priority())
            t = pick(queue, ledger, t0, time_limit)
            if t is None:
                break
            await solve(t, gw, store, allow_deep)
            if t.status == "failed" and t.spent == 0 and t.retries < 2:
                t.retries += 1          # API error, not a real attempt: retry later
                t.status = "pending"
                continue
            if t.spent > 0 and t.base_est > 0:
                r = t.spent / t.base_est
                m = 0.7 * cat_ratio.get(t.category, 1.0) + 0.3 * r
                cat_ratio[t.category] = m
                for q in queue:
                    if q.status == "pending" and q.category == t.category:
                        q.est_cost = max(150.0, min(12000.0, q.base_est * m))
            trace.write({"type": "task", "task": t.id, "category": t.category,
                         "reward": t.reward, "features": t.features, "outcome": t.status,
                         "cost": round(t.spent, 1), "est": round(t.base_est, 1)})
            print(f"[{t.status}] {t.id} reward={t.reward} cost={t.spent:.0f} "
                  f"left={ledger.budget - ledger.spent:.0f}")
    async def watchdog():
        left = time_limit - CFG.time_margin - (time.time() - t0)
        if left > 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=left)
            except asyncio.TimeoutError:
                stop.set()
    wds = [asyncio.create_task(worker(i)) for i in range(workers)]
    wd = asyncio.create_task(watchdog())
    await asyncio.gather(*wds)
    stop.set()
    wd.cancel()
    solved = [t for t in tasks if t.status == "solved"]
    from collections import Counter
    print(f"DONE: solved {len(solved)}/{len(tasks)}, "
          f"reward={sum(t.reward for t in solved):.1f}, "
          f"spent={ledger.spent:.0f}/{budget}, calls={ledger.calls}")
    print("[plan] outcomes:", dict(Counter(t.status for t in tasks)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-dir", default=os.environ.get("TASKS", "/data/tasks"))
    ap.add_argument("--budget", type=int, default=int(os.environ.get("BUDGET", "100000")))
    ap.add_argument("--time-limit", type=int, default=int(os.environ.get("TIME_LIMIT", "3600")))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("HARNESS_WORKERS", "5")))
    ap.add_argument("--no-triage", action="store_true")
    a = ap.parse_args()
    setup_env()
    tasks_dir = os.path.abspath(a.tasks_dir)
    CFG.out = os.path.abspath(os.environ["OUT"]) if os.environ.get("OUT") else ""
    CFG.trace_file = os.path.abspath(os.environ.get(
        "HARNESS_TRACE_FILE", os.path.join(tasks_dir, "trace.jsonl")))
    for attr, env in (("coder", "HARNESS_CODER"), ("fast", "HARNESS_FAST"), ("deep", "HARNESS_DEEP")):
        if os.environ.get(env):
            setattr(CFG, attr, os.environ[env])
    os.chdir(TMP)   # any library writing ./logs lands in writable tmp
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.add_signal_handler(signal.SIGTERM, lambda: sys.exit(0))
        except (NotImplementedError, RuntimeError):
            pass
        loop.run_until_complete(run(tasks_dir, a.budget, a.time_limit, a.workers,
                                    do_triage=not a.no_triage))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()