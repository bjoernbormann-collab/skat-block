"""Read-only live dashboard for the agents' logs. No orders, no writes, no auth: it binds to 127.0.0.1 by default.
  python3 tools/dashboard.py                  # http://127.0.0.1:8000
  ssh -L 8000:localhost:8000 user@server      # then open http://localhost:8000 on your own computer
Shows every data/*_log.jsonl as an agent (paper_log -> PAPER, live_log -> LIVE)."""
import argparse, json, pathlib, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from evaluate_paper import evaluate  # noqa: E402

STATIC = ROOT / "tools" / "dashboard_static" / "index.html"


def agents(data_dir):
    return sorted(p.name[:-len("_log.jsonl")] for p in data_dir.glob("*_log.jsonl"))


def rows_of(path, max_bytes=20_000_000):
    out = []
    with open(path, "rb") as f:
        f.seek(0, 2); size = f.tell(); f.seek(max(0, size - max_bytes))
        if size > max_bytes: f.readline()                      # drop partial first line
        for line in f:
            try: out.append(json.loads(line))
            except ValueError: pass                            # half-written last line
    return out


def thin(pts, n=600):
    return pts if len(pts) <= n else [pts[int(i * (len(pts) - 1) / (n - 1))] for i in range(n)]


def status(data_dir, name):
    log = data_dir / f"{name}_log.jsonl"
    rows = rows_of(log)
    ticks = [r for r in rows if "event" not in r]
    m = evaluate(rows) if ticks else None
    st = {}
    sp = data_dir / f"{name}_state.json"
    if sp.exists():
        try: st = json.loads(sp.read_text())
        except ValueError: pass
    last = ticks[-1]["ts"] if ticks else None
    trades = [r for r in rows if r.get("event") == "trade_closed"][-15:]
    return {
        "agent": name, "mode": "LIVE" if name.startswith("live") else "PAPER", "now": time.time(), "last_ts": last,
        "age_s": time.time() - last if last else None,
        "metrics": m, "equity": thin([[t["ts"], t["equity"]] for t in ticks]),
        "recent": ticks[-25:][::-1], "trades": trades[::-1],
        "position": st.get("pos"), "killed": st.get("ks", [False, ""])[0], "kill_reason": st.get("ks", [False, ""])[1],
        "start_equity": ticks[0]["equity"] if ticks else None,
    }


class H(BaseHTTPRequestHandler):
    data_dir = ROOT / "data"

    def _send(self, code, body, ctype):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, STATIC.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/agents":
            return self._send(200, json.dumps(agents(self.data_dir)).encode(), "application/json")
        if u.path == "/api/status":
            name = (parse_qs(u.query).get("agent") or [""])[0]
            if name not in agents(self.data_dir):                   # whitelist: never build paths from user input
                return self._send(404, b'{"error":"unknown agent"}', "application/json")
            try:
                return self._send(200, json.dumps(status(self.data_dir, name), default=str).encode(), "application/json")
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
        self._send(404, b"not found", "text/plain")

    def log_message(self, *a): pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    a = ap.parse_args(); H.data_dir = pathlib.Path(a.data_dir)
    if a.host not in ("127.0.0.1", "localhost"):
        print("WARNING: no authentication. Do not expose this to the internet; use an SSH tunnel.", file=sys.stderr)
    print(f"dashboard on http://{a.host}:{a.port}  (agents: {', '.join(agents(H.data_dir)) or 'none yet'})", flush=True)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
