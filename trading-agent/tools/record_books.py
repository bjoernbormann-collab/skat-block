"""Records Kraken order-book snapshots (REST, stdlib only) as JSON lines for later replay.
python3 tools/record_books.py XBTUSD 3600 1.0   # pair, seconds to run, poll interval"""
import json, sys, time, urllib.request, pathlib

pair = sys.argv[1] if len(sys.argv) > 1 else "XBTUSD"
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 60
every = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
out = pathlib.Path(__file__).resolve().parents[1] / "data" / f"books-{pair}-{int(time.time())}.jsonl"
out.parent.mkdir(exist_ok=True)
end, n = time.time() + dur, 0
with out.open("a") as f:
    while time.time() < end:
        t0 = time.time()
        try:
            with urllib.request.urlopen(f"https://api.kraken.com/0/public/Depth?pair={pair}&count=10", timeout=10) as r:
                d = json.load(r)
            book = next(iter(d["result"].values()))
            f.write(json.dumps({"ts": t0, "bids": [[float(p), float(s)] for p, s, _ in book["bids"]],
                                "asks": [[float(p), float(s)] for p, s, _ in book["asks"]]}) + "\n")
            f.flush(); n += 1
        except Exception as e:
            print("skip:", e, file=sys.stderr)
        time.sleep(max(0, every - (time.time() - t0)))
print(f"wrote {n} snapshots to {out}")
