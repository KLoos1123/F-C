"""Flextender.

Geen login nodig: de opdrachtenlijst is publiek. De pagina bevat een
verborgen widget-token (kbs_flx_widget_config) dat je meestuurt naar
de zoek-endpoint van de website (wp-admin/admin-ajax.php). Die endpoint
geeft in één keer een HTML-blob terug met ALLE opdrachten (de "paginas"
in de UI zijn alleen CSS-hidden divs, geen aparte requests).
"""

import re
import time
import requests
from bs4 import BeautifulSoup

BRON = "flextender"

PAGE_URL = "https://www.flextender.nl/opdrachten/"
AJAX_URL = "https://www.flextender.nl/wp-admin/admin-ajax.php"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ---------------------------------------------------------------- token

def _get_met_retry(sessie, url, pogingen=4):
    """GET met oplopende retries: één retry van 3s bleek niet genoeg voor
    een 504 Gateway Time-out op flextender.nl (dezelfde fout kwam terug op
    de verificatierun vlak erna, CI-run 2026-10-21) -- oplopende backoff
    geeft een langere storing meer ruimte om te herstellen voordat we deze
    hele bron laten mislukken."""
    wachttijd = 5
    for poging in range(pogingen):
        try:
            r = sessie.get(url, headers={"user-agent": UA}, timeout=30)
            r.raise_for_status()
            return r
        except Exception:
            if poging + 1 == pogingen:
                raise
            time.sleep(wachttijd)
            wachttijd *= 2


def _token(sessie):
    r = _get_met_retry(sessie, PAGE_URL)
    soup = BeautifulSoup(r.text, "lxml")
    veld = soup.find("input", {"name": "kbs_flx_widget_config"})
    if not veld or not veld.get("value"):
        raise RuntimeError("kbs_flx_widget_config niet gevonden op de pagina")
    return veld["value"]


# ---------------------------------------------------------------- ophalen

def _zoek(sessie, token, zoekterm=""):
    payload = {
        "kbs_flx_widget_config": token,
        "action": "kbs_flx_searchjobs",
        "kbs_flx_joblsrc_freetext": zoekterm,
        "StackOverflow1370021": "Fix autosubmit bug",
        "_charset_": "UTF-8",
    }
    r = sessie.post(AJAX_URL, data=payload, headers={"user-agent": UA}, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data.get("resultHtml", "")


# ---------------------------------------------------------------- normaliseren

def _tekst(el):
    return el.get_text(strip=True) if el else None


def _samenvattingsveld(kaart, label):
    """Zoekt een css-summaryrow met de gegeven caption en geeft de waarde terug."""
    for rij in kaart.select(".css-summaryrow"):
        caption = rij.select_one(".css-caption")
        if caption and caption.get_text(strip=True) == label:
            return _tekst(rij.select_one(".css-value"))
    return None


def _uit_kaart(kaart):
    url = kaart.get("data-kbslinkurl")
    aanvraagnr = _samenvattingsveld(kaart, "Aanvraagnummer")
    tid = aanvraagnr or (re.search(r"aanvraagnr=(\d+)", url or "").group(1) if url else None)

    return {
        "tender_id": str(tid) if tid else None,
        "nummer": aanvraagnr,
        "titel": _tekst(kaart.select_one(".css-jobtitle")),
        "organisatie": _tekst(kaart.select_one(".css-customer")),
        "status": "Open",
        "deadline": _samenvattingsveld(kaart, "Einde inschrijfdatum"),
        "publicatiedatum": None,
        "start": _samenvattingsveld(kaart, "Start"),
        "duur": _samenvattingsveld(kaart, "Duur"),
        "uren_per_week": _samenvattingsveld(kaart, "Uren per week"),
        "regio": _samenvattingsveld(kaart, "Regio"),
        "opleidingsniveau": _samenvattingsveld(kaart, "Opleidingsniveau"),
        "url": url,
    }


# ---------------------------------------------------------------- publiek

def haal_op():
    """Wordt aangeroepen door run.py. Geeft een lijst dicts terug."""
    sessie = requests.Session()

    token = _token(sessie)
    print("  token opgehaald")

    html = _zoek(sessie, token)
    soup = BeautifulSoup(html, "lxml")
    kaarten = soup.select(".css-foundjob")
    print(f"  {len(kaarten)} opdrachten gevonden")

    rijen = [_uit_kaart(k) for k in kaarten]
    rijen = [r for r in rijen if r["tender_id"]]

    return rijen

