import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from brain.hypotheses import REGISTRY
from brain.evaluate_hypotheses import stats
from reflex.replay import random_walk


class T(unittest.TestCase):
    def test_short_history_is_flat(self):
        for f in REGISTRY.values():
            self.assertEqual(f([100.0] * 10), 0)

    def test_positions_valid_and_no_crash(self):
        p = random_walk(3000, seed=7, vol=0.003)
        for f in REGISTRY.values():
            for t in range(1300, 3000, 97):
                self.assertIn(f(p[:t + 1]), (-1, 0, 1))

    def test_stats_tstat(self):
        n, m, t = stats([0.01, 0.02, 0.03, 0.02])
        self.assertEqual(n, 4); self.assertGreater(t, 3)


if __name__ == "__main__":
    unittest.main()
