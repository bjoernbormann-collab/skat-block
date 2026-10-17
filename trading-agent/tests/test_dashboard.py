import sys, pathlib, unittest, tempfile, json, threading, urllib.request, urllib.error
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dashboard as D
from http.server import ThreadingHTTPServer


def make(tmp):
    rows = [{"ts": 1000.0 + i * 300, "action": "hold", "reason": "gate", "mid": 100.0, "equity": 20.0, "killed": False} for i in range(10)]
    rows.append({"event": "trade_closed", "ts": 1500.0, "side": "long", "net_ret": 0.01, "notional": 4.0, "why": "time"})
    (tmp / "paper_log.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + '\n{"half writt')   # torn last line
    (tmp / "paper_state.json").write_text(json.dumps({"pos": None, "ks": [True, "max_drawdown"]}))


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); make(self.tmp)
        D.H.data_dir = self.tmp
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), D.H); self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self): self.srv.shutdown()

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r: return r.status, r.read()
        except urllib.error.HTTPError as e: return e.code, e.read()

    def test_status_and_torn_line(self):
        c, b = self.get("/api/status?agent=paper"); d = json.loads(b)
        self.assertEqual(c, 200); self.assertEqual(d["mode"], "PAPER"); self.assertTrue(d["killed"])
        self.assertEqual(d["kill_reason"], "max_drawdown"); self.assertEqual(len(d["equity"]), 10); self.assertEqual(len(d["trades"]), 1)

    def test_fresh_agent_without_scored_signals_is_valid_json(self):
        # regression: brier/hit are NaN until the first signal is scored; NaN is invalid JSON in browsers
        c, b = self.get("/api/status?agent=paper"); txt = b.decode()
        self.assertNotIn("NaN", txt); json.loads(txt, parse_constant=lambda x: self.fail("non-finite constant " + x))

    def test_agent_whitelist_blocks_paths(self):
        for bad in ("../etc/passwd", "paper_log", "%2e%2e/x", ""):
            self.assertEqual(self.get("/api/status?agent=" + bad)[0], 404)

    def test_page_and_list(self):
        self.assertEqual(self.get("/")[0], 200); self.assertEqual(json.loads(self.get("/api/agents")[1]), ["paper"])
        self.assertEqual(self.get("/nope")[0], 404)

    def test_pwa_assets_served_with_right_types(self):
        for path, ctype in (("/manifest.webmanifest", "application/manifest+json"), ("/sw.js", "text/javascript"),
                            ("/icon-192.png", "image/png"), ("/icon-512.png", "image/png"), ("/apple-touch-icon.png", "image/png")):
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                self.assertEqual(r.status, 200); self.assertTrue(r.headers["Content-Type"].startswith(ctype), path)
        m = json.loads(self.get("/manifest.webmanifest")[1]); self.assertEqual(m["display"], "standalone")

    def test_assets_whitelist_blocks_traversal(self):
        for bad in ("/../tools/dashboard.py", "/sw.js/../../dashboard.py", "/%2e%2e/dashboard.py", "/icon-192.png/x"):
            self.assertNotEqual(self.get(bad)[0], 200, bad)

    def test_sw_never_caches_api(self):
        self.assertIn('startsWith("/api/")', self.get("/sw.js")[1].decode())

    def test_read_only(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/status?agent=paper", data=b"x", method="POST")
        with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(req)


if __name__ == "__main__":
    unittest.main()
