import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from reflex.schema import JevDecision, SchemaError
from reflex.risk import RiskLimits, KillSwitch
from reflex.calibration import Calibrator, brier
from reflex.gate import decide
from reflex.sizing import kelly_fraction
from reflex.state import Book, compute_state, snapshot_tokens

GOOD = dict(regime="trending", direction="long", direction_confidence=0.9, toxic_flow=False,
            setup_quality=3, risk_state="ok", reward_risk=2.0)
EQ = dict(equity=100_000, peak_equity=100_000, day_start_equity=100_000)


def cal(n=50, hit=1.0):
    c = Calibrator()
    for i in range(n):
        c.update(0.9, 1 if i < n * hit else 0)
    return c


class T(unittest.TestCase):
    def go(self, **kw):
        j = JevDecision.parse({**GOOD, **kw.pop("j", {})})
        return decide(j, RiskLimits(), kw.pop("ks", KillSwitch()), kw.pop("cal", cal()), **{**EQ, **kw})

    def test_fires(self):
        r = self.go(); self.assertEqual(r["action"], "fire")
        self.assertLessEqual(r["notional"], 10_000)

    def test_gate_blocks(self):
        for bad in ({"toxic_flow": True}, {"setup_quality": 1}, {"direction": "neutral"}, {"risk_state": "reduce"}):
            self.assertEqual(self.go(j=bad)["action"], "hold", bad)

    def test_low_conf_escalates(self):
        self.assertEqual(self.go(j={"direction_confidence": 0.55})["action"], "escalate")
        self.assertEqual(self.go(j={"regime": "crisis"})["action"], "escalate")

    def test_uncalibrated_confidence_not_trusted(self):
        self.assertEqual(self.go(cal=Calibrator())["action"], "hold")       # no history -> shrunk
        self.assertEqual(self.go(cal=cal(hit=0.6))["action"], "hold")        # overconfident Jev

    def test_drawdown_latches_killswitch(self):
        ks = KillSwitch()
        self.assertEqual(self.go(ks=ks, equity=84_000)["reason"], "max_drawdown")
        self.assertTrue(ks.tripped)
        self.assertTrue(self.go(ks=ks)["reason"].startswith("kill_switch"))
        ks.reset("op"); self.assertEqual(self.go(ks=ks)["action"], "fire")

    def test_schema_strict(self):
        for bad in ({"setup_quality": 4}, {"direction": "up"}, {"direction_confidence": 1.2}, {"toxic_flow": "no"}):
            with self.assertRaises(SchemaError): JevDecision.parse({**GOOD, **bad})
        with self.assertRaises(SchemaError): JevDecision.parse({})

    def test_kelly_quarter(self):
        self.assertAlmostEqual(kelly_fraction(0.9, 2.0), (0.9 - 0.05) * 0.25)
        self.assertEqual(kelly_fraction(0.3, 1.0), 0.0)

    def test_state_causal_and_small(self):
        b = Book(ts=10, bids=[(99, 5)] * 5, asks=[(101, 3)] * 5,
                 trades=[(8, 100, 1, "buy"), (9, 101, 2, "sell"), (11, 500, 9, "buy")],  # last is future
                 equity=90, peak_equity=100)
        s = compute_state(b)
        self.assertLess(s["realized_vol"], 0.02)       # the future 500 print is excluded
        self.assertEqual(s["drawdown"], 0.1)
        self.assertLess(snapshot_tokens(s), 500)

    def test_brier(self):
        self.assertEqual(brier([1, 0], [1, 0]), 0.0)


if __name__ == "__main__":
    unittest.main()
