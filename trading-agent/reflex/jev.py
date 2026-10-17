"""Jev = the fast per-candle decision model. Any object with decide(state: dict) -> dict works.
The dict is validated by JevDecision.parse; anything malformed means HOLD."""
import json
import os

SYSTEM = (
    "You are the fast decision layer of a crypto trading system. You receive one compact market-state snapshot "
    "(spread_bps, imbalance in [-1,1], realized_vol, flow_net in [-1,1], inventory, drawdown) and must classify it. "
    "You do not size or place orders; deterministic code does that. Be conservative: use direction 'neutral' and "
    "low setup_quality unless the snapshot gives a clear, specific reason. direction_confidence is your honest "
    "probability that the direction is right over the next hour; do not inflate it. toxic_flow is true if the "
    "flow looks informed or adverse (strong one-sided flow against a thin book, spread blowout). "
    "setup_quality: 0 none, 1 weak, 2 decent, 3 excellent. risk_state: ok, reduce, or halt. "
    "reward_risk is the target-to-stop ratio of your idea as a positive number (for example 1.5); "
    "when direction is neutral, use 1.0."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "regime": {"type": "string", "enum": ["trending", "mean_reverting", "high_vol", "crisis"]},
        "direction": {"type": "string", "enum": ["long", "short", "neutral"]},
        "direction_confidence": {"type": "number"},
        "toxic_flow": {"type": "boolean"},
        "setup_quality": {"type": "integer", "enum": [0, 1, 2, 3]},
        "risk_state": {"type": "string", "enum": ["ok", "reduce", "halt"]},
        "reward_risk": {"type": "number"},
    },
    "required": ["regime", "direction", "direction_confidence", "toxic_flow", "setup_quality", "risk_state", "reward_risk"],
    "additionalProperties": False,
}


class PlaceholderJev:
    """Plumbing test only. Its confidence is capped at 0.7, so the 0.80 gate never fires on it."""
    def decide(self, state: dict) -> dict:
        score = state["imbalance"] + state["flow_net"]
        return dict(regime="mean_reverting", direction="long" if score > 0.4 else "short" if score < -0.4 else "neutral",
                    direction_confidence=min(0.7, 0.5 + abs(score) / 10), toxic_flow=state["spread_bps"] > 10,
                    setup_quality=1, risk_state="ok", reward_risk=1.5)


class ClaudeJev:
    """Claude via the official SDK. Key comes from ANTHROPIC_API_KEY (never stored in the repo)."""
    def __init__(self, model="claude-haiku-5-5", effort="low"):
        import anthropic  # pip install anthropic
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self.client, self.model, self.effort = anthropic.Anthropic(), model, effort
        self.calls = 0

    def decide(self, state: dict) -> dict:
        self.calls += 1
        r = self.client.messages.create(
            model=self.model, max_tokens=1024, system=SYSTEM,
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": json.dumps(state, separators=(",", ":"))}],
        )
        if r.stop_reason == "refusal":
            raise RuntimeError("model refused")           # caller treats any exception as HOLD
        text = next(b.text for b in r.content if b.type == "text")
        return json.loads(text)
