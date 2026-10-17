# Übergabe: Trading-Agent (Stand 2026-10-17)

Diese Datei fasst die bisherige Arbeit aus einer Cloud-Sitzung zusammen. Du (Claude Code auf dem Mac mini des Nutzers) arbeitest ab jetzt lokal weiter.

## Umgang mit dem Nutzer
- **Antworte auf Deutsch.** Der Nutzer ist kein Entwickler: ein Schritt nach dem anderen, Befehle zum Kopieren, kurze Erklärungen, auf Rückmeldung warten.
- Ehrlich bleiben: **Es gibt keinen belegten Handelsvorteil.** Alle Backtests (BTC/ETH, 2023–2026) waren nach Kosten ohne Edge. Der Nutzer weiß das. Keine Gewinnversprechen.
- Keine Zugangsdaten in den Chat, ins Repo oder in Logs. Schlüssel gibt der Nutzer nur selbst im Terminal ein.
- Alles, was Geld bewegt, nur nach ausdrücklicher Bestätigung im jeweiligen Moment.

## Was existiert (Branch `claude/new-session-1od9nf`, 37 Tests grün: `python3 -m unittest discover -s tests`)
- `reflex/`: schema, state, gate (feuert nur bei: kein toxischer Flow, setup_quality>=2, kalibrierte Konfidenz>0.80, risk_state ok; Eskalation bei Konfidenz<0.60 oder Krise), risk (15 % Drawdown, Positionsgrenze, Tagesverlust, gelatchter Notaus), sizing (Viertel-Kelly), calibration (Shadow-Kalibrierung), paper (PaperEngine), jev (PlaceholderJev, ClaudeJev = claude-haiku-5-5), replay, walkforward, data.
- `brain/`: Marktbericht, Hypothesentest (alle 5 Hypothesen durchgefallen), Fundamentaldaten-Screen (dünn, Chain-Daten unzuverlässig).
- `tools/`: run_paper.py, evaluate_paper.py (Go/No-Go: >=28 Tage, >=100 Trades, t>=2, DD<=10 %, Brier<0.25), dashboard.py (lesend, 127.0.0.1:8000, installierbare PWA), record_books.py, evaluate.py.
- `deploy/`: oracle-cloud-init.sh, enable_claude.sh, systemd- und launchd-Dateien.
- Anleitungen: README.md, SETUP_ORACLE.md, SETUP_MAC_MINI.md, SETUP_HANDY.md.

## Was wo läuft
- **Oracle-Server** (Always Free, VM.Standard.E2.1.Micro, Ubuntu 24.04): `ubuntu@138.2.185.236`, SSH-Schlüssel auf dem Mac: `/Users/bjoernbormann/Downloads/oracle.key`.
  Verbindung: `ssh -o ServerAliveInterval=30 -i /Users/bjoernbormann/Downloads/oracle.key ubuntu@138.2.185.236`
- Dienste dort: `tradingagent` (Paper-Agent, **Jev = Claude Haiku 5.5**, läuft seit 2026-10-17 ca. 16:13 UTC, Intervall 300 s) und `tradingagent-dashboard`. Code in `~/skat-block`, Daten in `~/skat-block/trading-agent/data/`.
- Anthropic-Schlüssel liegt nur in `/etc/tradingagent.env` auf dem Server (root, chmod 600). Claude-Aufruf ist **live verifiziert** (gültige Antwort, kein jev_error).
- Tailscale ist auf dem Server **installiert und verbunden**. Noch offen: HTTPS in der Tailscale-Verwaltung aktivieren, `sudo tailscale serve --bg --https=443 localhost:8000`, `tailscale serve status`, Tailscale-App auf dem iPhone, Safari -> Zum Home-Bildschirm (siehe SETUP_HANDY.md). Nie `tailscale funnel` benutzen.

## Offene Aufgaben (in dieser Reihenfolge)
1. **Dashboard aufs iPhone** (SETUP_HANDY.md abschließen, siehe oben).
2. **SSH-Schlüssel ersetzen:** Der private Schlüssel `oracle.key` wurde versehentlich in einem Cloud-Chat angehängt (sein Inhalt steht dort im Verlauf). Empfohlen: neues Schlüsselpaar am Mac erzeugen (`ssh-keygen -t ed25519`), den öffentlichen Teil in `~/.ssh/authorized_keys` auf dem Server eintragen, den alten dort entfernen, alten Schlüssel löschen.
3. **Paper-Betrieb beobachten** (Tage bis Wochen). Auswertung: `python3 tools/evaluate_paper.py data/paper_log.jsonl` auf dem Server. Nicht vorschnell live gehen.
4. **Live-Modus mit hartem 20-€-Limit** (nur wenn der Nutzer es ausdrücklich will; er hat es grundsätzlich entschieden, aber noch nichts davon gebaut). Verbindliche Anforderungen:
   - Neues `reflex/kraken.py` (Standardbibliothek): Public- und Private-API, Signatur = base64(HMAC-SHA512(base64decode(secret), urlpath + SHA256(str(nonce)+postdata))). Test gegen Krakens Dokubeispiel: secret `kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg==`, urlpath `/0/private/AddOrder`, postdata `nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25`, erwartet `4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ==` (bei Abweichung gegen docs.kraken.com prüfen, nicht raten).
   - Paar XBTEUR, nur Marktorders, `ordermin` aus AssetPairs; unterhalb Minimum oder bei zu wenig Guthaben nicht senden (`OrderSkipped`, ohne Notaus). Füllpreise/Gebühren aus QueryOrders. Unklarer Orderstatus => Notaus.
   - **Harte Grenze `HARD_CAP_EUR = 20.0` im Code**, nur Long (Spot), eine Position gleichzeitig, Stop-Loss 3 % (clientseitig, im Positionsfall alle ~30 s prüfen) plus Zeitausstieg.
   - Scharf nur mit **zwei Schaltern**: `--live` UND Umgebungsvariable `LIVE_TRADING_APPROVED=ja-20-euro`. Sonst Probelauf (`AddOrder` mit `validate=true`, simulierte Fills). Modus deutlich in Start- und Logzeilen (DRY-RUN/LIVE).
   - Engine-Umbau minimal: Hooks `_do_open`/`_do_close`/`_stop_hit` in `reflex/paper.py`; `LiveEngine(PaperEngine)` überschreibt nur diese. Log `data/live_log.jsonl`, State `data/live_state.json` (das Dashboard zeigt `live_*` automatisch als LIVE).
   - Kraken-Schlüssel nur mit Rechten „Orders erstellen/ändern", „Guthaben abfragen", „Orders abfragen". **Niemals Auszahlungsrecht.** Nutzer legt ihn selbst an. Höchstens 20 € einzahlen.
   - Tests mit simulierten HTTP-Antworten (Signatur, Probelauf sendet nichts, 20-€-Grenze, Long-only, OrderSkipped, Notaus bei unklarem Status, Stop-Loss, Schließen scheitert und wird wiederholt).
   - Reihenfolge beim ersten Lauf: erst Probelauf mehrere Stunden, dann nur nach ausdrücklichem „scharf" des Nutzers.
   - Behaupte nie, der Live-Pfad sei getestet, solange er nur mit simulierten Antworten und `validate=true` geprüft wurde.

## Bekannte Lücken
- Kraken-Private-API und Orderausführung sind **ungetestet gegen ein echtes Konto**.
- Funding/Open Interest und Makrodaten fehlen (Binance-Futures war aus der Cloud geblockt).
- Eskalationen (Konfidenz < 0.60) führen bisher nur zu „nicht handeln"; eine BRAIN-Neubewertung ist nicht verdrahtet.
- Das Log enthält nur die Entscheidung, nicht die Jev-Rohantwort.
- Kosten: Kraken ca. 0,25–0,4 % je Order; bei 4–10 €-Positionen fressen Gebühren viel.

## Erste Handlung
Lies README.md. Frage den Nutzer, womit er anfangen will (Empfehlung: Aufgabe 1, Dashboard aufs iPhone), und gehe dann Schritt für Schritt vor.
