import sys, pathlib, unittest, random
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from evaluate_paper import evaluate, render


def rows(days, n_trades, mean, seed=1, errs=0):
    rng, out, eq = random.Random(seed), [], 10_000.0
    for i in range(days * 24):
        out.append({"ts": i * 3600.0, "action": "hold", "reason": "jev_error:X" if i < errs else "gate", "equity": eq, "killed": False})
    for i in range(n_trades):
        r = rng.gauss(mean, 0.01); eq *= 1 + r * 0.1
        out.append({"event": "trade_closed", "ts": i * 3600.0, "net_ret": r, "notional": 1000})
        out.append({"event": "shadow", "ts": i, "conf": 0.7, "dir": "long", "correct": 1 if rng.random() < 0.7 else 0})
    out.append({"ts": days * 86400.0, "action": "hold", "equity": eq, "killed": False})
    return out


class T(unittest.TestCase):
    def test_not_enough_data(self):
        self.assertEqual(evaluate(rows(5, 10, 0.01))["verdict"], "NOT ENOUGH DATA")

    def test_candidate_when_edge_real(self):
        self.assertEqual(evaluate(rows(40, 300, 0.01))["verdict"], "CANDIDATE")

    def test_stop_when_no_edge(self):
        self.assertEqual(evaluate(rows(40, 300, -0.002))["verdict"], "STOP")

    def test_stop_on_jev_errors(self):
        o = evaluate(rows(40, 300, 0.01, errs=100)); self.assertEqual(o["verdict"], "STOP")

    def test_render_runs(self):
        self.assertIn("VERDICT", render(evaluate(rows(40, 300, 0.01))))


if __name__ == "__main__":
    unittest.main()
