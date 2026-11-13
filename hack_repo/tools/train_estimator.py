#!/usr/bin/env python3
"""Usage: python tools/train_estimator.py trace1.jsonl [...] [--labels labels.json]"""
import json, os, sys
import numpy as np

FEATURES = ["log_stmt", "log_code", "log_tests", "log_data", "n_files", "n_tests",
            "n_numbers", "n_lines", "kw_prove", "kw_optimize", "kw_missing",
            "cat_coding", "cat_math", "cat_search", "cat_other"]

def load(paths):
    rows = []
    for p in paths:
        for line in open(p, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("type") == "task" and r.get("features"):
                rows.append(r)
    return rows

def fit_linear(X, y, l2=1.0):
    return np.linalg.solve(X.T @ X + l2 * np.eye(X.shape[1]), X.T @ y)

def fit_logistic(X, y, l2=1e-2, iters=800, lr=0.1):
    w = np.zeros(X.shape[1]); b = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ w + b, -30, 30)))
        g = p - y
        w -= lr * (X.T @ g / len(y) + l2 * w)
        b -= lr * g.mean()
    return w, b

def matrix(rows):
    X = np.array([[r["features"].get(k, 0.0) for k in FEATURES] for r in rows])
    mu, sd = X.mean(0), X.std(0) + 1e-6
    return (X - mu) / sd, mu, sd

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    labels = {}
    if "--labels" in sys.argv:
        labels = json.load(open(sys.argv[sys.argv.index("--labels") + 1], encoding="utf-8"))
    rows = load(args)
    attempted = [r for r in rows if r.get("cost", 0) > 0]
    if len(attempted) < 10:
        print(f"need >=10 attempted records, got {len(attempted)}"); return
    Xs, mu, sd = matrix(attempted)
    cost = np.array([r["cost"] for r in attempted])
    wc = fit_linear(np.c_[Xs, np.ones(len(Xs))], np.log(cost))
    succ = np.array([1.0 if r["outcome"] == "solved" else 0.0 for r in attempted])
    ws, bs = fit_logistic(Xs, succ)
    ok_rows = [r for r in rows if r["task"] in labels] or attempted
    Xo, muo, sdo = matrix(ok_rows)
    ok = np.array([float(labels.get(r["task"], r["outcome"] != "infeasible")) for r in ok_rows])
    wo, bo = fit_logistic(Xo, ok)
    def fold(w, b, m, s):
        return (w / s).tolist(), float(b - np.sum(w * m / s))
    cw, cb = fold(wc[:-1], wc[-1], mu, sd)
    sw, sb = fold(ws, bs, mu, sd)
    ow, ob = fold(wo, bo, muo, sdo)
    os.makedirs("models", exist_ok=True)
    json.dump({"features": FEATURES, "cost_w": cw, "cost_b": cb,
               "succ_w": sw, "succ_b": sb, "ok_w": ow, "ok_b": ob},
              open("models/estimator.json", "w"), indent=1)
    print(f"trained: cost/success on {len(attempted)} attempts, feasibility on {len(ok_rows)} -> models/estimator.json")

if __name__ == "__main__":
    main()