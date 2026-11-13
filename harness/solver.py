"""Per-task pipelines with workspace/ layout support.
one-shot -> free local verification -> one repair -> optional reasoning escalation."""
import asyncio, os, re, shutil, sys, tempfile
from .core import CFG, TMP, atomic_write

SYS = "You are a precise problem solver. Follow the output format exactly."
F = "\x60\x60\x60"  # markdown code fence
AUDIT = os.environ.get("HARNESS_CODING_AUDIT", "1") != "0"

def extract_code(text):
    blocks = re.findall(re.escape(F) + r"(?:python)?\s*\n(.*?)" + re.escape(F), text, re.S)
    if blocks:
        return blocks[-1].strip()
    if re.search(r"^\s*(def |class |import |from )", text, re.M):
        return text.strip()
    return ""

def extract_answer(text):
    m = re.findall(r"ANSWER:\s*(.+)", text)
    if m:
        return m[-1].strip().strip(chr(96)).strip()
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""

def normalize_number(s):
    s = s.strip().strip(chr(96)).strip()
    cleaned = s.replace(",", "").replace(" ", "").replace("\u00a0", "")
    m = re.fullmatch(r"(-?\d+)(?:\.0+)?", cleaned)
    if m:
        return m.group(1)
    try:
        v = float(cleaned)
    except ValueError:
        return s
    return str(int(v)) if v.is_integer() else s

async def run_cmd(argv, cwd, timeout):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": TMP,
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "PYTHONPATH": cwd}
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except OSError as e:
        return -1, "", str(e)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
        return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", "timeout"

def _workdir(t):
    wd = tempfile.mkdtemp(prefix="task_", dir=TMP)
    for group in (t.code_files, t.test_files, t.data_files):
        for fn, body in group.items():
            p = os.path.join(wd, fn)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
    return wd

async def run_tests(t, wd):
    tests = sorted(t.test_files)
    if not tests:
        return 0, "", ""
    cwd = t.exec_dir(wd)
    outs, errs = [], []
    for tf in tests:
        rc, out, err = await run_cmd([sys.executable, t.rel(tf)], cwd, 45)
        outs.append(out); errs.append(err)
        if rc != 0:
            return rc, "\n".join(outs), "\n".join(errs)
    return 0, "\n".join(outs), "\n".join(errs)

def _cap_left(t):
    return t.spent < t.cap

async def _call(t, gw, messages, model, max_tokens, purpose, timeout=120):
    r = await gw.call(messages, model=model, max_tokens=max_tokens,
                      purpose=purpose, task_id=t.id, timeout=timeout)
    t.spent += r.cost
    return r

def _msg(user):
    return [{"role": "system", "content": SYS}, {"role": "user", "content": user}]

def _answer_paths(t):
    paths = [os.path.join(t.path, "answer.txt")]
    if t.ws != ".":
        paths.append(os.path.join(t.path, t.ws, "answer.txt"))
    return paths

def save_answer(t, answer, store):
    t.status = "solved"
    meta = {"reward": t.reward, "category": t.category, "cost": round(t.spent, 1)}
    try:
        if t.category == "coding":
            atomic_write(os.path.join(t.path, t.target_file), answer)
            for p in _answer_paths(t):
                atomic_write(p, "DONE")
            t.answer = "DONE"
            store.save(t.id, "DONE", meta)
        else:
            answer = normalize_number(answer)
            for p in _answer_paths(t):
                atomic_write(p, answer)
            t.answer = answer
            store.save(t.id, answer, meta)
    except OSError as e:
        print(f"[save] {t.id}: {e}")

async def solve_coding(t, gw, store, allow_deep):
    code = t.code_files.get(t.target_file, "")[:14000]
    fname = os.path.basename(t.target_file)
    tests = "\n".join(f"# {t.rel(fn)}\n{b}" for fn, b in t.test_files.items())[:6000]
    prompt = (f"{t.statement}\n\nFile {fname}:\n{F}python\n{code}\n{F}\n\n"
              f"Visible tests (unittest, do NOT edit them):\n{F}python\n{tests}\n{F}\n\n"
              f"Return ONLY the complete corrected {fname} in one {F}python block. "
              "Fix the root cause: hidden tests are broader than the visible ones.")
    wd = _workdir(t)
    try:
        for attempt in range(3):
            if not _cap_left(t):
                break
            model = CFG.deep if attempt == 2 else CFG.coder
            if attempt == 2 and not allow_deep(t):
                break
            r = await _call(t, gw, _msg(prompt), model,
                            3200 if attempt == 2 else 2600, f"coding{attempt}",
                            timeout=240 if attempt == 2 else 120)
            if not r.ok:
                break
            cand = extract_code(r.text)
            if not cand:
                continue
            with open(os.path.join(wd, t.target_file), "w", encoding="utf-8") as f:
                f.write(cand)
            rc, out, err = await run_tests(t, wd)
            if rc == 0:
                # visible tests are weak: audit for bugs they do not expose
                if attempt == 0 and AUDIT and t.spent < 0.4 * t.cap:
                    audit = (f"{t.statement}\n\nCurrent {fname}:\n{F}python\n{cand[:12000]}\n{F}\n\n"
                             f"Visible tests (all pass now):\n{F}python\n{tests[:4000]}\n{F}\n\n"
                             "The visible tests are weak. Hidden tests also cover edge cases: "
                             "empty inputs, single element, duplicates, negative numbers, "
                             "boundary values, ordering and ties. Find and fix any remaining "
                             "bug the visible tests do not expose. Return ONLY the complete "
                             f"corrected {fname} in one {F}python block. If it is already fully "
                             "correct, return it unchanged.")
                    r2 = await _call(t, gw, _msg(audit), CFG.coder, 2600, "coding_audit")
                    cand2 = extract_code(r2.text) if r2.ok else ""
                    if cand2:
                        with open(os.path.join(wd, t.target_file), "w", encoding="utf-8") as f:
                            f.write(cand2)
                        rc2, _, _ = await run_tests(t, wd)
                        if rc2 == 0:
                            cand = cand2
                        else:
                            with open(os.path.join(wd, t.target_file), "w", encoding="utf-8") as f:
                                f.write(cand)
                save_answer(t, cand, store)
                return
            tail = (err or out)[-1400:]
            prompt = (f"{t.statement}\n\nYour previous fix for {fname}:\n"
                      f"{F}python\n{cand[:12000]}\n{F}\n\nTests still fail:\n{tail}\n\n"
                      f"Return ONLY the complete corrected {fname} in one {F}python block.")
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    t.status = "failed"
    
async def solve_math(t, gw, store, allow_deep):
    prompt = (f"{t.statement}\n\nWrite a complete Python 3 script (stdlib only) that computes "
              "the answer exactly and prints ONLY the final number to stdout. "
              "Use integer arithmetic and apply the operations in the given order. "
              "If the computation is undefined or impossible (a division by zero, or a "
              "quantity the givens do not determine), print exactly INFEASIBLE. "
              f"Return ONLY the script in one {F}python block.")
    wd = tempfile.mkdtemp(prefix="math_", dir=TMP)
    try:
        for attempt in range(2):
            if not _cap_left(t):
                break
            model = CFG.fast if attempt == 0 else (CFG.deep if allow_deep(t) else CFG.coder)
            r = await _call(t, gw, _msg(prompt), model, 900 if attempt == 0 else 1600,
                            f"math_gen{attempt}", timeout=180)
            if not r.ok:
                break
            script = extract_code(r.text)
            if not script:
                break
            with open(os.path.join(wd, "solution.py"), "w", encoding="utf-8") as f:
                f.write(script)
            rc, out, err = await run_cmd([sys.executable, "solution.py"], wd, 30)
            ans = out.strip().splitlines()[-1].strip() if out.strip() else ""
            if rc == 0 and ans.upper() == "INFEASIBLE":
                t.status = "infeasible"
                return
            if rc == 0 and ans:
                save_answer(t, ans, store)
                return
            prompt = (f"{t.statement}\n\nYour script failed:\n{F}python\n{script[:4000]}\n{F}\n"
                      f"Error:\n{(err or out)[-800:]}\nReturn ONLY the corrected script "
                      f"in one {F}python block.")
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    t.status = "failed"

async def solve_search(t, gw, store, allow_deep):
    data = t.data_files
    total = sum(len(v) for v in data.values())
    if t.category != "data_analysis" and data and total <= 2500:
        blob = "\n".join(f"--- {t.rel(fn)} ---\n{b}" for fn, b in data.items())
        prompt = (f"{t.statement}\n\nData:\n{blob}\n\n"
                  "Answer with the final line exactly: ANSWER: <value>. "
                  "If the requested information is not present in the data, answer ANSWER: INFEASIBLE.")
        r = await _call(t, gw, _msg(prompt), CFG.fast, 500, "search_inline")
        ans = extract_answer(r.text) if r.ok else ""
        if ans.upper() == "INFEASIBLE":
            t.status = "infeasible"
            return
        if ans:
            save_answer(t, ans, store)
            return
        t.status = "failed"
        return
    wd = _workdir(t)
    try:
        items = list(data.items())
        dirs = {}
        for fn, b in items:
            dd = os.path.dirname(t.rel(fn)) or "."
            dirs[dd] = dirs.get(dd, 0) + 1
        summary = "; ".join(f"{k}: {v} files" for k, v in sorted(dirs.items()))
        # one sample per record kind, so EVERY schema is visible (company AND person)
        samples, seen = [], set()
        for fn, b in items:
            kind = re.sub(r"\d+", "#", os.path.basename(fn))
            if kind in seen:
                continue
            seen.add(kind)
            samples.append(f"--- {t.rel(fn)} (sample, full) ---\n{b[:800]}")
            if len(samples) >= 4:
                break
        schema = "\n".join(samples)
        prompt = (f"{t.statement}\n\nData layout: {summary}. Total {len(items)} files.\n"
                  + schema +
                  "\n\nWrite a complete Python 3 script (stdlib only) that scans ALL files "
                  "(glob.glob with recursive=True), parses the fields shown in the samples, "
                  "and follows reference fields across files (for example Employer or Manager "
                  "point to another record by name). Print ONLY the final answer to stdout, "
                  "with no label or prefix. Compute exactly with code. "
                  "If the requested information truly does not exist, print exactly INFEASIBLE. "
                  f"Return ONLY the script in one {F}python block.")
        for attempt in range(3):
            if not _cap_left(t):
                break
            r = await _call(t, gw, _msg(prompt), CFG.fast, 1200, f"search_gen{attempt}")
            if not r.ok:
                break
            script = extract_code(r.text)
            if not script:
                break
            with open(os.path.join(wd, t.ws if t.ws != "." else "", "solution.py"), "w",
                      encoding="utf-8") as f:
                f.write(script)
            rc, out, err = await run_cmd([sys.executable, "solution.py"], t.exec_dir(wd), 60)
            ans = out.strip()
            if rc == 0 and ans == "INFEASIBLE":
                t.status = "infeasible"
                return
            if rc == 0 and ans:
                ans = ans.splitlines()[-1].strip()
                ans = re.sub(r"^(answer|ans|result)\s*[:=]\s*", "", ans, flags=re.I).strip()
                save_answer(t, ans, store)
                return
            prompt = (f"{t.statement}\n\nYour script failed:\n{F}python\n{script[:6000]}\n{F}\n"
                      f"Error:\n{(err or out)[-1000:]}\nReturn ONLY the corrected script "
                      f"in one {F}python block.")
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    t.status = "failed"

async def solve_other(t, gw, store, allow_deep):
    prompt = f"{t.statement}\n\nAnswer with the final line exactly: ANSWER: <value>."
    r = await _call(t, gw, _msg(prompt), CFG.fast, 500, "other")
    ans = extract_answer(r.text) if r.ok else ""
    if not ans and allow_deep(t) and _cap_left(t):
        r = await _call(t, gw, _msg(prompt), CFG.deep, 1500, "other_deep", timeout=240)
        ans = extract_answer(r.text) if r.ok else ""
    if ans:
        save_answer(t, ans, store)
    else:
        t.status = "failed"

SOLVERS = {"coding": solve_coding, "math": solve_math,
           "data_analysis": solve_search, "search": solve_search, "other": solve_other}

async def solve(t, gw, store, allow_deep):
    try:
        await SOLVERS.get(t.category, solve_other)(t, gw, store, allow_deep)
    except Exception as e:
        print(f"[solver] {t.id}: {type(e).__name__}: {e}")
        t.status = "failed"