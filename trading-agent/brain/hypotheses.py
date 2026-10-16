"""Pre-registered hypotheses. Parameters are fixed a priori (NOT tuned) to limit overfitting.
Each returns a position in {-1,0,1} from past prices only. Horizon is HORIZON bars, non-overlapping."""
import math

HORIZON = 24   # hourly bars


def _ret(p, k): return p[-1] / p[-1 - k] - 1
def _vol(p, k):
    r = [math.log(p[-i] / p[-i - 1]) for i in range(1, k + 1)]
    return (sum(x * x for x in r) / k) ** 0.5


def h_trend_long_only(p):      # H1: long only above 50-day SMA (hourly bars)
    return 1 if len(p) > 1200 and p[-1] > sum(p[-1200:]) / 1200 else 0

def h_tsmom_7d(p):             # H2: follow the 7-day move, long/short
    return (1 if _ret(p, 168) > 0 else -1) if len(p) > 169 else 0

def h_dip_buy(p):              # H3: buy a >2 sigma 24h drop (mean reversion)
    if len(p) < 24 * 31: return 0
    sig = _vol(p, 24 * 30) * math.sqrt(24)
    return 1 if _ret(p, 24) < -2 * sig else 0

def h_vol_breakout(p):         # H4: vol compression (bottom quintile 7d vol) then follow 24h move
    if len(p) < 24 * 90 + 170: return 0
    v = _vol(p, 168)
    hist = sorted(_vol(p[:len(p) - i], 168) for i in range(0, 24 * 90, 24))
    return (1 if _ret(p, 24) > 0 else -1) if v <= hist[len(hist) // 5] else 0

def h_trend_regime_filtered_dip(p):   # H5: dip buy only inside an uptrend (regime-aware)
    return 1 if h_dip_buy(p) and h_trend_long_only(p) else 0

REGISTRY = {"H1 trend long-only": h_trend_long_only, "H2 7d momentum L/S": h_tsmom_7d,
            "H3 dip buy": h_dip_buy, "H4 vol breakout": h_vol_breakout,
            "H5 dip buy in uptrend": h_trend_regime_filtered_dip}
