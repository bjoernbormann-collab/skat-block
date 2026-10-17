# 24/7 crypto trading agent: BRAIN / REFLEX split

**Status: REFLEX layer and offline replay harness built and tested (27 tests, go/no-go evaluation, paper loop, Jev interface, BRAIN research v0, real-data loader, walk-forward, order-book recorder). Paper trading only. Research layer, live data, and live execution are NOT built.**

## Architecture
- **BRAIN (slow, Opus-class):** regime research, strategy derivation, backtests, overnight review, escalations. Not implemented here; it needs live data and sources.
- **REFLEX (fast, Jev):** per-candle decision. Jev fills a typed schema (`reflex/schema.py`). Code decides everything else.
- The model proposes. Deterministic code gates, sizes, and risk-checks. The model cannot override risk.

## Code map (`reflex/`)
| File | Role |
|---|---|
| `schema.py` | Strict Jev schema; malformed output raises, caller holds |
| `state.py` | Order book -> compact snapshot (<500 tokens), causal timestamps only |
| `calibration.py` | Brier score + binned recalibration; trusts Jev only downward, shrinks when data is thin |
| `sizing.py` | Quarter-Kelly from calibrated p |
| `risk.py` | 15% max drawdown, position cap, daily loss, latched kill switch (human reset) |
| `gate.py` | fire only if: no toxic flow, setup_quality>=2, calibrated p>0.80, risk_state ok; escalate if conf<0.60 or crisis |
| `replay.py` | Backtest harness: causal signal, real gate/risk/sizing, fees+slippage, Brier, kill switch. Tests prove a leaky oracle is caught and a causal momentum baseline has no edge on noise |
| `execution.py` | Paper broker. Live path intentionally absent |

Run: `python3 -m unittest discover -s tests -v`

## Tools
- `python3 tools/evaluate.py BTCUSDT|ETHUSDT`: walk-forward on Binance Public Data (hourly, 2023-2026), calibrate on fold k, test on fold k+1.
- `python3 tools/record_books.py XBTUSD 3600 1.0`: record Kraken order-book snapshots (JSON lines in `data/`, git-ignored) for later replay.

## Paper trading on the Mac mini (`tools/run_paper.py`)
No orders are ever sent. Live Kraken public data -> state -> Jev -> gate/risk -> simulated fills. State, calibration track record, and open position persist in `data/paper_state.json`; every decision is appended to `data/paper_log.jsonl`.
```
cd skat-block/trading-agent
python3 tools/run_paper.py --jev placeholder            # plumbing test; never trades (confidence capped at 0.7)
pip3 install anthropic                                   # only for --jev claude
export ANTHROPIC_API_KEY=...                             # from console.anthropic.com, never commit
python3 tools/run_paper.py --jev claude --interval 300   # Claude Haiku 5.5 as Jev, one call per tick, 300 calls/day cap
```
Auto-start and restart after crash/reboot: `deploy/com.tradingagent.paper.plist` (launchd; instructions in the file).
`reflex/jev.py` holds the Jev interface: any object with `decide(state) -> dict` works, so a different model can replace Claude without touching gate, risk, or sizing. Any Jev error, refusal, or malformed output means HOLD.
**Not yet verified:** `ClaudeJev` has unit-level syntax checks only; it has not been run against the live API (no key in the build environment). Run it once on the Mac mini and check `data/paper_log.jsonl` for `jev_error` entries.

## Live dashboard (`tools/dashboard.py`)
Read-only web page over the agents' logs (every `data/*_log.jsonl` is an agent; `live_*` is marked LIVE): capital curve with hover, KPIs, open position, kill-switch banner, go/no-go verdict, calibration, recent decisions and trades, auto-refresh every 5 s, light/dark/phone layout. Binds to 127.0.0.1 only; no authentication, so reach it through an SSH tunnel (`ssh -L 8000:localhost:8000 user@server`, then http://localhost:8000). Service file: `deploy/tradingagent-dashboard.service`. It never writes or places orders.

## Go/no-go evaluation (`tools/evaluate_paper.py`)
Reads the paper log and applies criteria fixed in advance: >= 28 days, >= 100 closed trades, mean net return per trade > 0, t >= 2, max drawdown <= 10%, Jev error rate <= 5%, Brier < 0.25 (coin flip), kill switch never tripped. Verdicts: NOT ENOUGH DATA / STOP / CANDIDATE. Setup guides: `SETUP_MAC_MINI.md` (launchd) or `SETUP_ORACLE.md` (Linux server, systemd unit in `deploy/tradingagent.service`). Run only one instance.

## Deliberately NOT built: live order execution
There is no code path that sends a real order. Adding one belongs after a CANDIDATE verdict, behind an explicit operator approval flag, with withdrawal-restricted keys and a tiny capital cap.

## BRAIN v0 (`brain/`)
- `python3 -m brain.market_report`: live regime snapshot (Kraken, CoinGecko, DefiLlama, Fear&Greed), sources and timestamps on every figure, failures shown as UNAVAILABLE. Latest: `research/market_snapshot.md`.
- `python3 -m brain.evaluate_hypotheses`: five pre-registered hypotheses (params fixed, not tuned), out-of-sample, 18bp round-trip cost, PROMOTE only if >=30 trades, mean>0, t>=3 and positive in >=75% of folds.
- **Result (BTC and ETH, 2023-2026): all five rejected** (`research/hypothesis_results.txt`). Trend long-only and vol breakout are about flat after costs; 7-day momentum L/S loses; dip-buying has too few trades to conclude anything.
- `python3 -m brain.fundamentals`: DefiLlama revenue/TVL + CoinGecko liquidity screen (children grouped by parent protocol). Latest: `research/fundamentals_screen.md`. Coverage is thin (about 20 liquid tokens) and chain revenue looks unreliable; the report states its own data limits.
- Not done: per-token asymmetric setups (unlocks, fees, TVL, holder concentration, catalysts). Those need sourced, dated per-token data; none are listed here because none were verified.

## First real-data result (honest)
The momentum baseline (placeholder for Jev) hits only **46-51%** on 6h-ahead direction for BTC and ETH, and higher confidence does not mean higher hit rate. The calibrated gate therefore **never fires: 0 trades, 0% return** in all out-of-sample folds, versus buy&hold +190% (BTC) over the same period. That is the system working as designed: no demonstrated edge, no trading. It also shows the bar any real signal must clear. A shadow-calibration mode (every signal is scored after its horizon, traded or not) was added so the agent can build a track record without risking capital.

## Six build phases (spec -> architecture -> test-first -> review -> ship -> approval gate)
1. **Spec:** done in this README + schema. Open: universe, venue, daily-loss limit, latency budget.
2. **Architecture:** adapters for exchange feed, LLM client, store. Put AgentKit/Jev behind these interfaces once their docs are verified.
3. **Test-first:** done for REFLEX. Replay harness done on synthetic data. Next: recorded real books, walk-forward splits, property tests on the risk layer.
4. **Review:** adversarial review of the gate and kill switch; add a staleness check (reject snapshots older than N ms).
5. **Ship (paper):** run >= 4 weeks paper with fees, slippage, and latency modelled. Log every Jev output and outcome.
6. **Approval gate:** the operator approves live only after calibration (Brier) and drawdown criteria are met, in writing, with a small capital cap.

## Self-improvement loop (nightly, not implemented)
Replay session -> per-fill and per-miss attribution -> Brier by regime -> propose schema/prompt changes -> re-run backtest -> operator approves before deploy. Never auto-deploy changes to risk limits.

## WHAT COULD I BE WRONG ABOUT?
1. **There may be no edge.** Nothing here shows the strategy makes money. Most retail crypto automation loses after fees; "looks profitable" in a backtest is the default outcome of overfitting.
2. **The 0.80 gate is arbitrary.** It is only meaningful if Jev's confidence is calibrated, and LLM probabilities usually are not. The calibrator guards against this but needs a few hundred outcomes per bin first. Until then the agent will mostly hold, by design.
3. **Kelly overbets on noisy p.** Quarter Kelly helps, but p-estimation error dominates. Treat sizing as an upper bound.
4. **Catalyst already priced in** is a research question I did not answer. No asymmetric-setup list was produced because I did not run live, dated, sourced research and won't invent one.
5. **Value accrual to tokens, incentive-driven edge:** unexamined; belongs to the BRAIN phase with primary sources.
6. **Latency:** ~81 ms for a hosted LLM call per candle is a claim from the prompt I could not verify. Exchange rate limits, outages, and stale data can break the "reflex" assumption. Add stale-snapshot rejection.
7. **Tail risk:** a 15% drawdown limit cannot stop gap moves, exchange failure, API key compromise, or liquidation cascades. Use exchange-side stops, withdrawal-restricted keys, and tiny initial capital.
8. **Hard limits live in code, but only if every order path goes through `gate.decide`.** Enforce that structurally at the execution adapter.
9. Third-party services named in the brief (agentkit.xyz, console.typesafe.ai) were not verified or integrated.
