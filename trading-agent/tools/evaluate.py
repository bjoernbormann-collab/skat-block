"""python3 tools/evaluate.py [SYMBOL] -- walk-forward on real Binance data with the momentum baseline."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from reflex.data import load
from reflex.replay import momentum_signal
from reflex.walkforward import walk_forward

sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
rows = load(sym, "1h")
px = [c for _, c in rows]
print(f"{sym}: {len(px)} hourly bars")
res = walk_forward(px, momentum_signal(k=6, scale=0.02), folds=8, horizon=6)
tot, bh = 1.0, 1.0
for i, (r, hold) in enumerate(res):
    ret = r.final_equity / 100_000 - 1
    tot *= 1 + ret; bh *= 1 + hold
    print(f"fold {i+1}: trades={r.trades:4d} hit={r.hit_rate:.2f} ret={ret:+.2%} maxDD={r.max_drawdown:.2%} "
          f"brier={r.brier:.3f} killed={r.killed} | buy&hold={hold:+.2%}")
print(f"compounded OOS: strategy={tot-1:+.2%}  buy&hold={bh-1:+.2%}")
