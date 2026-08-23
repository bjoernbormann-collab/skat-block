# CompoLog – Datenmodell zur Freigabe

Stand: Schritt 1 (Projektgerüst, Datenmodell, Migrationen, Auth, Grundlayout)
und Schritt 2 (Modul 1 – Artikelverwaltung / PIM) sind umgesetzt.

Das Modell deckt **alle acht Module** ab, nicht nur die bereits implementierten.
Das ist Absicht: Alembic läuft ab dem ersten Commit, und ein Schema, das die
späteren Module nicht vorsieht, erzwingt genau die Migrationen, die man sich
sparen wollte. Implementiert – also mit Logik und Tests hinterlegt – ist bisher
nur, was unten unter „Was schon läuft" steht.

50 Tabellen. Die Übersicht ist nach Modulen sortiert.

---

## Grundsatzentscheidungen

Diese vier Punkte sind später teuer zu ändern. Bitte gezielt prüfen.

### 1. Geldbeträge werden als skalierte Ganzzahlen gespeichert

`19,99 €` steht als `199900` in der Datenbank (Faktor 10 000, also vier
Nachkommastellen). Grund: SQLite kennt keinen Dezimaltyp. SQLAlchemys `Numeric()`
läuft dort über ein C-`double` – also genau die stille Cent-Drift, die man auf
einer Rechnung nicht gebrauchen kann.

Der Typ (`app/models/base.py`, `ExactDecimal`) **lehnt Floats aktiv ab** und
wirft eine Exception, statt zu runden. Ein `float` in einer Preisspalte ist damit
kein schleichender Fehler mehr, sondern ein sofortiger Absturz beim Schreiben.

Nebeneffekt, der gefällt: `SUM()` und `AVG()` funktionieren in reinem SQL weiter,
und beim Umzug auf PostgreSQL ändert sich an der Speicherung nichts – die
Migration bleibt ein Zeilenwechsel in der `.env`, keine Datenkonvertierung.

**Zu entscheiden:** vier Nachkommastellen. Bei Nettopreisen einzelner Positionen
sind zwei zu wenig (0,0825 € kommt bei Kleinteilen vor), vier reichen bequem.

### 2. Mengen sind Dezimalzahlen mit drei Nachkommastellen

**Entschieden: Meterware kommt mittelfristig, also jetzt umgestellt.**

Steckverbinder werden in Stück gehandelt – eine Ganzzahlspalte hätte heute
gereicht. Dezimal trotzdem, weil Meterware (Kabel, Schrumpfschlauch, Litze)
absehbar dazukommt und ein späteres Verbreitern bedeutet hätte, Bestandsjournal,
Reservierungen, alle Bestellungen und alle ausgestellten Belege gleichzeitig zu
migrieren – auf Echtdaten, mit einem Belegzusammenhang, der stimmen muss.

Drei Nachkommastellen decken Meter und Gramm ab. `packaging_unit` bildet die
Verpackungseinheit ab (1 lose, 25 für einen 25-m-Ring).

**Eine Ausnahme, absichtlich:** `ebay_listings.last_pushed_quantity` und
`channel_quantity` bleiben Ganzzahlen. Die eBay Inventory API nimmt nur ganze
Zahlen, und der Client rundet an der Grenze **ab** – 2,7 m als „3" anzubieten
wäre Überverkauf. Der Kommentar steht an der Spalte, damit das niemand
„aufräumt".

### 3. Der Bestand ist ein unveränderliches Journal, der Bestandssatz nur Cache

`stock_movements` ist die Wahrheit und wird nur angehängt – die Tabelle hat
bewusst kein `updated_at`, und es wird im Service-Layer keine Update- oder
Delete-Methode dafür geben. Eine Fehlbuchung wird durch eine Gegenbuchung
korrigiert, wie in einem Kassenbuch.

`stock_levels` (Artikel × Lagerort) ist ein abgeleiteter Cache, der in derselben
Transaktion wie die Bewegung fortgeschrieben wird. Ein Test rechnet den Cache aus
dem Journal nach und vergleicht.

Warum überhaupt ein Cache: „verfügbarer Bestand" wird bei jedem Sync-Lauf, jedem
Bestellimport und jeder Listenansicht gelesen. Ein Journal mit einigen tausend
Zeilen pro Monat bei jedem dieser Zugriffe aufzusummieren ist der klassische Weg,
eine Warenwirtschaft nach einem Jahr langsam zu machen.

**Verfügbar = physischer Bestand − offene Reservierungen.** Reservierungen sind
eigene Zeilen (`stock_reservations`), nicht ein Zähler – so gibt eine stornierte
Bestellung exakt ihre eigene Reservierung frei, ohne Rechnerei auf einer
gemeinsamen Zahl.

### 4. Belege sind eingefrorene Kopien, keine Verweise

`document_lines` enthält Artikelnummer, Bezeichnung und Preis als Text-Kopie.
`article_id` steht daneben, wird aber nie gedruckt. Ebenso werden Adressen in die
Bestellung hinein kopiert (`addresses` gehört zu genau einer Bestellung), nicht
aus einer Kundentabelle referenziert.

Grund: Eine Rechnung muss in acht Jahren noch korrekt ausdrucken, auch wenn der
Artikel längst umbenannt und der Käufer umgezogen ist. Marktplatz-Käufer sind
außerdem kein CRM – es gibt keinen stabilen Kundenstamm, auf den man verweisen
könnte.

---

## Modul 1 – Artikelverwaltung / PIM

| Tabelle | Zweck |
|---|---|
| `articles` | Stammdaten, Preise, Maße, Zoll, Varianten |
| `article_images` | mehrere Bilder je Artikel, Sortierung, Hauptbild, eBay-URL-Cache |
| `product_groups` | eigene Warengruppen, tragen das eBay-Kategorie-Mapping |
| `manufacturers` | Hersteller (TE, Aptiv, Yazaki, Molex …) |
| `suppliers` | Lieferanten |
| `audit_log` | Änderungshistorie, **eine Zeile pro geändertem Feld** |

**Varianten:** ein `articles`-Satz mit `kind = parent` gruppiert Kinder mit
`kind = child`. Bestand wird ausschließlich auf `standalone` und `child` geführt;
der Elternartikel ist ein reiner Gruppierungssatz und wird auf eine eBay
*Inventory Item Group* abgebildet. `variant_axis` auf dem Elternsatz sagt, welche
technischen Attribute die Kinder unterscheiden.

**Titel ist auf 80 Zeichen begrenzt** – eBays Hartgrenze, auf DB-Ebene erzwungen,
damit ein schlampiger Import keinen Artikel anlegen kann, der sich nie
veröffentlichen lässt.

**Änderungshistorie:** eine Zeile pro Feld statt eines JSON-Diffs pro Datensatz.
Geschwätziger, aber „wer hat wann welches Feld von welchem auf welchen Wert
geändert" ist damit ein `SELECT` und keine Auswertung zur Lesezeit.

---

## Modul 1b – Automotive (das Alleinstellungsmerkmal)

| Tabelle | Zweck |
|---|---|
| `oe_numbers` | OE-Nummern, dedupliziert, mit normalisierter Suchform |
| `article_oe_numbers` | n:m Artikel ↔ OE-Nummer |
| `cross_references` | Wettbewerbs-/Aftermarket-Nummern |
| `attribute_definitions` | kontrolliertes Vokabular der technischen Attribute |
| `article_attributes` | Key-Value je Artikel, Text **und** Zahl |
| `vehicles` | Fahrzeugvarianten, dedupliziert |
| `article_fitments` | n:m Artikel ↔ Fahrzeug, mit Einschränkungshinweis |

**OE-Nummern haben eine eigene Tabelle**, weil eine OE-Nummer regelmäßig auf
mehrere unserer Artikel zeigt (Gehäuse einzeln *und* als Reparatursatz) – und
umgekehrt genauso. `normalised` entfernt Leerzeichen, Punkte und Striche und
schreibt groß, damit die Suche nach `1J0 973 722` auch `1J0973722` findet.
**Gesucht wird immer auf dieser Spalte.**

**Technische Attribute laufen über ein kontrolliertes Vokabular**
(`attribute_definitions`). Freie Schlüssel werden binnen zwei Wochen zu
„Polzahl", „Pol-Zahl" und „Anzahl Pole", und danach funktioniert die automatische
Item-Specifics-Zuordnung nicht mehr. Jeder Attributschlüssel muss deshalb vorher
angelegt sein; zehn Definitionen sind bereits geseedet.

`article_attributes` hält Text **und** Zahl: der Text wird gedruckt und an eBay
geschickt, die Zahl macht „Rastermaß zwischen 2 und 3 mm" später zu einem
brauchbaren Filter.

**Baujahre stehen als `JJJJMM`-Ganzzahl** (`200403`), weil deutsche
Fahrzeugdaten monatsgenau sind („ab 03/2004") und ein `DATE` einen Tag
vortäuschen würde, den wir nicht haben. `ebay_epid` und `ktype` cachen die
eBay-Fahrzeugkennung nach dem ersten erfolgreichen Compatibility-Push.

---

## Modul 2 – eBay

| Tabelle | Zweck |
|---|---|
| `ebay_credentials` | OAuth-Tokens, verschlüsselt, je Umgebung |
| `ebay_listings` | lokales Abbild eines Angebots: Item + Offer + zuletzt gepushte Werte |
| `ebay_category_mappings` | Warengruppe → Kategorie, plus gecachte Pflicht-Aspekte |
| `listing_templates` | HTML-Beschreibungsvorlage mit Platzhaltern |
| `ebay_api_calls` | vollständiges Protokoll jedes HTTP-Calls |
| `ebay_rate_limits` | Kontingente je Ressource für das Dashboard |
| `sync_tasks` | Retry-Queue mit exponentiellem Backoff |

**Inventory Item und Offer sind getrennte Objekte** mit getrennten Lebenszyklen –
deshalb getrennte Spalten und nicht eine „Listing-ID". Das Inventory Item wird
über die SKU adressiert, hat also gar keine eigene ID; nur ein Flag sagt, dass es
existiert.

**`last_pushed_price` / `last_pushed_quantity`** sind der Änderungsdetektor des
Sync-Jobs: damit lässt sich „nichts geändert" von „Push fehlgeschlagen"
unterscheiden, ohne die API zu fragen.

**Client-ID und Secret bleiben in der `.env`.** In der Datenbank liegen nur die
*User*-Tokens, die erst nach interaktiver Zustimmung entstehen und deshalb in
keine Konfigurationsdatei können – verschlüsselt mit einem aus `SECRET_KEY`
abgeleiteten Schlüssel.

> **Warnung, bitte ernst nehmen:** Wer Datenbank **und** `.env` hat, hat alles.
> Die `.env` darf deshalb nicht in ein Backup, das das Haus verlässt. Das Backup
> nimmt sie bewusst nicht mit.

> **Zweite Warnung:** eBay-Refresh-Tokens laufen nach rund 18 Monaten ab und
> lassen sich **nicht** automatisch erneuern – es braucht eine neue interaktive
> Zustimmung. Läuft das unbemerkt ab, steht der Sync still.
> `refresh_token_expires_at` existiert genau dafür; die Vorwarnung gehört ins
> Dashboard.

---

## Modul 3 – Lager

| Tabelle | Zweck |
|---|---|
| `storage_locations` | Regal/Fach/Box, frei benennbar, mit `pick_sequence` für den Laufweg |
| `stock_levels` | Cache: Menge je Artikel × Lagerort |
| `stock_movements` | **unveränderliches Journal** |
| `stock_reservations` | offene Reservierungen aus Bestellungen |
| `purchase_orders` / `_lines` | Lieferantenbestellungen, Teillieferungen möglich |
| `stocktakes` / `_lines` | Inventur mit Soll-Schnappschuss |

`stock_movements.quantity` ist **vorzeichenbehaftet** (+50 Wareneingang, −3
Verkauf), damit `SUM()` über das Journal etwas bedeutet. `quantity_after` steht
bewusst redundant daneben: so ist das Journal für sich prüfbar, ohne es
nachzuspielen.

`reference_type` / `reference_id` zeigen absichtlich lose auf den auslösenden
Beleg. Ein harter Fremdschlüssel je Quelle wären sechs nullable Spalten und eine
neue Migration pro Belegart.

`is_sellable = false` auf einem Lagerort (Wareneingangszone, Retourenplatz)
nimmt dessen Bestand aus dem verfügbaren Bestand heraus.

Die Inventur speichert in `quantity_expected` den **Soll-Stand zum Zeitpunkt der
Zähllistenerzeugung** – die Differenz muss gegen das gerechnet werden, was das
System *damals* glaubte, nicht gegen den Stand beim Abschluss.

---

## Modul 4 – Aufträge

| Tabelle | Zweck |
|---|---|
| `sales_channels` | ein Satz je angebundenem Verkaufskonto |
| `orders` | Versandauftrag |
| `order_channel_references` | jede beitragende Marktplatz-Bestellnummer |
| `order_lines` | verkaufte Positionen |
| `addresses` | eingefrorene Adress-Schnappschüsse |
| `return_requests` / `return_lines` | Retouren |

**Kanal-agnostisch:** alles eBay-Spezifische steckt entweder in
`sales_channels` oder in `channel_*`-Spalten. Ein zweiter Kanal ist ein neuer
`sales_channels`-Satz plus ein Importer – keine Schemaänderung.

**Zusammenfassung mehrerer eBay-Transaktionen:** eBay liefert eine Bestellung pro
Transaktion. Mehrere desselben Käufers werden über `merge_group_key` zu **einer**
`orders`-Zeile zusammengefasst, damit einmal gepackt wird. Jede ursprüngliche
Bestellnummer bleibt in `order_channel_references` erhalten – die Trackingnummer
muss gegen **jede einzelne** zurückgemeldet werden, sonst fehlt sie bei der
Bewertung.

Der Unique-Index auf `(channel_id, channel_order_id)` macht den Import
idempotent: dieselbe eBay-Bestellung erneut zu importieren ist ein No-op statt
eines Duplikats.

**`order_lines.article_id` ist nullable.** Eine eBay-Bestellung kann für ein
Angebot eintreffen, das (noch) nicht mit einem PIM-Artikel verknüpft ist. So eine
Bestellung landet im Klärstatus, statt abgewiesen zu werden – eine Bestellung
wegen einer Zuordnungslücke zu verlieren ist der schlimmste denkbare Fehlerfall.

**`order_lines.unit_cost_net`** friert die Einstandskosten zum Verkaufszeitpunkt
ein, damit sich die Margenauswertung nicht rückwirkend ändert, wenn der
Durchschnittseinkaufspreis wandert.

---

## Modul 5 – Kommissionierung

| Tabelle | Zweck |
|---|---|
| `pick_lists` | ein Kommissionierlauf |
| `pick_list_orders` | n:m Pickliste ↔ Bestellung (Batch-Picking) |
| `pick_lines` | eine Position: Artikel × Lagerort |

`pick_lines.sort_order` wird bei der Erzeugung aus
`storage_locations.pick_sequence` vorberechnet – so können PDF und mobile Ansicht
sich nicht über den Laufweg uneinig sein.

`scan_confirmed` / `scanned_code` belegen, dass der Scanner und nicht der Daumen
die Position bestätigt hat. Fehlmengen laufen über `status = short` plus
`short_reason` und setzen die Bestellung in den Klärstatus.

---

## Modul 6 – Belege (GoBD)

| Tabelle | Zweck |
|---|---|
| `number_ranges` | lückenlose Zähler, ein Satz je (Code, Periode) |
| `documents` | ausgestellter Beleg, nach `finalised_at` unveränderlich |
| `document_lines` | eingefrorene Positionen |

GoBD in drei Regeln, vom Schema getragen:

1. **Unveränderbarkeit** – `Document` und PDF werden einmal geschrieben. Es gibt
   keinen Update-Pfad. Korrekturen laufen über einen Storno-Beleg, der per
   `cancels_document_id` zurückzeigt.
2. **Nachvollziehbarkeit** – `pdf_sha256` macht eine spätere Änderung der Datei
   auf der Platte erkennbar.
3. **Vollständigkeit** – die Nummernkreise sind lückenlos (siehe unten).

`issuer_snapshot` speichert Firmierung und USt-IdNr. **zum Ausstellungszeitpunkt**
als JSON. Wer umzieht, darf damit keine Altrechnung verändern.

### Die Nummernkreise – bereits implementiert und getestet

Zwei naheliegende Umsetzungen scheitern beide:

* `SELECT max(nummer)+1` – zwei gleichzeitige Schreiber lesen dasselbe Maximum.
* Die Nummer in einer eigenen kurzen Transaktion ziehen – schlägt das Schreiben
  des Belegs danach fehl, ist die Nummer verbrannt und es entsteht eine Lücke.

Was funktioniert: ein Zählersatz, der per atomarem `UPDATE` **innerhalb der
Transaktion des Aufrufers** hochgezählt wird, und der Beleg in derselben
Transaktion:

```python
with session_scope() as db:                 # eine Transaktion
    nummer = next_number(db, "invoice")     # nimmt eine Zeilensperre
    db.add(Document(number=nummer, ...))    # dieselbe Transaktion
# Commit – Nummer und Beleg erscheinen zusammen, oder gar nicht
```

Das `UPDATE` hält die Sperre bis zum COMMIT, ein zweiter Schreiber wartet also,
statt zu duplizieren. Bei einem Rollback rollt der Zähler mit zurück – es wird
keine Nummer verbraucht. Genau das prüft
`tests/test_numbering.py::test_rollback_consumes_no_number`.

**Der Preis:** die Belegerstellung wird serialisiert. Bewusst so gewählt – bei
einigen Dutzend Belegen am Tag wird die Sperre Millisekunden gehalten, und ein
lückenloser Nummernkreis ist deutlich mehr wert als der Durchsatz.

Neun Nummernkreise sind angelegt: Rechnung, Gutschrift, Storno, Lieferschein,
Auftrag, Lieferantenbestellung, Retoure, Pickliste, SKU. Alle mit Jahresreset
außer der SKU, die niemals zurückgesetzt wird.

---

## Modul 7 – Versand

| Tabelle | Zweck |
|---|---|
| `carriers` | DHL heute, DPD/GLS später |
| `shipping_products` | DHL Paket, Warenpost, Kleinpaket … |
| `shipments` | ein Paket; eine Bestellung kann mehrere haben |
| `shipment_lines` | welche Positionen in welchem Paket |

`reported_to_channel_at`, `channel_fulfillment_id` und `channel_report_error`
verfolgen die Rückmeldung an eBay **explizit**, statt sie nach einem
erfolgreichen Call anzunehmen. Die Trackingnummer ist bewertungsrelevant; ein
stillschweigend verlorener Rückmeldeversuch ist genau das, was man nicht merkt.

---

## Modul 8 – Auswertung

| Tabelle | Zweck |
|---|---|
| `fee_rules` | Gebührenmodell, mit Gültigkeitszeitraum |
| `order_fees` | tatsächliche Gebühr je Bestellung |
| `tax_rates` | USt-Sätze je Land (OSS-Vorbereitung) |
| `accounting_exports` | Protokoll der Übergaben an den Steuerberater |

`fee_rules` bildet die 2026er Struktur ab – fixer Betrag plus Prozentsatz, je
Kategorie, mit Deckel. Alle vier Bestandteile sind Felder, damit eine
Gebührenänderung eine Formulareingabe ist und keine Code-Änderung.
`valid_from` / `valid_to` halten Altbestellungen mit den damals gültigen Regeln
bewertet.

`order_fees.is_estimated` unterscheidet den bei Import gerechneten Schätzwert vom
später aus den eBay-Transaktionsdaten gezogenen Istwert. Beide bleiben stehen –
die Differenz ist es wert, gesehen zu werden.

---

## Was schon läuft

**Schritt 1 – Fundament**
* Datenmodell und Migration (`alembic upgrade head` erzeugt alle 50 Tabellen)
* Nummernkreise inkl. Transaktionssicherheit
* Anmeldung, Sessions, Sperre nach Fehlversuchen, zwei Rollen
* Exakte Dezimalarithmetik, Änderungshistorie, Backup mit Prüfsummen
* Strukturiertes JSON-Logging, getrennt nach Anwendung und API-Verkehr
* APScheduler mit Backup- und Session-Aufräumjob
* Deutsche Fehlerseiten, auch für HTMX-Fragmente

**Schritt 2 – Modul 1 (PIM)**
* Artikel anlegen, bearbeiten, deaktivieren (nie löschen)
* SKU-Vergabe aus dem Nummernkreis
* Volltextsuche über SKU, Titel, MPN, EAN, OE-Nummer und Querverweis,
  mit HTMX-Livesuche und Paginierung
* Duplikaterkennung über normalisierte MPN und OE-Nummer – warnt, blockiert
  nicht, und lässt sich bewusst übergehen
* Varianten mit erzwungenen Regeln (Eltern trägt keinen Bestand, Kind braucht
  Eltern, Eltern mit Kindern lässt sich nicht degradieren)
* OE-Nummern und Querverweise, normalisiert und dedupliziert
* Bilder: Upload, Hauptbild, Reihenfolge, Löschen; Format aus den Magic Bytes
  statt aus dem Content-Type; Auslieferung nur an Angemeldete
* Import XLSX/CSV mit Spaltenvorschlag, **Probelauf als Standard**,
  Einzelfehler-Report je Zeile, Alles-oder-nichts bei Fehlern
* Export XLSX/CSV, das sich unverändert wieder importieren lässt
* Änderungshistorie je Feld, in der Detailansicht sichtbar

**160 Tests, alle grün. Ruff sauber.**

## Was ausdrücklich noch nicht existiert

Nichts davon ist als Platzhalter getarnt – die Tabellen sind da, die Logik nicht:

* Technische Attribute und Fitment über die Oberfläche pflegen (Modell und
  Anzeige stehen, das Bearbeitungsformular fehlt)
* Der komplette eBay-Client (Modul 2)
* Bestandsbuchungen, Wareneingang, Inventur (Modul 3) – die Artikeldetailseite
  sagt das an der Stelle, wo sonst Zahlen stünden, ausdrücklich
* Bestellimport, Status-Workflow, Retouren (Modul 4)
* Picklisten, Scan-Ansicht (Modul 5)
* PDF-Erzeugung, ZUGFeRD (Modul 6 – die Nummernkreise stehen bereits)
* DHL-Anbindung (Modul 7)
* Auswertungen, DATEV-Export (Modul 8)

`app/scheduler.py` kennzeichnet seine Lücken mit `STUB NOTICE`;
`app/services/backup.py` wirft für PostgreSQL `NotImplementedError` mit
Klartext, statt still nichts zu tun.
