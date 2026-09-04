"""NS - werkenbijns.nl.

Geen login nodig. De vacatures staan server-side in de overzichtspagina;
de paginering gaat via ?o=N (offset in stappen van 10). We halen de
pagina's op via een browsercontext (Playwright) en parsen de HTML met
BeautifulSoup.
"""

import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

BRON = "ns"

BASE = "https://www.werkenbijns.nl"
OVERZICHT = f"{BASE}/vacatures"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

STAP = 10
MAX_OFFSET = 2000  # veiligheidsgrens


def _tekst(el):
    return el.get_text(strip=True) if el else None


def _metadata(kaart, soort):
    """Waarde van een metadata-regel (location/hours/discipline)."""
    li = kaart.select_one(f"li.hireserve.{soort} .metadata-text")
    return _tekst(li)


def _uit_kaart(a):
    href = a.get("href") or ""
    m = re.search(r"-(\d+)$", href)
    if not m:
        return None
    tid = m.group(1)

    return {
        "tender_id": tid,
        "nummer": None,
        "titel": _tekst(a.select_one(".vacancy-item-titles h3") or a.find("h3")),
        "organisatie": "NS",
        "status": "Open",
        "deadline": None,
        "publicatiedatum": None,
        "locatie": _metadata(a, "location"),
        "uren_per_week": _metadata(a, "hours"),
        "vakgebied": _metadata(a, "discipline"),
        "url": href if href.startswith("http") else BASE + href,
    }


def haal_op():
    """Wordt aangeroepen door run.py. Geeft een lijst dicts terug."""
    rijen = []
    gezien = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="nl-NL")

        offset = 0
        while offset <= MAX_OFFSET:
            url = OVERZICHT if offset == 0 else f"{OVERZICHT}?o={offset}"
            resp = ctx.request.get(url, timeout=30000)
            if not resp.ok:
                print(f"    offset {offset}: status {resp.status}, stoppen")
                break

            soup = BeautifulSoup(resp.text(), "lxml")
            kaarten = soup.select("a.vacancy-item[href]")
            if not kaarten:
                break

            nieuw = 0
            for a in kaarten:
                rij = _uit_kaart(a)
                if rij and rij["tender_id"] not in gezien:
                    gezien.add(rij["tender_id"])
                    rijen.append(rij)
                    nieuw += 1

            if nieuw == 0:  # paginering herhaalt zichzelf
                break
            offset += STAP

        browser.close()

    print(f"  {len(rijen)} vacatures gevonden")
    return rijen
