"""Gedeelde database voor alle scrapers.

Kopie van het db.py-patroon uit Scrappingtool-v2 (Mercell-tenderscraper),
uitgebreid met de subsidie-classificatie (zie classificatie.py) als vaste
kolommen -- zo kun je "hoeveel subsidie-relevante opdrachten per maand"
rechtstreeks met SQL beantwoorden, in plaats van bij elke vraag opnieuw op
trefwoorden te moeten filteren.

Elke scraper levert rijen aan met de velden uit VELDEN. Deduplicatie gebeurt
op (bron, tender_id).
"""

import sqlite3
from datetime import datetime, timezone

DB = "tenders.db"

# Het contract: dit zijn de velden die elke scraper moet aanleveren
# (subsidie_* velden worden door run.py toegevoegd via classificatie.py, niet
# door de scraper zelf).
VELDEN = [
    "bron",
    "tender_id",
    "nummer",
    "titel",
    "organisatie",
    "status",
    "deadline",
    "publicatiedatum",
    "locatie",
    "url",
    "subsidie_relevant",
    "subsidie_categorieen",
    "subsidie_trefwoorden",
    "subsidie_score",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders (
    bron                  TEXT NOT NULL,
    tender_id             TEXT NOT NULL,
    nummer                TEXT,
    titel                 TEXT,
    organisatie           TEXT,
    status                TEXT,
    deadline              TEXT,
    publicatiedatum       TEXT,
    locatie               TEXT,
    url                   TEXT,
    subsidie_relevant     INTEGER NOT NULL DEFAULT 0,
    subsidie_categorieen  TEXT,
    subsidie_trefwoorden  TEXT,
    subsidie_score        INTEGER NOT NULL DEFAULT 0,
    eerst_gezien          TEXT NOT NULL,
    laatst_gezien         TEXT NOT NULL,
    PRIMARY KEY (bron, tender_id)
);

CREATE INDEX IF NOT EXISTS idx_publicatie ON tenders(publicatiedatum DESC);
CREATE INDEX IF NOT EXISTS idx_bron       ON tenders(bron);
CREATE INDEX IF NOT EXISTS idx_deadline   ON tenders(deadline);
CREATE INDEX IF NOT EXISTS idx_relevant   ON tenders(subsidie_relevant);
"""


def verbind():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def opslaan(rijen):
    """Slaat rijen op. Bestaande tenders worden bijgewerkt, niet gedupliceerd.

    Geeft terug: (aantal_nieuw, totaal_in_database)
    """
    conn = verbind()
    nu = datetime.now(timezone.utc).isoformat(timespec="seconds")

    voor = conn.execute("SELECT count(*) FROM tenders").fetchone()[0]

    for r in rijen:
        waarden = [r.get(v) for v in VELDEN]
        conn.execute(
            """
            INSERT INTO tenders
                (bron, tender_id, nummer, titel, organisatie,
                 status, deadline, publicatiedatum, locatie, url,
                 subsidie_relevant, subsidie_categorieen, subsidie_trefwoorden,
                 subsidie_score, eerst_gezien, laatst_gezien)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (bron, tender_id) DO UPDATE SET
                titel                = excluded.titel,
                organisatie          = excluded.organisatie,
                status                = excluded.status,
                deadline              = excluded.deadline,
                locatie               = excluded.locatie,
                url                   = excluded.url,
                subsidie_relevant     = excluded.subsidie_relevant,
                subsidie_categorieen  = excluded.subsidie_categorieen,
                subsidie_trefwoorden  = excluded.subsidie_trefwoorden,
                subsidie_score        = excluded.subsidie_score,
                laatst_gezien         = excluded.laatst_gezien
            """,
            waarden + [nu, nu],
        )

    conn.commit()
    na = conn.execute("SELECT count(*) FROM tenders").fetchone()[0]
    conn.close()

    return na - voor, na


def alle_rijen():
    conn = verbind()
    rijen = conn.execute(
        "SELECT * FROM tenders ORDER BY publicatiedatum DESC"
    ).fetchall()
    conn.close()
    return rijen


def nieuw_sinds(tijdstip):
    """Tenders die voor het eerst gezien zijn na het opgegeven tijdstip (ISO-string)."""
    conn = verbind()
    rijen = conn.execute(
        "SELECT * FROM tenders WHERE eerst_gezien > ? ORDER BY publicatiedatum DESC",
        (tijdstip,),
    ).fetchall()
    conn.close()
    return rijen


def per_bron():
    conn = verbind()
    rijen = conn.execute(
        "SELECT bron, count(*) AS aantal FROM tenders GROUP BY bron ORDER BY aantal DESC"
    ).fetchall()
    conn.close()
    return rijen
