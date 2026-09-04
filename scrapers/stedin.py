"""Stedin - werkenbij.stedin.net (Radancy-platform).

Geen login nodig. De zoekpagina toont 15 vacatures per pagina en pagineert
via de query-parameter ?p=N. Het CDN kan kale requests blokkeren, daarom
halen we de pagina's op via een browsercontext (Playwright) en parsen we de
HTML met BeautifulSoup.
"""

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

BRON = "stedin"

BASE = "https://werkenbij.stedin.net"
ZOEK = f"{BASE}/vacatures-zoeken"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

KAART = "a.job-list--link[data-job-id]"
MAX_PAGINA = 40  # veiligheidsgrens


def _tekst(el):
    return el.get_text(strip=True) if el else None


def _uit_kaart(a):
    href = a.get("href")
    jid = a.get("data-job-id")
    if not jid:
        return None

    return {
        "tender_id": str(jid),
        "nummer": None,
        "titel": _tekst(a.find("h3")),
        "organisatie": "Stedin",
        "status": "Open",
        "deadline": None,
        "publicatiedatum": None,
        "locatie": _tekst(a.find("span", class_="job-location")),
        "categorie": _tekst(a.find("span", class_="category")),
        "url": BASE + href if href else None,
    }


def haal_op():
    """Wordt aangeroepen door run.py. Geeft een lijst dicts terug."""
    rijen = []
    gezien = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="nl-NL")

        for pagina in range(1, MAX_PAGINA + 1):
            resp = ctx.request.get(f"{ZOEK}?p={pagina}", timeout=30000)
            if not resp.ok:
                print(f"    pagina {pagina}: status {resp.status}, stoppen")
                break

            kaarten = BeautifulSoup(resp.text(), "lxml").select(KAART)
            if not kaarten:
                break

            nieuw = 0
            for a in kaarten:
                rij = _uit_kaart(a)
                if rij and rij["tender_id"] not in gezien:
                    gezien.add(rij["tender_id"])
                    rijen.append(rij)
                    nieuw += 1

            # Laatste pagina bereikt: paginering herhaalt zichzelf.
            if nieuw == 0:
                break

        browser.close()

    print(f"  {len(rijen)} vacatures gevonden")
    return rijen
