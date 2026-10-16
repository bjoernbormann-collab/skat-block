"""Historical data loader: Binance Public Data monthly klines (no API key). Cached under data/."""
import csv, io, pathlib, urllib.request, zipfile

BASE = "https://data.binance.vision/data/spot/monthly/klines"
CACHE = pathlib.Path(__file__).resolve().parents[1] / "data"


def month_closes(symbol: str, interval: str, ym: str) -> list:
    """Returns [(open_time_s, close)] for one month; [] if the month isn't published yet."""
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{symbol}-{interval}-{ym}.zip"
    if not f.exists():
        url = f"{BASE}/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                f.write_bytes(r.read())
        except Exception:
            return []
    out = []
    with zipfile.ZipFile(f) as z, z.open(z.namelist()[0]) as fh:
        for row in csv.reader(io.TextIOWrapper(fh)):
            if not row or not row[0].isdigit():
                continue
            t = int(row[0])
            t = t // 1_000_000 if t > 10**14 else t // 1000   # us (2025+) or ms
            out.append((t, float(row[4])))
    return out


def load(symbol="BTCUSDT", interval="1h", start="2023-01", end="2026-09") -> list:
    y, m = map(int, start.split("-")); ey, em = map(int, end.split("-"))
    rows = []
    while (y, m) <= (ey, em):
        rows += month_closes(symbol, interval, f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    rows.sort()
    return rows
