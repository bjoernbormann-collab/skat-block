"""BRAIN step 1: live market regime snapshot from verified public sources. Every number carries its source;
anything that fails to fetch is reported as UNAVAILABLE, never filled in."""
import json, math, urllib.request, datetime as dt

UA = {"User-Agent": "trading-agent-research/0.1"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def kraken_daily(pair, n=400):
    d = get(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=1440")
    rows = next(v for k, v in d["result"].items() if k != "last")
    return [(int(r[0]), float(r[4])) for r in rows][-n:]


def regime(closes):
    px = [c for _, c in closes]
    r = [math.log(px[i] / px[i - 1]) for i in range(1, len(px))]
    vol30 = (sum(x * x for x in r[-30:]) / 30) ** 0.5 * math.sqrt(365)
    vol_all = (sum(x * x for x in r) / len(r)) ** 0.5 * math.sqrt(365)
    sma50, sma200 = sum(px[-50:]) / 50, sum(px[-200:]) / 200
    dd = px[-1] / max(px[-365:]) - 1
    if dd < -0.30 and vol30 > 1.5 * vol_all:
        reg = "crisis"
    elif vol30 > 1.3 * vol_all:
        reg = "high_vol"
    elif px[-1] > sma50 > sma200 or px[-1] < sma50 < sma200:
        reg = "trending"
    else:
        reg = "mean_reverting"
    return dict(last=px[-1], ret30=px[-1] / px[-31] - 1, ret90=px[-1] / px[-91] - 1, vol30=vol30,
                vol_ratio=vol30 / vol_all, sma50=sma50, sma200=sma200, drawdown_1y=dd, regime=reg)


def build() -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"# Market regime snapshot ({now})", ""]
    for name, pair in (("BTC", "XBTUSD"), ("ETH", "ETHUSD")):
        try:
            g = regime(kraken_daily(pair))
            L += [f"## {name} [Kraken daily OHLC, api.kraken.com]",
                  f"- price {g['last']:.0f} | 30d {g['ret30']:+.1%} | 90d {g['ret90']:+.1%} | drawdown vs 1y high {g['drawdown_1y']:+.1%}",
                  f"- 30d realized vol {g['vol30']:.0%} annualised (x{g['vol_ratio']:.2f} of 400d norm) | SMA50 {g['sma50']:.0f} / SMA200 {g['sma200']:.0f}",
                  f"- **rule-based regime: {g['regime']}**", ""]
        except Exception as e:
            L += [f"## {name}: UNAVAILABLE ({e})", ""]
    try:
        g = get("https://api.coingecko.com/api/v3/global")["data"]
        L += ["## Dominance and market size [CoinGecko /global]",
              f"- BTC dominance {g['market_cap_percentage']['btc']:.1f}% | ETH {g['market_cap_percentage']['eth']:.1f}%",
              f"- total market cap ${g['total_market_cap']['usd']/1e12:.2f}T | 24h change {g['market_cap_change_percentage_24h_usd']:+.1f}%", ""]
    except Exception as e:
        L += [f"## Dominance: UNAVAILABLE ({e})", ""]
    try:
        s = get("https://stablecoins.llama.fi/stablecoins?includePrices=false")["peggedAssets"]
        tot = sum((a.get("circulating") or {}).get("peggedUSD", 0) for a in s)
        prev = sum((a.get("circulatingPrevMonth") or {}).get("peggedUSD", 0) for a in s)
        L += ["## Stablecoin liquidity [DefiLlama stablecoins]",
              f"- circulating ${tot/1e9:.0f}B | 1-month change {tot/prev-1:+.1%}", ""]
    except Exception as e:
        L += [f"## Stablecoins: UNAVAILABLE ({e})", ""]
    try:
        f = get("https://api.alternative.me/fng/?limit=2")["data"]
        L += ["## Sentiment [alternative.me Fear & Greed]", f"- {f[0]['value']} ({f[0]['value_classification']}), previous {f[1]['value']}", ""]
    except Exception as e:
        L += [f"## Sentiment: UNAVAILABLE ({e})", ""]
    L += ["## Not available from this environment",
          "- Perp funding / open interest (Binance futures blocked, HTTP 451); needs another venue's API or a paid feed.",
          "- Macro (rates, DXY, equities): not fetched, no verified free source wired in."]
    return "\n".join(L)


if __name__ == "__main__":
    print(build())
