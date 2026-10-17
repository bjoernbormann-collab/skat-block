# Setup auf Oracle Cloud (Always Free), Ubuntu

Paper-Trading, es werden keine echten Orders gesendet. **Nur eine Instanz betreiben** (Oracle ODER Mac mini), sonst gibt es zwei getrennte Paper-Konten mit verwirrenden Ergebnissen.

## 0. Wichtig: Oracle kann ungenutzte Always-Free-Instanzen einziehen
Nach Oracles Bedingungen (aus dem Gedächtnis, bitte aktuell prüfen) werden Always-Free-Instanzen als "idle" gestoppt/zurückgefordert, wenn über 7 Tage CPU, Netzwerk und Speicher dauerhaft sehr niedrig sind (unter ca. 20 %). Dieser Agent ist fast immer im Leerlauf. Gegenmittel: das Konto auf **Pay As You Go** hochstufen. Solange du nur Always-Free-Ressourcen nutzt, kostet das nichts, und die Idle-Rückforderung betrifft dich dann nach Oracles Angaben nicht. Das ist deine Entscheidung (Kreditkarte nötig); prüfe vorher die aktuellen Oracle-Bedingungen.

## 1. Instanz
Region Frankfurt (oder nah). Image Ubuntu 22.04/24.04. Shape: VM.Standard.A1.Flex (1 OCPU / 6 GB reicht) oder VM.Standard.E2.1.Micro. SSH-Key hinterlegen, nur Port 22 offen lassen (eingehend nichts weiter nötig, der Agent ruft nur nach außen).

## 2. Installieren
```
ssh ubuntu@<IP>
sudo apt update && sudo apt install -y python3-pip git
git clone https://github.com/bjoernbormann-collab/skat-block.git && cd skat-block && git checkout claude/new-session-1od9nf
cd trading-agent && python3 -m unittest discover -s tests      # erwartet: OK (27 Tests)
```
## 3. Erreichbarkeit prüfen (wichtig, nicht vorab getestet)
```
curl -s "https://api.kraken.com/0/public/Time"
```
Muss JSON mit "error":[] liefern. Kommt ein Fehler oder eine Sperrseite, blockt Kraken diese Oracle-IP/Region; dann Region wechseln oder den Mac mini nehmen.

## 4. Claude-Anbindung testen, dann Dienst
```
sudo pip3 install anthropic --break-system-packages    # oder: python3 -m venv .venv && .venv/bin/pip install anthropic (dann ExecStart anpassen)
sudo sh -c 'echo "ANTHROPIC_API_KEY=sk-ant-..." > /etc/tradingagent.env' && sudo chmod 600 /etc/tradingagent.env
set -a; . /etc/tradingagent.env; set +a
python3 tools/run_paper.py --jev claude --interval 20 --horizon 60     # ~2 Min, dann Ctrl+C; im Log nach "jev_error" suchen
rm -f data/paper_state.json data/paper_log.jsonl
sudo cp deploy/tradingagent.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now tradingagent
journalctl -u tradingagent -f
```
## 5. Auswerten (nach >= 28 Tagen)
`cd ~/skat-block/trading-agent && python3 tools/evaluate_paper.py`

## Sicherheit
Firewall nur SSH, Schlüsselanmeldung, kein Passwort-Login. Der API-Schlüssel nur in /etc/tradingagent.env. Setze in der Anthropic-Console ein Ausgabenlimit.
