"""Offline replay/backtest harness. Feeds bars to a signal function that sees ONLY past data,
runs the real gate/risk/sizing, resolves each trade after a fixed horizon, and reports metrics."""
import random
from dataclasses import dataclass
from .schema import JevDecision
from .risk import RiskLimits, KillSwitch
from .calibration import Calibrator, brier
from .gate import decide


def random_walk(n, seed, vol=0.002, drift=0.0, start=100.0):
    rng = random.Random(seed)
    px = [start]
    for _ in range(n - 1):
        px.append(px[-1] * (1 + drift + rng.gauss(0, vol)))
    return px


@dataclass
class Result:
    final_equity: float
    max_drawdown: float
    trades: int
    hit_rate: float
    brier: float
    killed: bool


def run(prices, signal, *, equity=100_000.0, horizon=5, fee_bps=6.0, slip_bps=3.0,
        limits=None, warmup=20, cal=None) -> Result:
    """signal(past_prices, t) -> dict for JevDecision.parse. `past_prices` is sliced to [:t+1]
    by the harness, so a signal cannot read the future unless it cheats via closure (see tests)."""
    limits, ks, cal = limits or RiskLimits(), KillSwitch(), cal or Calibrator()
    eq = peak = day0 = equity
    pending = []          # (exit_t, side, entry_px, notional, raw_conf)
    preds, outs, trades, wins, maxdd = [], [], 0, 0, 0.0
    busy_until = -1
    shadow = []           # (exit_t, direction, entry_px, raw_conf): every signal, traded or not
    for t in range(warmup, len(prices)):
        for item in [x for x in pending if x[0] == t]:      # resolve trades whose horizon ended
            _, side, ent, notional, conf = item
            sgn = 1 if side == "long" else -1
            ret = sgn * (prices[t] * (1 - sgn * slip_bps / 1e4) / ent - 1)
            eq += notional * ret - notional * fee_bps / 1e4
            win = 1 if ret > 0 else 0
            wins += win; preds.append(conf); outs.append(win)
            pending.remove(item)
            peak = max(peak, eq); maxdd = max(maxdd, (peak - eq) / peak)
        for item in [x for x in shadow if x[0] == t]:        # shadow calibration, resolved causally
            _, dr, ent0, conf0 = item
            if dr != "neutral":
                cal.update(conf0, 1 if (prices[t] > ent0) == (dr == "long") else 0)
            shadow.remove(item)
        if t + horizon >= len(prices):
            continue
        try:
            j = JevDecision.parse(signal(prices[:t + 1], t))
        except Exception:
            continue                                         # malformed -> hold
        shadow.append((t + horizon, j.direction, prices[t], j.direction_confidence))
        if t <= busy_until:
            continue
        d = decide(j, limits, ks, cal, equity=eq, peak_equity=peak, day_start_equity=day0)
        if d["action"] != "fire":
            continue
        sgn = 1 if d["side"] == "long" else -1
        ent = prices[t] * (1 + sgn * slip_bps / 1e4)
        pending.append((t + horizon, d["side"], ent, d["notional"], j.direction_confidence))
        busy_until = t + horizon
        trades += 1
        eq -= d["notional"] * fee_bps / 1e4
    return Result(eq, maxdd, trades, wins / trades if trades else 0.0,
                  brier(preds, outs), ks.tripped)


def momentum_signal(k=5, scale=0.01):
    """Causal baseline: follow the last k-bar move. Placeholder for Jev; expected NO edge on noise."""
    def f(past, t):
        r = past[-1] / past[-1 - k] - 1
        return dict(regime="trending", direction="long" if r > 0 else "short",
                    direction_confidence=min(0.95, 0.5 + abs(r) / scale), toxic_flow=False,
                    setup_quality=3, risk_state="ok", reward_risk=1.5)
    return f
