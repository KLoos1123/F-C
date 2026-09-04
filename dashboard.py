"""Genereert de databron voor het HTML-dashboard.

Schrijft web/tenders.json uit de tenders-database. Het dashboard (web/index.html)
laadt dat bestand via fetch() en doet zelf alle filteren/sorteren in de browser
-- geen server, geen login (zie README voor de afweging t.o.v. Scrappingtool-v2's
Supabase-opzet). GitHub Pages host web/ zodat het dashboard op een vaste URL staat.
"""

import os
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone

DB = "tenders.db"
UITVOER_DIR = "web"

VELDEN = [
    "bron", "tender_id", "nummer", "titel", "organisatie", "status",
    "url", "locatie", "deadline", "publicatiedatum", "eerst_gezien",
    "subsidie_relevant", "subsidie_categorieen", "subsidie_trefwoorden",
    "subsidie_score",
]


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rijen = conn.execute(
        "SELECT * FROM tenders ORDER BY publicatiedatum DESC"
    ).fetchall()
    laatst = conn.execute("SELECT max(laatst_gezien) FROM tenders").fetchone()[0]
    conn.close()

    alle_rijen = [{k: r[k] for k in VELDEN} for r in rijen]
    relevante_rijen = [r for r in alle_rijen if r["subsidie_relevant"]]

    data = {
        "fileName": "tenders",
        "lastUpdated": laatst or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(alle_rijen),
        "countRelevant": len(relevante_rijen),
        "rows": alle_rijen,
    }

    os.makedirs(UITVOER_DIR, exist_ok=True)
    pad = os.path.join(UITVOER_DIR, "tenders.json")
    with open(pad, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"{pad} geschreven ({len(alle_rijen)} rijen, {len(relevante_rijen)} relevant)")

    # Omschrijvingen apart voor het dashboard: { "bron|tender_id": tekst }.
    conn2 = sqlite3.connect(DB)
    beschr = {}
    try:
        rows2 = conn2.execute(
            "SELECT bron, tender_id, omschrijving FROM beschrijvingen").fetchall()
        for bron, tid, oms in rows2:
            if oms:
                beschr[f"{bron}|{tid}"] = oms
    except sqlite3.OperationalError:
        pass  # tabel bestaat nog niet
    conn2.close()
    pad2 = os.path.join(UITVOER_DIR, "beschrijvingen.json")
    with open(pad2, "w", encoding="utf-8") as f:
        json.dump(beschr, f, ensure_ascii=False)
    print(f"{pad2} geschreven ({len(beschr)} omschrijvingen)")

    # Samenvatting voor snel marktoverzicht: relevante opdrachten per bron,
    # per categorie en per maand (voor de trendlijn -- "de markt voorspellen").
    bron_teller = Counter(r["bron"] for r in relevante_rijen if r.get("bron"))
    cat_teller = Counter()
    for r in relevante_rijen:
        for cat in (r.get("subsidie_categorieen") or "").split(", "):
            if cat:
                cat_teller[cat] += 1
    maand_teller = Counter()
    for r in relevante_rijen:
        ref = r.get("publicatiedatum") or r.get("eerst_gezien") or ""
        if len(ref) >= 7:
            maand_teller[ref[:7]] += 1  # "YYYY-MM"

    samenvatting = {
        "lastUpdated": data["lastUpdated"],
        "totaal": len(alle_rijen),
        "totaalRelevant": len(relevante_rijen),
        "per_bron": dict(bron_teller.most_common()),
        "per_categorie": dict(cat_teller.most_common()),
        "per_maand": dict(sorted(maand_teller.items())),
    }
    pad3 = os.path.join(UITVOER_DIR, "samenvatting.json")
    with open(pad3, "w", encoding="utf-8") as f:
        json.dump(samenvatting, f, ensure_ascii=False)
    print(f"{pad3} geschreven")


if __name__ == "__main__":
    main()
