"""Out-of-sample evaluation of each hypothesis. Verdict is PROMOTE only if all hold:
  >=30 trades, mean net return>0, t-stat>=3 (multiple-testing bar), positive in >=75% of time folds."""
import math, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from reflex.data import load
from brain.hypotheses import REGISTRY, HORIZON

COST = 0.0018   # 6 bps fee + 3 bps slippage, each side


def trades(px, f):
    out = []                                   # (index, net_return)
    for t in range(1300, len(px) - HORIZON, HORIZON):
        pos = f(px[:t + 1])
        if pos:
            out.append((t, pos * (px[t + HORIZON] / px[t] - 1) - COST))
    return out


def stats(rs):
    n = len(rs)
    if n < 2: return n, 0.0, 0.0
    m = sum(rs) / n; sd = (sum((r - m) ** 2 for r in rs) / (n - 1)) ** 0.5
    return n, m, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0)


def evaluate(sym, folds=6):
    px = [c for _, c in load(sym, "1h")]
    rows = []
    for name, f in REGISTRY.items():
        tr = trades(px, f)
        n, m, t = stats([r for _, r in tr])
        L = len(px) // folds
        fold_means = [stats([r for i, r in tr if k * L <= i < (k + 1) * L]) for k in range(folds)]
        active = [fm for fm in fold_means if fm[0] >= 5]
        pos = sum(1 for fm in active if fm[1] > 0)
        frac = pos / len(active) if active else 0
        ok = n >= 30 and m > 0 and t >= 3 and frac >= 0.75
        rows.append((name, n, m, t, pos, len(active), "PROMOTE" if ok else "reject"))
    return len(px), rows


if __name__ == "__main__":
    for sym in ("BTCUSDT", "ETHUSDT"):
        n, rows = evaluate(sym)
        print(f"\n{sym} ({n} hourly bars, horizon {HORIZON}h, cost {COST*1e4:.0f}bp/trade)")
        print(f"{'hypothesis':26s} {'trades':>6s} {'mean net/trade':>14s} {'t-stat':>7s} {'folds+':>7s}  verdict")
        for name, n, m, t, pos, act, v in rows:
            print(f"{name:26s} {n:6d} {m:+14.3%} {t:7.2f} {pos:>3d}/{act:<3d}  {v}")
