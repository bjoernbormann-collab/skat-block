"""Go/no-go report from data/paper_log.jsonl. Criteria are fixed in advance (below), not tuned after the fact.
  python3 tools/evaluate_paper.py [path/to/paper_log.jsonl]
Verdicts: NOT ENOUGH DATA | STOP (a hard criterion failed) | CANDIDATE (all criteria met; human decision still required)."""
import json, math, pathlib, sys
from collections import defaultdict

CRITERIA = dict(min_days=28, min_trades=100, min_mean_net_ret=0.0, min_t=2.0, max_drawdown=0.10,
                max_jev_error_rate=0.05, max_brier=0.25)   # 0.25 = a coin flip


def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def evaluate(rows):
    ticks = [r for r in rows if "event" not in r]
    sh = [r for r in rows if r.get("event") == "shadow"]
    tr = [r for r in rows if r.get("event") == "trade_closed"]
    out = {}
    out["days"] = (ticks[-1]["ts"] - ticks[0]["ts"]) / 86400 if len(ticks) > 1 else 0.0
    out["ticks"] = len(ticks)
    out["jev_error_rate"] = sum(1 for t in ticks if str(t.get("reason", "")).startswith("jev_error")) / len(ticks) if ticks else 0
    out["fires"] = sum(1 for t in ticks if t.get("action") == "fire")
    out["escalations"] = sum(1 for t in ticks if t.get("action") == "escalate")
    out["trades"] = len(tr)
    rs = [t["net_ret"] for t in tr]
    n = len(rs)
    m = sum(rs) / n if n else 0.0
    sd = (sum((x - m) ** 2 for x in rs) / (n - 1)) ** 0.5 if n > 1 else 0.0
    out["mean_net_ret"], out["t"] = m, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0)
    peak, mdd = 0.0, 0.0
    for t in ticks:
        peak = max(peak, t["equity"]); mdd = max(mdd, (peak - t["equity"]) / peak if peak else 0)
    out["max_drawdown"] = mdd
    out["return"] = ticks[-1]["equity"] / ticks[0]["equity"] - 1 if ticks else 0.0
    out["killed"] = bool(ticks and ticks[-1].get("killed"))
    out["signals"] = len(sh)
    out["brier"] = sum((s["conf"] - s["correct"]) ** 2 for s in sh) / len(sh) if sh else float("nan")
    out["hit"] = sum(s["correct"] for s in sh) / len(sh) if sh else float("nan")
    bins = defaultdict(lambda: [0, 0])
    for s in sh:
        b = bins[min(int(s["conf"] * 10), 9)]; b[0] += 1; b[1] += s["correct"]
    out["bins"] = {k / 10: (v[0], v[1] / v[0]) for k, v in sorted(bins.items())}
    C = CRITERIA
    if out["days"] < C["min_days"] or out["trades"] < C["min_trades"]:
        out["verdict"], out["why"] = "NOT ENOUGH DATA", f"need >= {C['min_days']} days and >= {C['min_trades']} closed trades"
        return out
    fails = []
    if out["mean_net_ret"] <= C["min_mean_net_ret"]: fails.append("mean net return per trade <= 0")
    if out["t"] < C["min_t"]: fails.append(f"t-stat {out['t']:.2f} < {C['min_t']}")
    if out["max_drawdown"] > C["max_drawdown"]: fails.append("drawdown above limit")
    if out["jev_error_rate"] > C["max_jev_error_rate"]: fails.append("Jev error rate too high")
    if not out["brier"] < C["max_brier"]: fails.append("Brier score not better than a coin flip")
    if out["killed"]: fails.append("kill switch tripped")
    out["verdict"] = "STOP" if fails else "CANDIDATE"
    out["why"] = "; ".join(fails) or "all pre-registered criteria met; still needs your human decision and a tiny-capital start"
    return out


def render(o):
    L = [f"VERDICT: {o['verdict']}  ({o['why']})", "",
         f"days {o['days']:.1f} | ticks {o['ticks']} | Jev errors {o['jev_error_rate']:.1%} | escalations {o['escalations']}",
         f"fires {o['fires']} | closed trades {o['trades']} | mean net/trade {o['mean_net_ret']:+.3%} | t {o['t']:.2f}",
         f"return {o['return']:+.2%} | max drawdown {o['max_drawdown']:.2%} | kill switch {'TRIPPED' if o['killed'] else 'ok'}",
         f"scored signals {o['signals']} | hit rate {o['hit']:.3f} | Brier {o['brier']:.3f} (0.250 = coin flip)", "",
         "calibration (stated confidence -> actual hit rate):"]
    for b, (n, h) in o["bins"].items():
        L.append(f"  {b:.1f}-{b + .1:.1f}: n={n:5d} hit={h:.3f}")
    return "\n".join(L)


if __name__ == "__main__":
    p = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[1] / "data" / "paper_log.jsonl"
    if not p.exists(): sys.exit(f"no log at {p}; run tools/run_paper.py first")
    print(render(evaluate(load(p))))
