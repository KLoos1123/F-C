# Subsidiemarkt Monitor

Kopie van het [Scrappingtool-v2](https://github.com/KLoos1123/Scrappingtool-v2)
tender-scraping-patroon (Python + Playwright/requests + SQLite + GitHub
Actions), toegepast op een nieuwe markt: interim-/freelance-/zzp-opdrachten
die vragen om subsidie-expertise (subsidieadvies, -management, -verwerving,
-administratie, staatssteun) of aanpalende financial-control-/compliance-
expertise (financial/business control, accounting, audit, reporting,
programma-/project control).

Doel: de vraagkant van die markt in beeld brengen ("hoeveel van dit soort
opdrachten verschijnen waar, hoe vaak, met welke deadlines") zodat Profource
die markt kan volgen/voorspellen. De matching van die opdrachten met
beschikbare cv's is een apart vervolgtraject van het AI-team en valt buiten
dit tool.

## Hoe het werkt

```
scrapers/*.py  (13 platformen hergebruikt uit Scrappingtool-v2, + opdrachtoverheid.nl)
  │  run.py    - draait elke scraper, een gecrashte bron stopt de rest niet
  ▼
Ruwe opdrachten (bron, tender_id, titel, organisatie, status, deadline, ...)
  │  classificatie.py  - trefwoordherkenning op titel + omschrijving
  ▼
Getagde opdrachten (subsidie_relevant, subsidie_categorieen, subsidie_score)
  │  db.py     - SQLite, dedupliceert op (bron, tender_id), houdt eerst_gezien/laatst_gezien bij
  ▼
tenders.db  ──►  dashboard.py  ──►  web/index.html (GitHub Pages)
```

Net als bij de MKB-scraper (het andere "kopie"-project) worden `tenders.db`
en de `web/*.json`-exports gecommit in deze (private) repo: dat geeft
historie via `git log`/`git diff` in plaats van afhankelijkheid van
Actions-cache/artifact-retentie, en het dashboard werkt zonder server of
login (open `web/index.html` lokaal, of de GitHub Pages-URL na de eerste
run).

## Bronnen

Hergebruikt (ongewijzigd) uit Scrappingtool-v2: Mercell, Flextender, Hero,
Striive, freelance.nl, NS, Stedin, Stedin-VMS, TenderNed, Inhuurdesk Regio
(Noord-Holland Noord / Noordoost-Brabant / Zuidoost-Brabant), Werken in
Gelderland, FlexWestBrabant, Magnit.

Nieuw: `scrapers/opdrachtoverheid.py` (opdrachtoverheid.nl). **Let op:** dit
platform is een Nuxt/Pinia-SPA; het exacte lijst-endpoint kon niet worden
vastgesteld door de JS statisch te lezen (geen browserverkeer mogelijk vanuit
de omgeving waarin dit gebouwd is). De scraper onderschept daarom het
live netwerkverkeer op de homepage, net als `magnit.py` al deed voor Magnit.
Dit is dus een best-effort eerste versie -- controleer de eerste paar
Actions-runs (of `debug_opdrachtoverheid.png` bij een mislukte run) en verfijn
zo nodig de veldherkenning in `VELD_KANDIDATEN`.

**Nog niet gebouwd:** een vierde genoemde bron, "tendernet" -- er bestaat
geen `tendernet.nl` (resolvet niet) en `tendernet.eu` lijkt een geparkeerd/
niet-gerelateerd domein (certificaat hoort niet bij die naam). Waarschijnlijk
bedoeld is TenderNed (al aanwezig) of een ander platform onder een andere
naam -- graag de juiste URL bevestigen, dan volgt de scraper in dezelfde
structuur.

## Classificatie

`classificatie.py` matcht (case-insensitive, op substring) tegen de lijst die
Profource tot nu toe handmatig gebruikte:

- **Subsidies**: subsidieadvies, subsidiemanagement, subsidieverwerving,
  subsidieadministratie, subsidierapportage, staatssteun, + de generieke stam
  "subsidie(s)" (dekt functietitels als "-adviseur"/"-manager" die met de
  exacte brontermen zelf niet zouden matchen)
- **Financial & Business Control**: financial control, business control,
  accounting, financiële administratie, financiële verantwoording,
  financiële procesverbetering
- **Compliance & Audit**: compliance, audit(s)
- **Programma- & Projectcontrol**: programmamanagement/-manager, project
  control
- **Reporting**: reporting

Een opdracht is "relevant" zodra één trefwoord matcht in titel of
omschrijving (titel-matches wegen zwaarder mee in de score). Niet-relevante
opdrachten worden niet weggegooid, alleen niet standaard getoond in het
dashboard (checkbox "Toon ook niet-relevante") -- zo kun je de trefwoordenlijst
later bijstellen zonder historie te verliezen. Pas de lijst aan in
`classificatie.py`; `tests/test_classificatie.py` pint het gedrag met een
paar regressietests (incl. de advies/adviseur-valkuil hierboven).

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
```

Login-vereisende bronnen (Mercell, Striive, Magnit, freelance.nl,
Stedin-VMS) hebben dezelfde secrets nodig als in Scrappingtool-v2 --
`MERCELL_EMAIL`/`MERCELL_WACHTWOORD`, `STRIIVE_EMAIL`/`STRIIVE_WACHTWOORD`,
`MAGNIT_EMAIL`/`MAGNIT_WACHTWOORD`, `FREELANCE_EMAIL`/`FREELANCE_WACHTWOORD`,
`STEDINVMS_EMAIL`/`STEDINVMS_WACHTWOORD` -- zet ze lokaal als omgevingsvariabele
en in **Settings → Secrets and variables → Actions** op deze repo (dit is een
aparte repo, dus de secrets van Scrappingtool-v2 worden niet automatisch
gedeeld; dezelfde inloggegevens hergebruiken kan gewoon). Ontbrekende secrets
laten die ene bron falen, niet de hele run (zie `MAX_MISLUKT` in `run.py`).

## Gebruik

```bash
python run.py
```

Draait alle scrapers, classificeert, slaat op in `tenders.db`, exporteert
`tenders.csv` / `tenders_nieuw.csv` / `tenders_subsidies.csv` en bouwt het
dashboard (`web/*.json`). Open `web/index.html` in een browser om te bekijken.

## Automatisering

`.github/workflows/scrape.yml` draait tweemaal daags (06:00 en 12:00 UTC) en
op handmatige trigger, committeert de bijgewerkte database + dashboard-data
terug, en publiceert `web/` naar GitHub Pages (**Settings → Pages → Source:
GitHub Actions** moet eenmalig aangezet worden).

## Dashboardschema

`tenders`-tabel (zie `db.py`): dezelfde basisvelden als Scrappingtool-v2
(bron, tender_id, titel, organisatie, status, deadline, publicatiedatum,
locatie, url, eerst_gezien, laatst_gezien) plus `subsidie_relevant`,
`subsidie_categorieen`, `subsidie_trefwoorden`, `subsidie_score`.
`beschrijvingen`-tabel: volledige omschrijvingen apart (dezelfde reden als in
Scrappingtool-v2 -- hoofdtabel licht houden, en input voor de latere
AI-matching met cv's).

## Tests

```bash
pip install pytest
pytest
```

Dekt vooralsnog alleen `classificatie.py` (de kernlogica die bepaalt wat als
"subsidie-relevant" telt). De scrapers zelf worden -- zoals in
Scrappingtool-v2 -- niet unit-getest; die valideer je via een echte
Actions-run.
