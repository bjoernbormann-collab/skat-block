"""REFLEX decision gate: Jev schema in, Action out. Fires only if every deterministic condition holds."""
from .schema import JevDecision
from .risk import RiskLimits, KillSwitch, check
from .sizing import size_notional
from .calibration import Calibrator


def decide(j: JevDecision, limits: RiskLimits, ks: KillSwitch, cal: Calibrator, *,
           equity, peak_equity, day_start_equity,
           age_ms: float = 0.0, max_age_ms: float = 1000.0) -> dict:
    # 0. Stale snapshot: never trade on old data.
    if age_ms > max_age_ms:
        return {"action": "hold", "reason": "stale_snapshot"}
    # 1. Low confidence or crisis regime -> hand to the slow brain, never trade on it.
    if j.direction_confidence < limits.jev_conf_floor or j.regime == "crisis":
        return {"action": "escalate", "reason": "low_confidence_or_crisis"}
    # 2. Gate: every condition must hold.
    p = cal.calibrated(j.direction_confidence)
    if j.direction == "neutral" or j.toxic_flow or j.setup_quality < 2 \
            or p <= 0.80 or j.risk_state != "ok":
        return {"action": "hold", "reason": "gate", "p_cal": round(p, 3)}
    # 3. Size from calibrated p, then hard risk check (model cannot override).
    notional = size_notional(equity, p, j.reward_risk, limits.max_position_frac)
    if notional <= 0:
        return {"action": "hold", "reason": "no_edge", "p_cal": round(p, 3)}
    signed = notional if j.direction == "long" else -notional
    ok, why = check(limits, ks, equity=equity, peak_equity=peak_equity,
                    day_start_equity=day_start_equity, proposed_notional=signed, regime=j.regime)
    if not ok:
        return {"action": "hold", "reason": why}
    return {"action": "fire", "side": j.direction, "notional": round(abs(signed), 2), "p_cal": round(p, 3)}
