"""Hard risk layer. Pure code; the model can never override it."""
from dataclasses import dataclass


@dataclass
class RiskLimits:
    max_drawdown: float = 0.15      # of peak equity
    max_position_frac: float = 0.10  # of equity, notional
    max_daily_loss: float = 0.03     # of start-of-day equity (operator-tunable)
    jev_conf_floor: float = 0.60     # below this -> escalate to deep re-read


class KillSwitch:
    """Latched. Once tripped it stays tripped until a human calls reset()."""
    def __init__(self):
        self.tripped, self.reason = False, ""

    def trip(self, reason: str):
        self.tripped, self.reason = True, reason

    def reset(self, operator: str):
        self.tripped, self.reason = False, f"reset by {operator}"


def check(limits: RiskLimits, ks: KillSwitch, *, equity, peak_equity, day_start_equity,
          proposed_notional, regime) -> tuple:
    """Return (allowed, reason). Evaluated before EVERY order."""
    if ks.tripped:
        return False, f"kill_switch:{ks.reason}"
    if peak_equity > 0 and (peak_equity - equity) / peak_equity >= limits.max_drawdown:
        ks.trip("max_drawdown")
        return False, "max_drawdown"
    if day_start_equity > 0 and (day_start_equity - equity) / day_start_equity >= limits.max_daily_loss:
        ks.trip("daily_loss")
        return False, "daily_loss"
    if regime == "crisis":
        return False, "crisis_regime"
    if equity <= 0 or abs(proposed_notional) > limits.max_position_frac * equity + 1e-9:
        return False, "position_cap"
    return True, "ok"
