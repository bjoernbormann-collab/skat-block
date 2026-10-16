"""Paper-trading loop on live Kraken public data. No orders are ever sent anywhere.
  python3 tools/run_paper.py --jev placeholder          # plumbing test, never trades
  ANTHROPIC_API_KEY=... python3 tools/run_paper.py --jev claude --interval 300
State in data/paper_state.json (survives restarts); every decision in data/paper_log.jsonl."""
import argparse, json, pathlib, sys, time, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from reflex.paper import PaperEngine
from reflex.state import Book
from reflex.jev import PlaceholderJev, ClaudeJev

ap = argparse.ArgumentParser()
ap.add_argument("--jev", choices=["placeholder", "claude"], default="placeholder")
ap.add_argument("--pair", default="XBTUSD")
ap.add_argument("--interval", type=float, default=300, help="seconds between ticks (also bounds API cost)")
ap.add_argument("--horizon", type=float, default=3600, help="seconds a paper trade is held")
ap.add_argument("--equity", type=float, default=10_000)
ap.add_argument("--max-claude-calls-per-day", type=int, default=300)
a = ap.parse_args()

D = pathlib.Path(__file__).resolve().parents[1] / "data"; D.mkdir(exist_ok=True)


def get(path):
    with urllib.request.urlopen(f"https://api.kraken.com/0/public/{path}", timeout=10) as r:
        d = json.load(r)
    if d.get("error"): raise RuntimeError(d["error"])
    return next(v for k, v in d["result"].items() if k != "last")


def fetch_book(pair) -> Book:
    t0 = time.time()
    b = get(f"Depth?pair={pair}&count=10")
    tr = get(f"Trades?pair={pair}")
    trades = [(float(t[2]), float(t[0]), float(t[1]), "buy" if t[3] == "b" else "sell") for t in tr[-200:]]
    return Book(ts=t0, bids=[(float(p), float(s)) for p, s, _ in b["bids"]],
                asks=[(float(p), float(s)) for p, s, _ in b["asks"]], trades=trades)


jev = PlaceholderJev() if a.jev == "placeholder" else ClaudeJev()
eng = PaperEngine(jev, equity=a.equity, horizon_s=a.horizon, path=D / "paper_state.json", log_path=D / "paper_log.jsonl")
print(f"paper trading {a.pair} jev={a.jev} interval={a.interval}s equity={eng.broker.equity:.2f} (Ctrl+C to stop)", flush=True)
day, calls = None, 0
while True:
    t0 = time.time()
    try:
        d = time.strftime("%Y-%m-%d", time.gmtime())
        if d != day: day, calls = d, 0
        if a.jev == "claude" and calls >= a.max_claude_calls_per_day:
            print("daily Claude call cap reached; holding until tomorrow", flush=True)
        else:
            calls += 1
            out = eng.tick(fetch_book(a.pair), time.time())
            print(json.dumps(out), flush=True)
    except Exception as e:
        print("tick failed:", type(e).__name__, e, file=sys.stderr, flush=True)
    time.sleep(max(1.0, a.interval - (time.time() - t0)))
