"""Paper-trading engine. One tick(): resolve due trades/signals, ask Jev, gate, (paper) execute, persist."""
import json, pathlib, time
from .schema import JevDecision
from .state import Book, compute_state
from .risk import RiskLimits, KillSwitch
from .calibration import Calibrator
from .gate import decide
from .execution import PaperBroker


class PaperEngine:
    def __init__(self, jev, equity=10_000.0, horizon_s=3600, limits=None, max_age_s=5.0,
                 path=None, log_path=None, fee_bps=6.0, slip_bps=3.0):
        self.jev, self.horizon, self.limits, self.max_age = jev, horizon_s, limits or RiskLimits(), max_age_s
        self.path, self.log_path = path, log_path
        self.broker, self.ks, self.cal = PaperBroker(equity, fee_bps, slip_bps), KillSwitch(), Calibrator()
        self.peak = self.day0 = equity
        self.day = None
        self.pos = None            # dict: side, notional, entry, exit_ts
        self.shadow = []           # [exit_ts, direction, entry_mid, conf]
        self.closed = 0
        if path and pathlib.Path(path).exists():
            self._load()

    # ---- persistence (equity, calibration track record, open position, kill switch survive restarts)
    def _save(self):
        if not self.path: return
        s = dict(equity=self.broker.equity, peak=self.peak, day0=self.day0, day=self.day, pos=self.pos,
                 shadow=self.shadow, closed=self.closed, ks=[self.ks.tripped, self.ks.reason],
                 cal=dict(hits=self.cal.hits, n=self.cal.n))
        tmp = pathlib.Path(self.path).with_suffix(".tmp")
        tmp.write_text(json.dumps(s)); tmp.replace(self.path)

    def _load(self):
        s = json.loads(pathlib.Path(self.path).read_text())
        self.broker.equity, self.peak, self.day0, self.day = s["equity"], s["peak"], s["day0"], s["day"]
        self.pos, self.shadow, self.closed = s["pos"], s["shadow"], s["closed"]
        self.ks.tripped, self.ks.reason = s["ks"]
        for k, v in s["cal"]["hits"].items(): self.cal.hits[int(k)] = v
        for k, v in s["cal"]["n"].items(): self.cal.n[int(k)] = v

    def _log(self, rec):
        if self.log_path:
            with open(self.log_path, "a") as f: f.write(json.dumps(rec) + "\n")

    def tick(self, book: Book, now: float) -> dict:
        mid = (book.bids[0][0] + book.asks[0][0]) / 2
        today = time.strftime("%Y-%m-%d", time.gmtime(now))
        if today != self.day:
            self.day, self.day0 = today, self.broker.equity
        # resolve shadow signals (calibration: every signal is scored, traded or not)
        for s in [x for x in self.shadow if x[0] <= now]:
            if s[1] != "neutral":
                self.cal.update(s[3], 1 if (mid > s[2]) == (s[1] == "long") else 0)
            self.shadow.remove(s)
        # close due position
        if self.pos and now >= self.pos["exit_ts"]:
            sgn = 1 if self.pos["side"] == "long" else -1
            ret = sgn * (mid * (1 - sgn * self.broker.slip / 1e4) / self.pos["entry"] - 1)
            self.broker.equity += self.pos["notional"] * ret - self.pos["notional"] * self.broker.fee / 1e4
            self.pos, self.closed = None, self.closed + 1
            self.peak = max(self.peak, self.broker.equity)
        book.position = (self.pos["notional"] if self.pos and self.pos["side"] == "long" else
                         -self.pos["notional"] if self.pos else 0.0)
        book.equity, book.peak_equity = self.broker.equity, self.peak
        state = compute_state(book)
        if self.pos:
            out = {"action": "hold", "reason": "in_position"}
        else:
            try:
                j = JevDecision.parse(self.jev.decide(state))
                self.shadow.append([now + self.horizon, j.direction, mid, j.direction_confidence])
                out = decide(j, self.limits, self.ks, self.cal, equity=self.broker.equity, peak_equity=self.peak,
                             day_start_equity=self.day0, age_ms=max(0.0, now - book.ts) * 1000,
                             max_age_ms=self.max_age * 1000)
                if out["action"] == "fire":
                    f = self.broker.order(out["side"], out["notional"], mid)
                    self.pos = dict(side=out["side"], notional=out["notional"], entry=f["px"], exit_ts=now + self.horizon)
            except Exception as e:                       # Jev down / malformed / refusal -> never trade
                out = {"action": "hold", "reason": f"jev_error:{type(e).__name__}"}
        out.update(ts=now, mid=mid, equity=round(self.broker.equity, 2), killed=self.ks.tripped)
        self._log(out); self._save()
        return out
