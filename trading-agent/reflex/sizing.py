"""Fractional Kelly sizing from a *calibrated* probability, capped at quarter Kelly."""


def kelly_fraction(p: float, reward_risk: float, cap: float = 0.25) -> float:
    """Kelly f* = p - (1-p)/b for win prob p, payoff ratio b. Returns scaled fraction in [0, cap*f*]."""
    f = p - (1 - p) / reward_risk
    return max(0.0, f) * cap


def size_notional(equity: float, p: float, reward_risk: float, max_position_frac: float) -> float:
    return min(equity * kelly_fraction(p, reward_risk), equity * max_position_frac)
