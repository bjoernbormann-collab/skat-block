"""Typed Jev decision schema. Jev only fills this in; code decides what happens."""
from dataclasses import dataclass
from typing import Literal

Regime = Literal["trending", "mean_reverting", "high_vol", "crisis"]
Direction = Literal["long", "short", "neutral"]
RiskState = Literal["ok", "reduce", "halt"]
Action = Literal["fire", "hold", "escalate"]


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class JevDecision:
    regime: Regime
    direction: Direction
    direction_confidence: float  # raw model probability, 0..1 (calibrated downstream)
    toxic_flow: bool
    setup_quality: int           # 0..3
    risk_state: RiskState
    reward_risk: float = 1.5     # target/stop ratio proposed by Jev

    @classmethod
    def parse(cls, d: dict) -> "JevDecision":
        """Strict parse; anything malformed raises, and the caller must hold."""
        try:
            x = cls(
                regime=d["regime"], direction=d["direction"],
                direction_confidence=float(d["direction_confidence"]),
                toxic_flow=d["toxic_flow"], setup_quality=d["setup_quality"],
                risk_state=d["risk_state"], reward_risk=float(d.get("reward_risk", 1.5)),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise SchemaError(f"bad Jev output: {e}") from e
        if x.regime not in ("trending", "mean_reverting", "high_vol", "crisis"):
            raise SchemaError("regime")
        if x.direction not in ("long", "short", "neutral"):
            raise SchemaError("direction")
        if x.risk_state not in ("ok", "reduce", "halt"):
            raise SchemaError("risk_state")
        if not isinstance(x.toxic_flow, bool):
            raise SchemaError("toxic_flow must be bool")
        if not isinstance(x.setup_quality, int) or isinstance(x.setup_quality, bool) \
                or not 0 <= x.setup_quality <= 3:
            raise SchemaError("setup_quality 0..3")
        if not 0.0 <= x.direction_confidence <= 1.0:
            raise SchemaError("confidence range")
        if x.reward_risk <= 0:
            raise SchemaError("reward_risk")
        return x
