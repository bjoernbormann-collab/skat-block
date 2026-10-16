import sys, pathlib, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from reflex.paper import PaperEngine
from reflex.state import Book
from reflex.jev import PlaceholderJev, SCHEMA

GOOD = dict(regime="trending", direction="long", direction_confidence=0.95, toxic_flow=False,
            setup_quality=3, risk_state="ok", reward_risk=2.0)


class Fake:
    def __init__(self, out): self.out, self.n = out, 0
    def decide(self, s):
        self.n += 1
        if isinstance(self.out, Exception): raise self.out
        return self.out


def book(ts, mid=100.0):
    return Book(ts=ts, bids=[(mid - .5, 5)] * 5, asks=[(mid + .5, 5)] * 5, trades=[(ts - 1, mid, 1, "buy")])


class T(unittest.TestCase):
    def trusted(self, eng):
        for _ in range(60): eng.cal.update(0.95, 1)

    def test_fire_hold_close_cycle(self):
        eng = PaperEngine(Fake(GOOD), horizon_s=100); self.trusted(eng)
        r = eng.tick(book(1000), 1000.1); self.assertEqual(r["action"], "fire")
        self.assertEqual(eng.tick(book(1010), 1010.1)["reason"], "in_position")
        eng.tick(book(1101, mid=102.0), 1101.1)                       # exit with a gain
        self.assertEqual(eng.closed, 1); self.assertGreater(eng.pos["exit_ts"], 1101.1);   # closed, then Jev re-signalled
        self.assertGreater(eng.broker.equity, 10_000 - 20)

    def test_jev_error_never_trades(self):
        for err in (RuntimeError("down"), ):
            eng = PaperEngine(Fake(err)); r = eng.tick(book(1000), 1000.1)
            self.assertEqual(r["action"], "hold"); self.assertTrue(r["reason"].startswith("jev_error"))
        eng = PaperEngine(Fake({"junk": 1})); self.assertEqual(eng.tick(book(1000), 1000.1)["action"], "hold")

    def test_stale_book_blocks(self):
        eng = PaperEngine(Fake(GOOD)); self.trusted(eng)
        self.assertEqual(eng.tick(book(1000), 1100)["reason"], "stale_snapshot")

    def test_state_survives_restart(self):
        p = pathlib.Path(tempfile.mkdtemp()) / "s.json"
        e1 = PaperEngine(Fake(GOOD), path=p); self.trusted(e1); e1.tick(book(1000), 1000.1)
        e2 = PaperEngine(Fake(GOOD), path=p)
        self.assertEqual(e2.pos, e1.pos); self.assertEqual(e2.cal.n, e1.cal.n); self.assertEqual(e2.broker.equity, e1.broker.equity)

    def test_placeholder_never_fires(self):
        eng = PaperEngine(PlaceholderJev()); self.trusted(eng)
        self.assertNotEqual(eng.tick(book(1000), 1000.1)["action"], "fire")

    def test_schema_matches_parser(self):
        from reflex.schema import JevDecision
        JevDecision.parse({k: GOOD[k] for k in SCHEMA["required"]})


if __name__ == "__main__":
    unittest.main()
