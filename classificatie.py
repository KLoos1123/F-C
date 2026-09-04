"""Herkent subsidie- en financial-control-gerelateerde opdrachten op trefwoorden.

Elke scraper levert opdrachten van een generiek tenderplatform aan (net als in
Scrappingtool-v2); dit tool voegt daar bovenop een relevantie-classificatie toe
voor de subsidiepraktijk van Profource, zodat de markt (vraag naar
subsidie-experts bij interim-opdrachten) gevolgd kan worden zonder alle
irrelevante IT/bouw/logistiek-opdrachten van diezelfde platformen kwijt te
raken -- niet-relevante rijen worden gewoon bewaard, alleen getagd.

TREFWOORDEN is de lijst die Profource tot nu toe handmatig gebruikte, per
categorie gegroepeerd voor leesbaarheid in het dashboard. Twee kleine
aanvullingen op die lijst (expliciet gemarkeerd) dekken de functietitel-vorm
van een paar samengestelde NL-woorden: "subsidieadviseur"/"subsidiemanager"
delen geen woordstam met "subsidieadvies"/"subsidiemanagement" (advies/
adviseur en management/manager lopen uiteen), dus zonder die aanvulling mist
substring-matching precies de functietitels waar het om gaat.
"""

TREFWOORDEN = {
    "Subsidies": [
        "subsidieadvies", "subsidiemanagement", "subsidieverwerving",
        "subsidieadministratie", "subsidierapportage", "staatssteun",
        "subsidie", "subsidies",  # aanvulling: dekt -adviseur/-manager/-administrateur etc.
    ],
    "Financial & Business Control": [
        "financial control", "business control", "accounting",
        "financiële administratie", "financiele administratie",
        "financiële verantwoording", "financiele verantwoording",
        "financiële procesverbetering", "financiele procesverbetering",
    ],
    "Compliance & Audit": [
        "compliance", "audit", "audits",
    ],
    "Programma- & Projectcontrol": [
        "programmamanagement", "programmamanager",  # aanvulling: management/manager lopen uiteen
        "project control",
    ],
    "Reporting": [
        "reporting",
    ],
}

# Vlakke (trefwoord -> categorie) lookup, langste eerst zodat bv. "subsidie"
# nooit vóór een specifiekere match als "subsidieadministratie" gerapporteerd wordt.
_ALLE_TREFWOORDEN = sorted(
    ((kw, cat) for cat, kws in TREFWOORDEN.items() for kw in kws),
    key=lambda p: len(p[0]),
    reverse=True,
)


def classificeer(titel, omschrijving=None):
    """Geeft (relevant, categorieen, gematchte_trefwoorden, score) terug.

    Titel-matches wegen zwaarder dan omschrijving-matches: de titel zegt iets
    over de rol zelf, de omschrijving kan het trefwoord ook terloops noemen.
    """
    titel_l = (titel or "").lower()
    oms_l = (omschrijving or "").lower()

    categorieen = set()
    gematcht = set()
    score = 0

    for kw, categorie in _ALLE_TREFWOORDEN:
        in_titel = kw in titel_l
        in_oms = kw in oms_l
        if not in_titel and not in_oms:
            continue
        gematcht.add(kw)
        categorieen.add(categorie)
        score += (2 if in_titel else 0) + (1 if in_oms else 0)

    return {
        "subsidie_relevant": bool(gematcht),
        "subsidie_categorieen": ", ".join(sorted(categorieen)),
        "subsidie_trefwoorden": ", ".join(sorted(gematcht)),
        "subsidie_score": score,
    }
