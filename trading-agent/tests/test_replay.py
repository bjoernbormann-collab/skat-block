import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from reflex.replay import random_walk, run, momentum_signal
from reflex.schema import JevDecision
from reflex.risk import RiskLimits, KillSwitch
from reflex.calibration import Calibrator
from reflex.gate import decide


def oracle(prices_full, h=5):
    """Deliberately leaky signal: peeks at the future via closure. Harness must make this look great,
    proving metrics respond to real information (and that the causal baseline doesn't get it)."""
    def f(past, t):
        up = prices_full[t + h] > prices_full[t]
        return dict(regime="trending", direction="long" if up else "short", direction_confidence=0.95,
                    toxic_flow=False, setup_quality=3, risk_state="ok", reward_risk=1.5)
    return f


class T(unittest.TestCase):
    def test_leak_is_detected(self):
        p = random_walk(3000, seed=1)
        warm = Calibrator()
        for _ in range(100): warm.update(0.95, 1)           # pre-trust so the gate lets it trade
        r = run(p, oracle(p), cal=warm)
        self.assertGreater(r.final_equity, 100_000 * 1.05)  # future knowledge => big profit

    def test_causal_signal_no_edge_on_noise(self):
        eqs = []
        for seed in range(10):
            p = random_walk(3000, seed=seed)
            warm = Calibrator()
            for _ in range(100): warm.update(0.95, 1)       # even fully trusted, noise gives no edge
            eqs.append(run(p, momentum_signal(), cal=warm).final_equity)
        self.assertLess(sum(eqs) / len(eqs), 100_000 * 1.01)   # mean not meaningfully profitable

    def test_uncalibrated_agent_mostly_holds(self):
        p = random_walk(2000, seed=3)
        r = run(p, momentum_signal())
        self.assertLess(r.trades, 5)                        # no track record -> shrunk confidence -> hold

    def test_stale_snapshot_blocks(self):
        j = JevDecision.parse(dict(regime="trending", direction="long", direction_confidence=0.9,
                                   toxic_flow=False, setup_quality=3, risk_state="ok"))
        c = Calibrator()
        for _ in range(50): c.update(0.9, 1)
        kw = dict(equity=1e5, peak_equity=1e5, day_start_equity=1e5)
        self.assertEqual(decide(j, RiskLimits(), KillSwitch(), c, **kw, age_ms=50)["action"], "fire")
        self.assertEqual(decide(j, RiskLimits(), KillSwitch(), c, **kw, age_ms=5000)["reason"], "stale_snapshot")


if __name__ == "__main__":
    unittest.main()
