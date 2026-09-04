"""Opdracht Overheid - interim/freelance/zzp-opdrachten bij de (semi-)overheid.

www.opdrachtoverheid.nl is een Nuxt/Pinia-SPA (geen server-side gerenderde
lijst) die praat met een los API-domein: kbenp-match-api.azurewebsites.net
("KBenP" is de initiatiefnemer). Het overzicht laadt via een client-side
call naar `v7/vacancies/search`. Deze scraper onderschept dat live
netwerkverkeer -- zoals magnit.py -- door naar de homepage te navigeren
(waar de zoekwidget staat) en te wachten tot het netwerk stil is.

Bevestigd op basis van een echte run (zie PR #1): Opdracht Overheid is zelf
een aggregator boven andere VMS-systemen (het voorbeelditem tijdens het
bouwen kwam van "circle8", een Salesforce-VMS net als stedin_vms.py) --
`tender_id` is geprefixt met het bronsysteem (bv. "circle8_..."),
`tender_source` noemt het, en `tender_url` wijst naar de oorspronkelijke
plek (die gebruiken we rechtstreeks, in plaats van zelf een URL te
construeren). Volledige veldenlijst uit dat voorbeelditem staat in
VELD_KANDIDATEN hieronder; niet elk veld is bij elke bron gevuld.

Geen login nodig om te bladeren.
"""

import json
import re
from playwright.sync_api import sync_playwright

BRON = "opdrachtoverheid"

BASE = "https://www.opdrachtoverheid.nl"
API_HOST = "kbenp-match-api.azurewebsites.net"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Bevestigde veldnamen (zie moduledocstring) uit v7/vacancies/search, met een
# paar generieke fallbacks ervoor in geval een andere onderliggende bron
# (ander VMS) net andere namen gebruikt.
VELD_KANDIDATEN = {
    "id": ["tender_id", "id"],
    "titel": ["tender_name", "title", "titel"],
    "organisatie": ["tender_buying_organization", "organizationName", "organisatie"],
    "status": ["tender_status", "status"],
    "deadline": ["tender_date", "deadline", "closingDate"],
    "publicatiedatum": ["tender_first_seen", "publishDate", "publishedAt"],
    "locatie": ["tender_job_location", "organization_location", "location"],
    "url": ["tender_url", "url"],
    "omschrijving_html": ["tender_description_html"],
    "omschrijving_tekst": ["tender_overview", "tender_requirements", "tender_other_information"],
}

_HTML_TAG = re.compile(r"<[^>]+>")


def _eerste(item, namen):
    """Eerste bruikbare waarde uit item voor de gegeven kandidaat-veldnamen.

    Alleen scalars (str/int/float/bool): Opdracht Overheid aggregeert meerdere
    onderliggende VMS'en (zie moduledocstring), en niet elke bron levert
    hetzelfde veld als platte tekst -- bv. organization_location bleek in de
    praktijk soms een geneste dict, die db.py's sqlite-binding niet aankan
    (en die je toch niet zomaar leesbaar kunt tonen). Val in dat geval door
    naar de volgende kandidaat i.p.v. te crashen of een Python-repr op te
    slaan.
    """
    for naam in namen:
        waarde = item.get(naam)
        if waarde not in (None, "") and isinstance(waarde, (str, int, float, bool)):
            return waarde
    return None


def _tekst_uit_html(html):
    if not html:
        return None
    tekst = _HTML_TAG.sub(" ", html)
    tekst = re.sub(r"\s+", " ", tekst).strip()
    return tekst or None


def _uit_item(item):
    if not isinstance(item, dict):
        return None
    iid = _eerste(item, VELD_KANDIDATEN["id"])
    titel = _eerste(item, VELD_KANDIDATEN["titel"])
    # "is None" i.p.v. truthiness: een id van 0 is geldig maar valt anders
    # (net als een lege titel-string) verkeerd door de boolean-check heen.
    if iid is None or not titel:
        return None

    omschrijving = (_tekst_uit_html(_eerste(item, VELD_KANDIDATEN["omschrijving_html"]))
                    or _eerste(item, VELD_KANDIDATEN["omschrijving_tekst"]))

    rij = {
        "tender_id": str(iid),
        "nummer": None,
        "titel": str(titel),
        "organisatie": _eerste(item, VELD_KANDIDATEN["organisatie"]),
        "status": _eerste(item, VELD_KANDIDATEN["status"]) or "Open",
        "deadline": _eerste(item, VELD_KANDIDATEN["deadline"]),
        "publicatiedatum": _eerste(item, VELD_KANDIDATEN["publicatiedatum"]),
        "locatie": _eerste(item, VELD_KANDIDATEN["locatie"]),
        "url": _eerste(item, VELD_KANDIDATEN["url"]) or BASE,
    }
    if omschrijving:
        rij["omschrijving"] = omschrijving
    return rij


def _grootste_lijst(obj):
    """Zoekt recursief de grootste lijst van dicts in een JSON-structuur."""
    beste = []

    def _loop(node):
        nonlocal beste
        if isinstance(node, list):
            if node and all(isinstance(x, dict) for x in node) and len(node) > len(beste):
                beste = node
            for x in node:
                _loop(x)
        elif isinstance(node, dict):
            for v in node.values():
                _loop(v)

    _loop(obj)
    return beste


def haal_op():
    """Wordt aangeroepen door run.py. Geeft een lijst dicts terug."""
    gevangen = []  # (url, json-body) van elke respons van de match-API

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="nl-NL")
        page = ctx.new_page()

        def onresponse(resp):
            if API_HOST not in resp.url:
                return
            try:
                data = resp.json()
            except Exception:
                return
            gevangen.append((resp.url, data))

        page.on("response", onresponse)

        try:
            page.goto(BASE + "/", timeout=60000, wait_until="networkidle")
        except Exception:
            pass  # networkidle kan timeouten op een pagina met polling/analytics
        page.wait_for_timeout(3000)

        if not gevangen:
            try:
                page.screenshot(path="debug_opdrachtoverheid.png", full_page=True)
            except Exception:
                pass

        browser.close()

    # v7/vacancies/search is de bevestigde lijst-endpoint (zie moduledocstring);
    # andere responses op dezelfde host (bv. v7/vacancies/counts, of
    # search/vacanciesLocation met organisatie/locatie-data) leveren geen
    # vacature-velden. Kies 'm expliciet wanneer gezien; anders de grootste
    # lijst als vangnet voor het geval het endpoint ooit verandert.
    kandidaten = []
    beste_naam_match = False
    for url, data in gevangen:
        lijst = _grootste_lijst(data)
        naam_match = "vacancies/search" in url.lower()
        beter = (naam_match and not beste_naam_match) or (
            naam_match == beste_naam_match and len(lijst) > len(kandidaten)
        )
        if beter:
            kandidaten = lijst
            beste_naam_match = naam_match
            print(f"  kandidaat-lijst ({len(lijst)} items) via {url}")

    if not kandidaten:
        raise RuntimeError(
            f"geen opdrachtenlijst onderschept ({len(gevangen)} API-responses gezien), "
            "zie debug_opdrachtoverheid.png"
        )

    rijen = [r for r in (_uit_item(i) for i in kandidaten) if r]
    print(f"  {len(rijen)} opdrachten gevonden")

    if not rijen and kandidaten:
        # Veldnamen kwamen niet overeen -- dump sleutels + voorbeeld zodat
        # VELD_KANDIDATEN in één keer met de echte namen aangevuld kan worden
        # i.p.v. nog een CI-cyclus blind te gokken.
        voorbeeld = kandidaten[0]
        print(f"  0 rijen ondanks {len(kandidaten)} kandidaten -- veldnamen "
              f"komen niet overeen met VELD_KANDIDATEN. Sleutels van item 0: "
              f"{sorted(voorbeeld.keys()) if isinstance(voorbeeld, dict) else type(voorbeeld)}")
        print(f"  voorbeelditem: {json.dumps(voorbeeld, ensure_ascii=False)[:1000]}")

    return rijen
