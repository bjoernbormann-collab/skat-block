"""BRAIN step 2: fundamentals SCREEN (not theses). Joins DefiLlama revenue/fees with TVL/mcap, filters for
liquidity, ranks by revenue momentum and valuation. Revenue != value accrual to the token: every row still
needs manual review of buybacks/staking/governance, unlocks, and whether the move is already priced in."""
import datetime as dt, json, time, urllib.error, urllib.request

UA = {"User-Agent": "trading-agent-research/0.1"}
Q = "excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
        return json.load(r)


def screen(min_mcap=300e6):
    """Group children under their parentProtocol (e.g. parent#aave) so revenue is summed across versions
    and the token's mcap/gecko_id is taken from whichever child carries it."""
    rev = get(f"https://api.llama.fi/overview/fees?{Q}&dataType=dailyRevenue")["protocols"]
    fees = {p["slug"]: p for p in get(f"https://api.llama.fi/overview/fees?{Q}")["protocols"]}
    prots = get("https://api.llama.fi/protocols")
    meta = {}                                   # group key -> token metadata
    for p in prots:
        k = p.get("parentProtocol") or p["slug"]
        m = meta.setdefault(k, {"tvl": 0.0, "tvl7": None})
        m["tvl"] += p.get("tvl") or 0
        if p.get("mcap") and p.get("gecko_id") and "gid" not in m:
            m.update(gid=p["gecko_id"], mcap=p["mcap"], sym=p["symbol"])
    grp = {}
    for r in rev:
        k = r.get("parentProtocol") or r["slug"]
        g = grp.setdefault(k, dict(name=r["name"], cat=r.get("category"), r30=0.0, r60=0.0, f30=0.0, n=0))
        g["r30"] += r.get("total30d") or 0
        g["r60"] += r.get("total60dto30d") or 0
        g["f30"] += (fees.get(r["slug"]) or {}).get("total30d") or 0
        g["n"] += 1
        if r.get("parentProtocol"):
            g["name"] = k.replace("parent#", "").title()
    rows, unmatched = [], 0
    for k, g in grp.items():
        m = meta.get(k)
        if not m or "gid" not in m:
            unmatched += 1
            continue
        if g["r30"] <= 0 or m["mcap"] < min_mcap:
            continue
        rows.append(dict(name=g["name"], sym=m["sym"], cat=g["cat"], gid=m["gid"], mcap=m["mcap"],
                         ann_rev=g["r30"] * 365 / 30, ps=m["mcap"] / (g["r30"] * 365 / 30),
                         rev_g=(g["r30"] / g["r60"] - 1) if g["r60"] > 0 else None,
                         fee_30d=g["f30"], tvl=m["tvl"], tvl7=None, n=g["n"]))
    return rows, unmatched, len(grp)


def volumes(ids, tries=4):
    """{gecko_id: (volume24h, change24h)} or None if CoinGecko stays rate-limited (caller must say so)."""
    out = {}
    for i in range(0, len(ids), 100):
        url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&per_page=250&ids=" + ",".join(ids[i:i + 100])
        for k in range(tries):
            try:
                for c in get(url):
                    out[c["id"]] = (c.get("total_volume") or 0, c.get("price_change_percentage_24h"))
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or k == tries - 1:
                    return None
                time.sleep(20 * (k + 1))
        time.sleep(3)
    return out


def report(top=15) -> str:
    rows, unm, n = screen()
    vols = volumes([r["gid"] for r in rows])
    if vols is not None:
        rows = [r for r in rows if vols.get(r["gid"], (0,))[0] >= 5e6]
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"# Fundamentals screen ({now})", "",
         "Sources: DefiLlama (api.llama.fi: dailyRevenue, fees, protocols), CoinGecko markets (volume). "
         f"Universe: {n} revenue-reporting protocols (children grouped by parent), {unm} dropped (no token/mcap match); kept mcap>=$300M" + (" and 24h volume>=$5M" if vols is not None else " (**24h volume filter NOT applied: CoinGecko rate-limited, check liquidity manually**)") + f": {len(rows)}.",
         "", "**This is a screen, not a set of theses.** Revenue is protocol revenue per DefiLlama and may not accrue to token holders.", ""]
    def table(title, key, rev):
        L.extend([f"## {title}", "", "| Token | Category | mcap | ann. revenue | mcap/revenue | 30d revenue vs prior 30d | TVL |", "|---|---|---|---|---|---|---|"])
        for r in sorted(rows, key=key, reverse=rev)[:top]:
            g = f"{r['rev_g']:+.0%}" if r["rev_g"] is not None else "n/a"
            t7 = f"${r['tvl']/1e9:.2f}B" if r["tvl"] else "n/a"
            L.append(f"| {r['sym']} ({r['name']}) | {r['cat']} | ${r['mcap']/1e9:.2f}B | ${r['ann_rev']/1e6:.0f}M | {r['ps']:.1f}x | {g} | {t7} |")
        L.append("")
    table("Cheapest on revenue (lowest mcap/revenue)", lambda r: r["ps"], False)
    table("Fastest revenue growth (30d vs prior 30d, revenue >= $10M annualised)",
          lambda r: (r["rev_g"] if (r["rev_g"] is not None and r["ann_rev"] >= 10e6) else -9), True)
    L += ["## Known data limits (read before using any row)",
          "- Only ~1% of revenue-reporting entries carry a liquid token that passes the filters; coverage is thin, many tokens are missing.",
          "- Chain rows (SOL, SUI, APT, ADA, AVAX, ...) look under-reported vs. known activity: DefiLlama revenue definitions differ by chain and category. Do NOT trust their mcap/revenue multiples.",
          "- 'Revenue' is DefiLlama's definition (after supply-side payouts); it may still not reach token holders. mcap/revenue is a crude screen, not a valuation.",
          "- Growth rates compare two 30-day windows and are noisy for small revenue bases.", "",
          "## Mandatory manual checks per candidate (NOT done here)",
          "- Does revenue reach token holders (buyback/burn/staking yield) or only a treasury/team?",
          "- Token unlock schedule over next 12 months vs. daily volume.",
          "- Holder concentration; incentive-driven revenue (mercenary liquidity, points)?",
          "- Catalyst: dated, and already priced in? What evidence would invalidate the thesis?",
          "- Bear case in one paragraph, written before looking at the chart."]
    return "\n".join(L)


if __name__ == "__main__":
    print(report())
