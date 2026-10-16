"""Deterministic state engine: live order book -> one compact snapshot (<500 tokens)."""
import json
import math
from dataclasses import dataclass


@dataclass
class Book:
    ts: float                      # exchange timestamp of this snapshot (seconds)
    bids: list                     # [(price, size)] best first
    asks: list
    trades: list                   # [(ts, price, size, side)] recent, side in {"buy","sell"}
    position: float = 0.0          # signed units
    equity: float = 0.0
    peak_equity: float = 0.0


def compute_state(b: Book, depth: int = 5) -> dict:
    # Causality: only use trades at or before the snapshot time (no future leakage).
    tr = [t for t in b.trades if t[0] <= b.ts]
    bb, ba = b.bids[0][0], b.asks[0][0]
    mid = (bb + ba) / 2
    bv = sum(s for _, s in b.bids[:depth])
    av = sum(s for _, s in b.asks[:depth])
    imbalance = (bv - av) / (bv + av) if bv + av else 0.0
    rets = [math.log(tr[i][1] / tr[i - 1][1]) for i in range(1, len(tr)) if tr[i - 1][1] > 0]
    vol = (sum(r * r for r in rets) / len(rets)) ** 0.5 if rets else 0.0
    buy = sum(t[2] for t in tr if t[3] == "buy")
    sell = sum(t[2] for t in tr if t[3] == "sell")
    dd = (b.peak_equity - b.equity) / b.peak_equity if b.peak_equity > 0 else 0.0
    return {
        "ts": b.ts, "mid": round(mid, 4),
        "spread_bps": round((ba - bb) / mid * 1e4, 2),
        "imbalance": round(imbalance, 3),
        "realized_vol": round(vol, 6),
        "flow_net": round((buy - sell) / (buy + sell), 3) if buy + sell else 0.0,
        "inventory": b.position,
        "drawdown": round(dd, 4),
    }


def snapshot_tokens(state: dict) -> int:
    """Conservative token estimate (~3 chars/token) used to enforce the <500 budget."""
    return math.ceil(len(json.dumps(state, separators=(",", ":"))) / 3)
