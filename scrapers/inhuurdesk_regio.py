"""Regionale inhuurdesks op het gedeelde "Marktplaats"-platform.

Drie desks draaien op identieke software (server-side gerenderd):
  - inhuur.werkeninnoordhollandnoord.nl
  - inhuurdesk.werkeninnoordoostbrabant.nl
  - inhuur.werkeninzuidoostbrabant.nl

Opdracht-links hebben de vorm /Opdracht/{Organisatie-slug}/{Titel-slug}/{id}.
We lezen de /opdrachten-lijstpagina (en de homepage als vangnet) en proberen
eenvoudige ?page=N-paginering tot er geen nieuwe id's meer bijkomen.
"""

import re
from urllib.parse import unquote
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

BRON = "inhuurdesk-regio"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

DESKS = [
    ("nhn", "Noord-Holland Noord", "https://inhuur.werkeninnoordhollandnoord.nl"),
    ("nob", "Noordoost-Brabant", "https://inhuurdesk.werkeninnoordoostbrabant.nl"),
    ("zob", "Zuidoost-Brabant", "https://inhuur.werkeninzuidoostbrabant.nl"),
]

OPDRACHT_RE = re.compile(r"^/Opdracht/([^/]+)/([^/]+)/(\d+)$")
MAX_PAGINA = 30


def _ontslug(s):
    """'Gemeente-Schagen' -> 'Gemeente Schagen' (lossy maar leesbaar)."""
    return re.sub(r"\s+", " ", unquote(s).replace("-", " ")).strip()


def _uit_anker(a, base, prefix, regio):
    m = OPDRACHT_RE.match(a.get("href") or "")
    if not m:
        return None
    org_slug, titel_slug, oid = m.groups()

    # De h3 op de homepage kapt lange titels af ("...piek..."); de URL-slug
    # bevat de volledige titel, dus die heeft dan de voorkeur.
    titel = a.get_text(strip=True) or None
    if (not titel or titel.lower() in ("delen", "bekijk")
            or titel.endswith("...") or titel.endswith("…")):
        titel = _ontslug(titel_slug)

    return {
        "tender_id": f"{prefix}-{oid}",
        "nummer": oid,
        "titel": titel,
        "organisatie": _ontslug(org_slug),
        "status": "Open",
        "deadline": None,
        "publicatiedatum": None,
        "locatie": regio,
        "url": base + a["href"],
    }


def _desk(ctx, prefix, regio, base):
    rijen = {}

    def verwerk(html):
        nieuw = 0
        for a in BeautifulSoup(html, "lxml").select("a[href^='/Opdracht/']"):
            rij = _uit_anker(a, base, prefix, regio)
            if rij and rij["tender_id"] not in rijen:
                # kies het anker met de beste titel (h3 boven lege ankers)
                rijen[rij["tender_id"]] = rij
                nieuw += 1
            elif rij:
                oud = rijen[rij["tender_id"]]
                if (not oud["titel"] or len(rij["titel"] or "") > len(oud["titel"])):
                    rijen[rij["tender_id"]] = rij
        return nieuw

    # lijstpagina met simpele paginering, homepage als vangnet
    for pagina in range(1, MAX_PAGINA + 1):
        url = f"{base}/opdrachten" if pagina == 1 else f"{base}/opdrachten?page={pagina}"
        try:
            r = ctx.request.get(url, timeout=30000)
        except Exception as e:
            print(f"    {prefix} pagina {pagina}: {e}")
            break
        if not r.ok:
            break
        if verwerk(r.text()) == 0:
            break

    try:
        r = ctx.request.get(base + "/", timeout=30000)
        if r.ok:
            verwerk(r.text())
    except Exception:
        pass

    print(f"    {regio}: {len(rijen)}")
    return list(rijen.values())


def haal_op():
    """Wordt aangeroepen door run.py. Geeft een lijst dicts terug."""
    rijen = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="nl-NL")
        for prefix, regio, base in DESKS:
            try:
                rijen.extend(_desk(ctx, prefix, regio, base))
            except Exception as e:
                print(f"    {regio} MISLUKT: {e}")
        browser.close()

    print(f"  {len(rijen)} opdrachten gevonden")
    return rijen
