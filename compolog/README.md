# CompoLog

Selbst gehostete Warenwirtschaft für den eBay-Handel mit Automotive-Steckverbindern.

Läuft lokal auf einem Mac mini, optional per Cloudflare Tunnel vom iPhone
erreichbar. Kein SaaS außer den APIs, die zwingend nötig sind (eBay, DHL).

**Ausbaustand:** Schritt 1 (Fundament) und Schritt 2 (Modul 1 – Artikelverwaltung
inklusive Import/Export) sind fertig. Details und die Begründung der
Modellentscheidungen stehen in [DATENMODELL.md](DATENMODELL.md).

---

## Installation

Vorausgesetzt ist Python 3.11 oder neuer (getestet mit 3.11; die
Projektbeschreibung nennt 3.12+, der Code läuft ab 3.11).

```bash
cd compolog
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# SECRET_KEY erzeugen und in die .env eintragen:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Firmendaten in der `.env` ausfüllen – sie stehen später auf jeder Rechnung und
sind nach §14 UStG Pflichtangaben.

Dann Schema anlegen, Grunddaten einspielen, Benutzer erstellen:

```bash
alembic upgrade head
python -m app.cli seed          # Nummernkreise, Attribute, Lagerorte (idempotent)
python -m app.cli create-user admin --role admin
```

Starten:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

→ http://127.0.0.1:8000

---

## Kommandos

| Befehl | Zweck |
|---|---|
| `alembic upgrade head` | Schema auf den aktuellen Stand bringen |
| `alembic revision --autogenerate -m "…"` | Migration aus Modelländerungen erzeugen |
| `python -m app.cli seed` | Grunddaten anlegen, beliebig oft wiederholbar |
| `python -m app.cli create-user NAME --role admin\|warehouse` | Benutzer anlegen |
| `python -m app.cli backup` | Backup sofort ausführen |
| `pytest` | Testsuite |
| `ruff check app tests` | Linter |

---

## Projektstruktur

```
compolog/
├── alembic/              Migrationen (ab dem ersten Commit, keine Handarbeit am Schema)
├── app/
│   ├── config.py         Settings-Klasse – alles aus .env, nichts hartkodiert
│   ├── services/
│   │   ├── numbering.py  lückenlose Nummernkreise (transaktionssicher)
│   │   ├── articles.py   Artikellogik: SKU, Varianten, Duplikate, Suche
│   │   ├── images.py     Bildablage auf der Platte
│   │   └── importexport.py  XLSX/CSV mit Spaltenmapping
│   ├── db.py             Engine, Session, SQLite-PRAGMAs
│   ├── security.py       bcrypt, serverseitige Sessions, Login-Sperre
│   ├── errors.py         deutsche Fehlerseiten, keine Stacktraces für Nutzer
│   ├── logging_config.py JSON-Logging, rotierend, App und API getrennt
│   ├── scheduler.py      APScheduler – Backup, Session-Aufräumen (eBay-Jobs folgen)
│   ├── cli.py            Verwaltungsbefehle
│   ├── models/           ORM, nach Modulen getrennt
│   └── web/              Routen, Jinja2-Templates, statische Dateien
├── data/                 Datenbank, Bilder, Belege, Backups, Logs (nicht im Git)
└── tests/
```

---

## Betrieb

### Als Dienst auf dem Mac mini

`launchd` statt `nohup`, damit der Dienst einen Neustart übersteht. Eine
`~/Library/LaunchAgents/de.compolog.app.plist` mit `KeepAlive` und
`WorkingDirectory` auf dieses Verzeichnis reicht.

### Erreichbarkeit von außen

Beim Betrieb hinter einem Cloudflare Tunnel unbedingt setzen:

```
SESSION_COOKIE_SECURE=true
TRUSTED_HOSTS=compolog.deine-domain.de
```

Ohne `TRUSTED_HOSTS` nimmt die App jeden `Host`-Header an. Der Tunnel selbst
sollte zusätzlich über Cloudflare Access abgesichert werden – die
Anwendungsanmeldung ist eine einfache Session-Anmeldung und nicht dafür gebaut,
allein im offenen Internet zu stehen.

### Backups

Der Scheduler legt täglich zur konfigurierten Stunde unter `data/backups/`
ein Verzeichnis mit Datenbank-Dump, `documents.tar.gz`, `images.tar.gz` und
einer `SHA256SUMS` an.

Die Datenbank wird über SQLites eigene Backup-API kopiert, nicht per `cp`. Ein
Dateikopie einer laufenden WAL-Datenbank kann einen zerrissenen, nicht mehr
öffnenbaren Schnappschuss ergeben – was man am Tag merkt, an dem man ihn braucht.

**Die `.env` liegt bewusst nicht im Backup.** Sie enthält den Schlüssel, mit dem
die eBay-Tokens verschlüsselt sind; wer Backup und `.env` zusammen hat, hat
Vollzugriff auf das Verkäuferkonto. Die `.env` gehört in einen Passwortmanager.

Ein Backup, das nie zurückgespielt wurde, ist ein Gerücht. Bitte einmal probieren.

### PostgreSQL statt SQLite

Nur die `DATABASE_URL` ändern:

```
DATABASE_URL=postgresql+psycopg://compolog:passwort@localhost/compolog
```

Modelle und Migrationen sind dafür geschrieben. **Achtung:**
`app/services/backup.py` kann bislang nur SQLite und wirft für PostgreSQL
bewusst `NotImplementedError` statt still nichts zu tun – `pg_dump` muss dann
eingebunden werden.

### Tailwind produktiv bauen

Aktuell liegt Tailwinds In-Browser-JIT-Build unter
`app/web/static/js/tailwind.js`. Der braucht keine Toolchain – deshalb ist er
da –, kompiliert die Styles aber bei jedem Seitenaufruf neu.

Sobald Node verfügbar ist:

```bash
npm install
npm run build:css       # bzw. npm run watch:css beim Entwickeln
```

Danach in `app/web/templates/layout/base.html` die `tailwind.js`-Zeile
entfernen. Die Warenhaus-Ansichten auf dem Handy danken es.

---

## Artikelverwaltung (Modul 1)

Unter **Artikel** liegen Suche, Anlage, Bearbeitung und Import/Export.

* **Suche** geht über Artikelnummer, Titel, Herstellerteilenummer, EAN,
  OE-Nummer und Querverweis. OE-Nummern werden normalisiert – „1J0 973 722"
  findet auch „1J0973722" und umgekehrt.
* **Doppelanlage** wird beim Speichern geprüft (MPN und OE-Nummer). Es wird
  gewarnt, nicht blockiert: zwei verschiedene Teile können dieselbe OE-Nummer
  tragen. Der Hinweis lässt sich mit einem Klick übergehen.
* **Varianten**: ein Elternartikel gruppiert, Bestand läuft ausschließlich über
  die Kinder. Die Regeln werden erzwungen, nicht nur dokumentiert.
* **Bilder** werden am Dateiinhalt erkannt, nicht an der Endung, und nur an
  angemeldete Nutzer ausgeliefert. Dasselbe Bild zweimal hochzuladen erzeugt
  keinen zweiten Datensatz.
* **Import**: XLSX oder CSV, Spalten werden anhand der Überschriften
  vorgeschlagen. **Der erste Durchlauf ist immer ein Probelauf** – es wird
  nichts gespeichert, bevor der Bericht auf dem Bildschirm stand. Schlägt auch
  nur eine Zeile fehl, wird gar nichts übernommen; der Bericht nennt Zeile,
  Artikelnummer und Grund.
* **Export** erzeugt genau die Spaltenüberschriften, die der Import wieder
  erkennt. Exportieren, in Excel korrigieren, reimportieren funktioniert also,
  ohne dabei Felder zu verlieren.

Warengruppen werden beim Import **nicht** automatisch angelegt: an einer
Warengruppe hängen die eBay-Kategorie und die Angebotsvorlage, und ein Tippfehler
würde Artikel erzeugen, die gut aussehen und sich nicht veröffentlichen lassen.
Hersteller und Lieferanten werden dagegen bei Bedarf angelegt.

Artikel werden **deaktiviert, nie gelöscht** – mit einem Artikel verschwänden
sein Bestandsjournal und seine Auftragshistorie, und beide müssen lesbar bleiben.

## Tests

```bash
pytest              # 160 Tests
pytest -q --tb=short
```

Die Suite baut das Schema **aus den Migrationen** auf, nicht per
`create_all()`. Eine fehlende oder kaputte Migration lässt damit die Tests
scheitern – genau der Fehler, der sonst erst auf der Produktivmaschine auffällt.

Getestet werden bisher: Nummernkreise (inkl. Rollback-Verhalten), exakte
Dezimalarithmetik, Passwort- und Session-Handling, Änderungshistorie,
Backup-Integrität, Modell-Invarianten, der Artikelservice (SKU-Vergabe,
Variantenregeln, Duplikaterkennung, Suche, Marge), Import und Export
einschließlich Rundlauf, Bildverwaltung sowie die Weboberfläche über HTTP.

---

## Rechtliche Hinweise

Weder der Autor dieses Codes noch dieses Dokument ersetzen einen Steuerberater.
Die folgenden Punkte sind trotzdem offensichtlich genug, um sie zu benennen.

**GoBD und Belegnummern.** Rechnungsnummern müssen lückenlos und eindeutig sein.
Die Umsetzung dafür steht (siehe DATENMODELL.md), aber sie funktioniert nur,
solange die Nummer in derselben Transaktion wie der Beleg gezogen wird. Wer
später eine Nummer „auf Vorrat" zieht, macht die Eigenschaft kaputt.

**Aufbewahrungsfrist.** Rechnungen unterliegen nach §147 AO einer zehnjährigen
Aufbewahrungspflicht. Die Backup-Rotation (`BACKUP_KEEP_DAYS`, Standard 30 Tage)
ist ausdrücklich **keine** Archivierung. Für die Belege braucht es eine separate,
langfristige Ablage.

**E-Rechnung.** Seit 2025 müssen inländische B2B-Rechnungen elektronisch
empfangen werden können; die Pflicht zum Versenden greift gestaffelt danach.
Für reines B2C-Geschäft über eBay ist das meist nicht relevant – sobald aber
Gewerbekunden dabei sind, wird es das. Das Datenmodell sieht ZUGFeRD/XRechnung
vor (`einvoice_xml_path`, `einvoice_profile`); erzeugt wird bisher nichts.
Bitte den konkreten Stichtag für die eigene Situation mit dem Steuerberater
klären, statt sich auf diese Zeile zu verlassen.

**Kleinunternehmer §19 UStG.** `SMALL_BUSINESS_SCHEME=true` ändert die gesamte
Steuerbehandlung: keine USt auf Rechnungen, dafür ein Pflichthinweis auf dem
Beleg. Wird die Grenze im Jahr überschritten, ändert sich das mitten im Jahr.
Bitte vor dem ersten Beleg richtig setzen.

**OSS und EU-Ausland.** Ab 10.000 € B2C-Umsatz in andere EU-Länder gilt der
Steuersatz des *Käuferlandes*, zu melden über das OSS-Verfahren. Die Tabelle
`tax_rates` ist die Vorbereitung; die Auswertung fehlt noch. eBay verkauft
grenzüberschreitend schneller, als man denkt – bitte im Blick behalten.

**Verpackungsgesetz / LUCID.** Wer verpackte Ware an Endverbraucher versendet,
muss bei LUCID registriert und an einem dualen System beteiligt sein. Betrifft
diese Software nicht, aber den Handel, den sie abbildet.

**OE-Nummern in Angeboten.** OE-Nummern dürfen zu Vergleichszwecken genannt
werden (§ 23 MarkenG), nicht aber so, dass ein Herkunftseindruck entsteht. Die
mitgelieferte Angebotsvorlage enthält deshalb einen entsprechenden Hinweis. Die
Vorlage ist als Ausgangspunkt gedacht, nicht als Rechtsberatung.

---

## Ehrliche Aufwandseinschätzung

Ein paar Anforderungen klingen kleiner, als sie sind:

**eBay Item Specifics** sind der Hauptgrund, warum Publish-Versuche scheitern.
Die Pflichtfelder unterscheiden sich je Kategorie, ändern sich ohne Ankündigung,
und die Fehlermeldungen sind selten hilfreich. Die Prüfung *vor* dem Publish
(wie gefordert) ist deshalb richtig – aber sie ist ein Modul für sich, kein
Nebenprodukt des Publish-Aufrufs.

**eBay Parts Compatibility** ist die aufwendigste Einzelfunktion der Liste. Die
Fahrzeugzuordnung will K-Type- bzw. ePID-Kennungen, die zu den eigenen
Fahrzeugdaten passen müssen. Ohne saubere Ausgangsdaten wird das eine lange
Fleißarbeit – unabhängig davon, wie gut der Code ist.

**ZUGFeRD/XRechnung** heißt PDF/A-3 mit eingebettetem, validem XML. PDF/A-3 ist
deutlich strenger als „ein PDF" (eingebettete Schriften, definierte Farbprofile,
Metadaten). Realistisch ist das ein eigener Arbeitsblock, kein Anhängsel an die
Rechnungserzeugung.

**Bestehende Angebote importieren** ist der heikelste Schritt der eBay-Anbindung,
weil dabei laufende Angebote im Spiel sind. Der Import muss zuerst rein lesend
laufen, das Ergebnis muss geprüft werden, und erst danach darf geschrieben
werden. Der Sandbox-Schalter (`EBAY_SANDBOX`) existiert genau dafür.

**Der DHL-Geschäftskundenversand** braucht einen Vertrag mit freigeschalteter
API und eine eigene Abnahme. Das ist kein Code-Problem, aber es dauert – bitte
früh anstoßen, nicht erst wenn Modul 7 dran ist.
