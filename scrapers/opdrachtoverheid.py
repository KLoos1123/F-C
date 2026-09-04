"""Opdracht Overheid - interim/freelance/zzp-opdrachten bij de (semi-)overheid.

www.opdrachtoverheid.nl is een Nuxt/Pinia-SPA (geen server-side gerenderde
lijst) die praat met een los API-domein: kbenp-match-api.azurewebsites.net
("KBenP" is de initiatiefnemer). Het overzicht laadt via een client-side
zoekaanroep op basis van een generieke filter-DSL
(`{single, filters:[{field_name, value, operator}], order_by}`) -- bevestigd
voor het organisatie/locatie-endpoint (`/search/vacanciesLocation`), maar het
exacte endpoint voor de VOLLEDIGE opdrachtenlijst kon niet worden vastgesteld
door de JS-bundels statisch te lezen (geen live browser beschikbaar tijdens
het bouwen van deze scraper).

Daarom onderschept deze scraper -- zoals magnit.py -- het live netwerkverkeer:
navigeer naar de homepage (waar de zoekwidget staat), wacht tot het netwerk
stil is, en pak de grootste JSON-array die de API in die tijd teruggaf. Velden
worden generiek herkend (meerdere kandidaat-namen per veld, NL en EN) omdat de
exacte respons-vorm niet vooraf bekend is.

Dit is dus een best-effort eerste versie: valideer/verfijn aan de hand van de
eerste echte run in GitHub Actions (zie debug_opdrachtoverheid.png bij falen).
Geen login nodig om te bladeren.
"""

import re
from playwright.sync_api import sync_playwright

BRON = "opdrachtoverheid"

BASE = "https://www.opdrachtoverheid.nl"
API_HOST = "kbenp-match-api.azurewebsites.net"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Kandidaat-veldnamen per uitvoerveld, in volgorde van voorkeur.
VELD_KANDIDATEN = {
    "id": ["id", "vacancyId", "vacancy_id", "jobId", "referenceNumber", "reference", "guid"],
    "titel": ["title", "titel", "jobTitle", "vacancyTitle", "functieTitel", "name"],
    "organisatie": ["organizationName", "organisationName", "organizationDisplayName",
                     "organisatie", "clientName", "buyingOrganization",
                     "tender_buying_organization", "organization"],
    "status": ["status", "state", "publishStatus"],
    "deadline": ["deadline", "closingDate", "applicationDeadline", "reactionDeadline",
                 "endDate", "closeDate"],
    "publicatiedatum": ["publishDate", "publishedAt", "publicationDate", "startDate",
                         "createdAt"],
    "locatie": ["location", "locatie", "place", "region", "city"],
    "organisatie_slug": ["organizationSlug", "organisationSlug", "organizationUrlSlug"],
    "titel_slug": ["jobtitleSlug", "titleSlug", "jobTitleSlug"],
}


def _eerste(item, namen):
    for naam in namen:
        if naam in item and item[naam] not in (None, ""):
            return item[naam]
    return None


def _slug(tekst):
    if not tekst:
        return None
    s = re.sub(r"[^a-z0-9]+", "-", str(tekst).lower()).strip("-")
    return s or None


def _uit_item(item):
    if not isinstance(item, dict):
        return None
    iid = _eerste(item, VELD_KANDIDATEN["id"])
    titel = _eerste(item, VELD_KANDIDATEN["titel"])
    # "is None" i.p.v. truthiness: een id van 0 is geldig maar valt anders
    # (net als een lege titel-string) verkeerd door de boolean-check heen.
    if iid is None or not titel:
        return None

    org = _eerste(item, VELD_KANDIDATEN["organisatie"])
    org_slug = _eerste(item, VELD_KANDIDATEN["organisatie_slug"]) or _slug(org)
    titel_slug = _eerste(item, VELD_KANDIDATEN["titel_slug"]) or _slug(titel)
    url = (f"{BASE}/inhuuropdracht/{org_slug}/{titel_slug}/{iid}"
           if org_slug and titel_slug else BASE)

    return {
        "tender_id": str(iid),
        "nummer": None,
        "titel": str(titel),
        "organisatie": org,
        "status": _eerste(item, VELD_KANDIDATEN["status"]) or "Open",
        "deadline": _eerste(item, VELD_KANDIDATEN["deadline"]),
        "publicatiedatum": _eerste(item, VELD_KANDIDATEN["publicatiedatum"]),
        "locatie": _eerste(item, VELD_KANDIDATEN["locatie"]),
        "url": url,
    }


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

    # Eerste echte run (zie PR #1) onderschepte drie responses van deze host:
    #   v7/vacancies/counts        (17)  -- aantallen per categorie, geen vacatures
    #   v7/vacancies/search        (25)  -- de eigenlijke lijst
    #   search/vacanciesLocation  (427)  -- organisaties/locaties (uit _organisaties-achtig
    #                                       endpoint), geen vacature-velden
    # "grootste lijst" koos toen dus de verkeerde (vacanciesLocation): 0 opdrachten
    # na het filteren op id+titel. /vacancies/search met naam winnen altijd van de
    # rest; alleen als die er niet bij zit vallen we terug op de grootste lijst.
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
    return rijen
