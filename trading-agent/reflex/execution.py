"""Execution. Paper broker only; live mode requires an explicit operator-approved flag and is not implemented."""
import os


class PaperBroker:
    def __init__(self, equity: float, fee_bps: float = 6.0, slip_bps: float = 3.0):
        self.equity, self.fee, self.slip, self.fills = equity, fee_bps, slip_bps, []

    def order(self, side: str, notional: float, mid: float) -> dict:
        px = mid * (1 + (self.slip / 1e4 if side == "long" else -self.slip / 1e4))
        cost = notional * self.fee / 1e4
        self.equity -= cost
        fill = {"side": side, "notional": notional, "px": px, "fee": cost}
        self.fills.append(fill)
        return fill


def live_enabled() -> bool:
    # Live trading is off by default and has no code path here; approval gate is the operator's.
    return False and os.environ.get("LIVE_TRADING_APPROVED") == "yes"
