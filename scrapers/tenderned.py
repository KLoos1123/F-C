"""TenderNed - aanbestedingen via de open publicatie-API (papi).

Publieke JSON-API, geen login nodig. De API is gesorteerd op nieuwste eerst;
we halen de publicaties van de laatste weken op (gepagineerd) zodat de focus
op nieuwe leads ligt. Dedup op (bron, tender_id) bouwt vanzelf historie op
over runs heen.
"""

import requests
from datetime import datetime, timezone, timedelta

BRON = "tenderned"

API = "https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties"
DETAIL = "https://www.tenderned.nl/aankondigingen/overzicht"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

DAGEN_TERUG = 21
BLOK = 100
MAX_PAGINA = 300  # veiligheidsgrens


def _oms(v):
    return (v or {}).get("omschrijving")


def _uit_publicatie(p):
    pid = p.get("publicatieId")
    return {
        "tender_id": str(pid),
        "nummer": str(p.get("kenmerk")) if p.get("kenmerk") else None,
        "titel": p.get("aanbestedingNaam"),
        "organisatie": p.get("opdrachtgeverNaam"),
        "status": _oms(p.get("publicatiestatus")),
        "deadline": p.get("sluitingsDatum"),
        "publicatiedatum": p.get("publicatieDatum"),
        "locatie": None,
        "type_opdracht": _oms(p.get("typeOpdracht")),
        "procedure": _oms(p.get("procedure")),
        "type_publicatie": _oms(p.get("typePublicatie")),
        "url": f"{DETAIL}/{pid}",
    }


def haal_op():
    """Wordt aangeroepen door run.py. Geeft een lijst dicts terug."""
    sessie = requests.Session()
    headers = {"user-agent": UA, "accept": "application/json"}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DAGEN_TERUG)).strftime("%Y-%m-%d")

    rijen = []
    pagina = 0
    totaal = None

    while pagina < MAX_PAGINA:
        r = sessie.get(
            API,
            params={"page": pagina, "size": BLOK, "publicatieDatumVanaf": cutoff},
            headers=headers,
            timeout=45,
        )
        r.raise_for_status()
        data = r.json()

        if totaal is None:
            totaal = data.get("totalElements")
            print(f"  venster vanaf {cutoff}, {totaal} publicaties gemeld")

        content = data.get("content") or []
        if not content:
            break

        # nieuwste-eerst: stop zodra we voorbij het venster zijn
        te_oud = False
        for p in content:
            pd = p.get("publicatieDatum") or ""
            if pd and pd < cutoff:
                te_oud = True
                continue
            if p.get("publicatieId"):
                rijen.append(_uit_publicatie(p))

        if data.get("last") or te_oud:
            break
        pagina += 1

    print(f"  {len(rijen)} publicaties opgehaald")
    return rijen
