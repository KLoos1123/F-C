"""Hero Interim Professionals - opdrachtenlijst.

Publieke pagina, geen login nodig. Alle opdrachten staan op één pagina
in JetEngine-listingitems; er is geen paginering aangetroffen.
"""

import requests
from bs4 import BeautifulSoup

BRON = "hero"

URL = "https://interimprofessionals.hero.eu/interim-opdrachten/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _slug(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


def _uit_item(item):
    link = item.select_one("h4.entry-title a")
    if not link or not link.get("href"):
        return None

    url = link["href"]
    tijd = item.select_one(".post-meta time")
    regio = item.select_one(".jet-content-fields__item-value")

    return {
        "tender_id": _slug(url),
        "nummer": None,
        "titel": link.get_text(strip=True),
        "organisatie": None,
        "status": "Open",
        "deadline": None,
        "publicatiedatum": tijd.get("datetime") if tijd else None,
        "locatie": regio.get_text(strip=True) if regio else None,
        "url": url,
    }


def haal_op():
    """Wordt aangeroepen door run.py. Geeft een lijst dicts terug."""
    r = requests.get(URL, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    items = soup.select("div.jet-posts__item")
    print(f"  {len(items)} opdrachten gevonden")

    return [rij for rij in (_uit_item(i) for i in items) if rij]
