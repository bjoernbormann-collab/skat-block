# Dashboard als App auf dem Handy (privat, über Tailscale)

Das Dashboard bleibt **privat**: Es lauscht weiter nur auf dem Server selbst (127.0.0.1). Tailscale baut ein privates Netz
nur zwischen deinen Geräten (Server + Handy + Mac) und liefert die Seite darin über HTTPS aus. Ohne Tailscale-Anmeldung
kommt niemand an die Seite. **Nie `tailscale funnel` benutzen** (das würde sie öffentlich ins Internet stellen).

## 1. Tailscale-Konto
Auf https://tailscale.com ein kostenloses Konto anlegen (Anmeldung mit Google/Apple/Microsoft). Das machst du selbst im Browser.

## 2. Auf dem Server (SSH, `ubuntu@tradingagent:~$`)
```
cd ~/skat-block && git pull
sudo systemctl restart tradingagent-dashboard
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
`tailscale up` zeigt eine **Internetadresse (URL)**. Öffne sie auf deinem Mac oder Handy im Browser und melde den Server in deinem Tailscale-Konto an.
Danach in der Tailscale-Verwaltung (https://login.tailscale.com/admin/dns) prüfen, dass **MagicDNS** und **HTTPS Certificates** aktiviert sind
(ein Knopf "Enable HTTPS"). Dann:
```
sudo tailscale serve --bg --https=443 localhost:8000
tailscale serve status
```
`serve status` zeigt eine Adresse wie `https://tradingagent.<dein-netz>.ts.net`. Fragt der Befehl nach HTTPS-Freigabe und zeigt eine URL,
öffne diese und bestätige, dann den Befehl wiederholen.

## 3. Auf dem Handy
1. App **Tailscale** installieren (App Store / Play Store), mit **demselben Konto** anmelden, VPN-Erlaubnis bestätigen.
2. Im Browser die Adresse `https://tradingagent.<dein-netz>.ts.net` öffnen. Das Dashboard erscheint.
3. **Als App installieren:**
   - iPhone: in **Safari** auf Teilen (Quadrat mit Pfeil) -> **Zum Home-Bildschirm**.
   - Android: in **Chrome** Menü (drei Punkte) -> **App installieren** (oder "Zum Startbildschirm").
4. Die App "Trading" startet jetzt wie eine normale App im Vollbild. Tailscale muss dabei verbunden sein (läuft meist im Hintergrund).

## Ausschalten / Kontrolle
```
tailscale serve status                 # was ist freigegeben
sudo tailscale serve --https=443 off   # Freigabe beenden
sudo tailscale down                    # Server vom privaten Netz trennen
```
Geräte kannst du jederzeit in https://login.tailscale.com/admin/machines entfernen.

## Grenzen
- Die App ist nur eine Ansicht (lesend). Sie kann nichts kaufen oder verkaufen und hat keine Push-Benachrichtigungen.
- Ohne Verbindung zeigt sie nur die leere Hülle und eine Fehlermeldung: Zahlen werden absichtlich nie zwischengespeichert.
- Die Tailscale-Befehle habe ich in der offiziellen Dokumentation nachgesehen, aber nicht auf deinem Server ausgeführt.
