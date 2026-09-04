import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from classificatie import classificeer


def test_subsidie_functietitel_matcht_via_stam():
    # "subsidieadviseur" deelt geen woordstam met het brontrefwoord
    # "subsidieadvies" (advies/adviseur lopen uiteen) -- de generieke
    # "subsidie"-aanvulling moet dit toch vangen.
    r = classificeer("Senior Subsidieadviseur", None)
    assert r["subsidie_relevant"] is True
    assert "Subsidies" in r["subsidie_categorieen"]


def test_programmamanager_matcht_via_aanvulling():
    r = classificeer("Programmamanager Duurzaamheid", None)
    assert r["subsidie_relevant"] is True
    assert "Programma- & Projectcontrol" in r["subsidie_categorieen"]


def test_financial_controller_matcht_meerdere_categorieen():
    r = classificeer("Financial Controller", "Verantwoordelijk voor financiële verantwoording en reporting.")
    assert r["subsidie_relevant"] is True
    assert "Financial & Business Control" in r["subsidie_categorieen"]
    assert "Reporting" in r["subsidie_categorieen"]


def test_irrelevante_titel_wordt_niet_getagd():
    r = classificeer("SAP ABAP Developer", "Ontwikkelt maatwerk in ABAP voor S/4HANA.")
    assert r["subsidie_relevant"] is False
    assert r["subsidie_categorieen"] == ""
    assert r["subsidie_score"] == 0


def test_titel_match_weegt_zwaarder_dan_omschrijving_match():
    alleen_titel = classificeer("Compliance Officer", None)
    alleen_omschrijving = classificeer("Officer", "Houdt zich bezig met compliance.")
    assert alleen_titel["subsidie_score"] > alleen_omschrijving["subsidie_score"]


def test_lege_titel_is_geen_crash():
    r = classificeer(None, None)
    assert r["subsidie_relevant"] is False
