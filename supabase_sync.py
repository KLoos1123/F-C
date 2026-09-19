"""Synchroniseert gescrapete en geclassificeerde opdrachten naar Supabase.

Kopie van het patroon uit Scrappingtool-v2/supabase_sync.py, met de
subsidie_*-velden uit classificatie.py toegevoegd aan de payload. Supabase is
hier de databron voor externe raadpleging (bv. een Copilot Studio-agent via
de anon-key) naast de SQLite-database die dit tool zelf gebruikt/commit.

Dit script raakt de status / status_gewijzigd_door / status_gewijzigd_op
kolommen NOOIT aan -- dat zijn (voor een toekomstig interactief dashboard)
door gebruikers gezette waarden en worden hier bewust nooit overschreven (zie
upsert_tenders_bulk in supabase_schema.sql).

Vereiste env vars (zet als GitHub Actions secrets):
    SUPABASE_URL                 bv. https://xxxx.supabase.co
    SUPABASE_SERVICE_ROLE_KEY    service_role key (NOOIT de anon key hier
                                  gebruiken -- deze bypassed row level
                                  security en mag alleen server-side draaien)

Draai eerst supabase_schema.sql eenmalig in de Supabase SQL editor (zie
README) voordat dit script iets kan wegschrijven.
"""

import os
from datetime import datetime, timezone

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

BATCH = 500  # rijen per request; houdt de payload en de plpgsql-loop overzichtelijk


def geconfigureerd():
    """True als SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY gezet zijn.

    Supabase is optioneel voor dit tool (zie README); run.py gebruikt dit om
    de sync-stap over te slaan zonder 'm als mislukte bron te tellen wanneer
    hij simpelweg niet is ingesteld.
    """
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _headers(extra=None):
    if not geconfigureerd():
        raise RuntimeError(
            "SUPABASE_URL en/of SUPABASE_SERVICE_ROLE_KEY ontbreken. "
            "Zet ze als secrets in de GitHub Action (zie README)."
        )
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def _chunks(lijst, grootte):
    for i in range(0, len(lijst), grootte):
        yield lijst[i:i + grootte]


def sync_tenders(rijen):
    """rijen: dicts zoals verzameld in run.py, na classificatie.classificeer()
    (bron, tender_id, nummer, titel, organisatie, status [= bron-status,
    zoals de scraper 'm aanlevert], deadline, publicatiedatum, locatie, url,
    subsidie_relevant, subsidie_categorieen, subsidie_trefwoorden, subsidie_score).

    Slaat rijen zonder bron of tender_id over. Geeft het aantal gesyncte
    rijen terug.
    """
    payload = [
        {
            "bron": r.get("bron"),
            "tender_id": str(r.get("tender_id") if r.get("tender_id") is not None else r.get("nummer") or ""),
            "nummer": r.get("nummer"),
            "titel": r.get("titel"),
            "organisatie": r.get("organisatie"),
            "bron_status": r.get("status"),
            "deadline": r.get("deadline"),
            "publicatiedatum": r.get("publicatiedatum"),
            "locatie": r.get("locatie"),
            "url": r.get("url"),
            "subsidie_relevant": bool(r.get("subsidie_relevant")),
            "subsidie_categorieen": r.get("subsidie_categorieen") or "",
            "subsidie_trefwoorden": r.get("subsidie_trefwoorden") or "",
            "subsidie_score": r.get("subsidie_score") or 0,
        }
        for r in rijen
        if r.get("bron") and (r.get("tender_id") or r.get("nummer"))
    ]
    if not payload:
        return 0

    url = f"{SUPABASE_URL}/rest/v1/rpc/upsert_tenders_bulk"
    n = 0
    for chunk in _chunks(payload, BATCH):
        resp = requests.post(url, headers=_headers(), json={"rows": chunk}, timeout=60)
        if not resp.ok:
            raise RuntimeError(f"upsert_tenders_bulk mislukt ({resp.status_code}): {resp.text[:500]}")
        n += len(chunk)
    return n


def sync_beschrijvingen(rijen):
    """rijen: dicts met minimaal bron, tender_id, omschrijving.

    Overschrijft omschrijving + opgehaald_op altijd (zelfde gedrag als
    beschrijvingen.py). Geeft het aantal gesyncte rijen terug.
    """
    nu = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = []
    for r in rijen:
        tekst = (r.get("omschrijving") or "").strip()
        bron = r.get("bron")
        tid = r.get("tender_id")
        if not tekst or not bron or tid is None:
            continue
        payload.append({
            "bron": bron,
            "tender_id": str(tid),
            "omschrijving": tekst[:4000],
            "opgehaald_op": nu,
        })
    if not payload:
        return 0

    url = f"{SUPABASE_URL}/rest/v1/beschrijvingen"
    headers = _headers({"Prefer": "resolution=merge-duplicates"})
    n = 0
    for chunk in _chunks(payload, BATCH):
        resp = requests.post(url, headers=headers, json=chunk, timeout=60)
        if not resp.ok:
            raise RuntimeError(f"beschrijvingen-sync mislukt ({resp.status_code}): {resp.text[:500]}")
        n += len(chunk)
    return n
