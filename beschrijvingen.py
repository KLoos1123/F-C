"""Aparte opslag voor opdracht-omschrijvingen.

De hoofdtabel (tenders) blijft licht: alleen de korte velden voor het dashboard.
De volledige omschrijvingen komen in een eigen tabel, zodat we per opdracht
tekst kunnen verzamelen (input voor de latere AI-inschatting van de eindklant)
zonder elke query op de hoofdtabel te vertragen.

Contract: een scraper mag in zijn rij-dict een veld 'omschrijving' meegeven.
run.py haalt die eruit en bewaart ze hier op (bron, tender_id).
"""

import sqlite3
from datetime import datetime, timezone

DB = "tenders.db"
MAX_TEKEN = 4000   # kap heel lange teksten af; genoeg voor matching, houdt db klein

SCHEMA = """
CREATE TABLE IF NOT EXISTS beschrijvingen (
    bron          TEXT NOT NULL,
    tender_id     TEXT NOT NULL,
    omschrijving  TEXT,
    opgehaald_op  TEXT NOT NULL,
    PRIMARY KEY (bron, tender_id)
);
"""


def _verbind():
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    return conn


def opslaan(rijen):
    """rijen: dicts met minimaal bron, tender_id en omschrijving.

    Alleen niet-lege omschrijvingen worden bewaard/bijgewerkt. Geeft het aantal
    weggeschreven omschrijvingen terug.
    """
    conn = _verbind()
    nu = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    for r in rijen:
        tekst = (r.get("omschrijving") or "").strip()
        bron = r.get("bron")
        tid = r.get("tender_id")
        if not tekst or not bron or tid is None:
            continue
        if len(tekst) > MAX_TEKEN:
            tekst = tekst[:MAX_TEKEN]
        conn.execute(
            """
            INSERT INTO beschrijvingen (bron, tender_id, omschrijving, opgehaald_op)
            VALUES (?,?,?,?)
            ON CONFLICT (bron, tender_id) DO UPDATE SET
                omschrijving = excluded.omschrijving,
                opgehaald_op = excluded.opgehaald_op
            """,
            (bron, str(tid), tekst, nu),
        )
        n += 1
    conn.commit()
    conn.close()
    return n


def aanwezig():
    """(bron, tender_id)-paren die al een omschrijving hebben."""
    conn = _verbind()
    paren = {(r[0], r[1]) for r in conn.execute(
        "SELECT bron, tender_id FROM beschrijvingen")}
    conn.close()
    return paren


def per_bron():
    conn = _verbind()
    rijen = conn.execute(
        "SELECT bron, count(*) AS aantal FROM beschrijvingen GROUP BY bron ORDER BY aantal DESC"
    ).fetchall()
    conn.close()
    return rijen
