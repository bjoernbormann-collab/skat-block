# Setup auf dem Mac mini (Schritt für Schritt)

Alles ist Paper-Trading: **es werden keine echten Orders gesendet.**

## 1. Installieren
```
cd ~
git clone https://github.com/bjoernbormann-collab/skat-block.git
cd skat-block && git checkout claude/new-session-1od9nf
cd trading-agent
python3 -m unittest discover -s tests      # erwartet: OK (27 Tests)
```
Falls `python3` fehlt: `xcode-select --install`.

## 2. Plumbing-Test (ohne Schlüssel, ohne Kosten)
```
python3 tools/run_paper.py --jev placeholder --interval 5
```
Es erscheinen JSON-Zeilen mit `"action": "hold"`. Mit Ctrl+C beenden. Der Platzhalter handelt nie.

## 3. Claude als Jev (kostet wenige Cent pro Tag)
```
pip3 install anthropic
export ANTHROPIC_API_KEY=sk-ant-...      # von console.anthropic.com, nie ins Repo
python3 tools/run_paper.py --jev claude --interval 300
```
Prüfe nach 10 Minuten `data/paper_log.jsonl`: Einträge mit `jev_error` bedeuten, dass der API-Aufruf nicht funktioniert (Schlüssel, Guthaben, Modellname). Das ist der Teil, den ich nicht live testen konnte.
Kostenbremse: höchstens 300 Aufrufe pro Tag (`--max-claude-calls-per-day`).

## 4. Dauerbetrieb
1. Systemeinstellungen -> Energie: Ruhezustand verhindern, "Nach Stromausfall automatisch starten" aktivieren.
2. `deploy/com.tradingagent.paper.plist` nach `~/Library/LaunchAgents/` kopieren, `YOURNAME`, Pfad und Schlüssel eintragen, `--jev placeholder` auf `--jev claude` ändern.
3. `launchctl load ~/Library/LaunchAgents/com.tradingagent.paper.plist` (Stoppen: `unload`).
Der Stand (Kapital, Kalibrierung, offene Position, Notaus) bleibt über Neustarts erhalten.

## 5. Auswerten
```
python3 tools/evaluate_paper.py
```
Zeigt nach mindestens 28 Tagen und 100 abgeschlossenen Trades ein Urteil nach vorab festgelegten Kriterien (siehe `tools/evaluate_paper.py`):
- **NOT ENOUGH DATA**: weiterlaufen lassen.
- **STOP**: ein Kriterium ist durchgefallen (kein Edge, zu viel Drawdown, zu viele Jev-Fehler, Notaus). Nicht live gehen.
- **CANDIDATE**: alle Kriterien erfüllt. Das ist kein Freibrief, sondern nur die Berechtigung, über einen Start mit sehr kleinem Kapital nachzudenken.

## Dashboard
```
python3 tools/dashboard.py            # nur lokal erreichbar (127.0.0.1:8000), lesend
```
Vom eigenen Rechner (bei Oracle): `ssh -L 8000:localhost:8000 -i <key> ubuntu@<IP>`, dann im Browser http://localhost:8000. Dauerbetrieb: `deploy/tradingagent-dashboard.service` wie den Agenten-Dienst installieren. Nie ohne Tunnel ins Internet stellen (keine Anmeldung).

## 6. Orderbuch-Recorder (optional, für spätere Backtests)
`caffeinate -i python3 tools/record_books.py XBTUSD 86400 1.0`

## Notaus
Löst der Agent den Notaus aus (15 % Drawdown, Tagesverlust, Krise), bleibt er aus, bis du `data/paper_state.json` löschst oder `KillSwitch.reset` ausführst. Das ist Absicht.
