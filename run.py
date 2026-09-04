"""Draait alle scrapers, classificeert elke opdracht op subsidie-relevantie en
schrijft het resultaat naar de gedeelde database.

Zelfde opzet als Scrappingtool-v2/run.py: een scraper die crasht stopt de rest
niet, maar de run eindigt wel in een fout zodat je het in GitHub Actions ziet
-- tenzij het aantal mislukte bronnen binnen MAX_MISLUKT blijft (login-scrapers
zijn af en toe flakey; pas bij brede uitval is er echt iets structureel mis).
"""
import os
import csv
import sys
import subprocess
import traceback
from datetime import datetime, timezone, timedelta

MAX_MISLUKT = 3

import db
import beschrijvingen
import classificatie
from scrapers import (mercell, flextender, hero, striive, freelancenl, ns,
                      stedin, tenderned, inhuurdesk_regio, gelderland,
                      flexwestbrabant, magnit, stedin_vms, opdrachtoverheid)


SCRAPERS = [
    mercell,
    flextender,
    hero,
    striive,
    freelancenl,
    ns,
    stedin,
    tenderned,
    inhuurdesk_regio,
    gelderland,
    flexwestbrabant,
    magnit,
    stedin_vms,
    opdrachtoverheid,
    # tendernet volgt zodra de precieze bron/URL is bevestigd.
]

CSV_ALLES = "tenders.csv"
CSV_NIEUW = "tenders_nieuw.csv"
CSV_RELEVANT = "tenders_subsidies.csv"


def exporteer(rijen, bestand):
    if not rijen:
        print(f"  {bestand}: niets te schrijven")
        return
    kolommen = rijen[0].keys()
    with open(bestand, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=kolommen, delimiter=";")
        w.writeheader()
        w.writerows(dict(r) for r in rijen)
    print(f"  {bestand}: {len(rijen)} rijen")


def main():
    startmoment = datetime.now(timezone.utc) - timedelta(seconds=5)
    alles = []
    mislukt = []

    for scraper in SCRAPERS:
        naam = scraper.BRON
        print(f"\n=== {naam} ===")
        try:
            rijen = scraper.haal_op()
            for r in rijen:
                r["bron"] = naam
            print(f"  {len(rijen)} rijen opgehaald")
            alles.extend(rijen)
        except Exception as e:
            print(f"  MISLUKT: {e}")
            traceback.print_exc()
            mislukt.append(naam)

    if not alles:
        print("\nNiets opgehaald, database niet aangepast.")
        sys.exit(1)

    print("\n=== classificatie ===")
    aantal_relevant = 0
    for r in alles:
        classificatie_resultaat = classificatie.classificeer(
            r.get("titel"), r.get("omschrijving"))
        r.update(classificatie_resultaat)
        if classificatie_resultaat["subsidie_relevant"]:
            aantal_relevant += 1
    print(f"  {aantal_relevant}/{len(alles)} opdrachten subsidie-relevant getagd")

    print("\n=== database ===")
    nieuw, totaal = db.opslaan(alles)
    print(f"  {nieuw} nieuw, {totaal} totaal")
    for r in db.per_bron():
        print(f"  {r['bron']}: {r['aantal']}")

    # Omschrijvingen apart bewaren (hoofdtabel blijft licht). Scrapers die een
    # 'omschrijving' meegeven voeden zo zowel de classificatie hierboven als
    # de latere AI-matching met beschikbare cv's (buiten scope van dit tool).
    print("\n=== omschrijvingen ===")
    try:
        met_oms = [r for r in alles if r.get("omschrijving")]
        opgeslagen = beschrijvingen.opslaan(met_oms)
        print(f"  {opgeslagen} omschrijvingen bewaard")
        for r in beschrijvingen.per_bron():
            print(f"  {r[0]}: {r[1]}")
    except Exception as e:
        print(f"  omschrijvingen MISLUKT: {e}")

    print("\n=== export ===")
    alle = db.alle_rijen()
    exporteer(alle, CSV_ALLES)
    exporteer(db.nieuw_sinds(startmoment.isoformat(timespec="seconds")), CSV_NIEUW)
    exporteer([r for r in alle if r["subsidie_relevant"]], CSV_RELEVANT)

    print("\n=== dashboard ===")
    subprocess.run(["python", "dashboard.py"], check=True)

    if mislukt:
        melding = f"Mislukte bronnen ({len(mislukt)}): {', '.join(mislukt)}"
        print(f"\n{melding}")
        samenvatting = os.environ.get("GITHUB_STEP_SUMMARY")
        if samenvatting:
            try:
                with open(samenvatting, "a", encoding="utf-8") as f:
                    f.write(f"\n⚠️ {melding}\n")
            except Exception:
                pass
        if len(mislukt) > MAX_MISLUKT:
            print(f"  meer dan {MAX_MISLUKT} bronnen mislukt -> run faalt")
            sys.exit(1)
        print(f"  binnen tolerantie ({len(mislukt)}/{MAX_MISLUKT}); run blijft groen")

    print("\nKlaar.")


if __name__ == "__main__":
    main()
