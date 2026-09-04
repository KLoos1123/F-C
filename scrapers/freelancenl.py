"""freelance.nl - freelance opdrachten.

Twee modi:
  1. Ingelogd (voorkeur): als FREELANCE_EMAIL/FREELANCE_WACHTWOORD gezet zijn,
     logt hij in op mijn.freelance.nl en gebruikt de `search`-GraphQL. Die geeft
     meer velden dan de publieke API: reactietermijn (deadline), tarief en uren.
  2. Publiek (fallback): zonder inlog laadt hij www.freelance.nl en bevraagt de
     publieke `publicSearch`-GraphQL. Minder velden (geen deadline/tarief).

De site blokkeert kale requests (WAF geeft 403), daarom draait alles binnen een
echte browsercontext.
"""

import os
import re
import json
from playwright.sync_api import sync_playwright

BRON = "freelance.nl"

APP = "https://www.freelance.nl"
MIJN = "https://mijn.freelance.nl"
API = f"{APP}/public-api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# publieke query (fallback)
PUBLIC_QUERY = """
query PublicSearch($query: SearchQueryInput!, $sortMethod: String!, $limit: Int!, $offset: Int!) {
  publicSearch(query: $query, sortMethod: $sortMethod, limit: $limit, offset: $offset) {
    count
    results {
      assignment {
        title
        place
        hoursFrom
        hoursTo
        id
        status
        publishAt
      }
    }
  }
}
"""


def _parse_graphql(tekst):
    """freelance's ingelogde endpoint kan multipart/mixed teruggeven (Apollo
    @defer): een body die begint met '--graphql' met JSON-delen ertussen.
    Deze helper haalt het eerste JSON-object met een 'data'-veld eruit; valt
    terug op gewone json.loads voor een kale JSON-body."""
    t = tekst.lstrip()
    if t.startswith("{"):
        return json.loads(t)
    # multipart: zoek per deel het JSON-blok
    for deel in tekst.split("--graphql"):
        deel = deel.strip()
        i = deel.find("{")
        if i == -1:
            continue
        try:
            obj = json.loads(deel[i:])
        except Exception:
            continue
        if isinstance(obj, dict) and ("data" in obj or "incremental" in obj):
            return obj
    raise ValueError("geen JSON in graphql-response")


def _slug(titel):
    s = (titel or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _url(aid, titel):
    slug = _slug(titel)
    return f"{APP}/opdracht/{aid}-{slug}" if slug else f"{APP}/opdracht/{aid}"


def _uren(a):
    if a.get("hoursFrom") or a.get("hoursTo"):
        return f"{a.get('hoursFrom') or '?'}-{a.get('hoursTo') or '?'}"
    return None


# ---------------------------------------------------------------- ingelogd

def _accept_cookies(page):
    for txt in ["Accepteer alles", "Akkoord", "Accept", "Alles accepteren"]:
        try:
            b = page.query_selector(f"button:has-text('{txt}')")
            if b:
                b.click()
                page.wait_for_timeout(600)
                return
        except Exception:
            pass


def _uit_search(a):
    """Assignment uit de ingelogde `search`-query."""
    aid = a.get("id")
    titel = a.get("title") or ""
    comp = (a.get("company") or {}).get("name")
    # "Unknown company" is de placeholder voor niet-onthulde opdrachtgevers
    if comp and comp.strip().lower() == "unknown company":
        comp = None
    return {
        "tender_id": str(aid),
        "nummer": str(aid),
        "titel": titel,
        "organisatie": comp,
        "status": a.get("status"),
        "deadline": a.get("applicationDeadlineDate"),
        "publicatiedatum": a.get("publishAt"),
        "locatie": a.get("place") or None,
        "uren_per_week": _uren(a),
        # omschrijving zit al in de ingelogde search-respons; wordt door run.py
        # apart bewaard (niet in de hoofdtabel). Juist hier waardevol: de
        # opdrachtgever is verborgen, dus deze tekst voedt straks de AI-inschatting.
        "omschrijving": a.get("description") or None,
        "url": _url(aid, titel),
    }


def _ingelogd(email, wachtwoord):
    """Logt in en haalt alle opdrachten via de ingelogde search-query.

    Vangt eerst het live search-verzoek af (URL + headers) en herhaalt dat
    daarna met oplopende offset, zodat we niet afhankelijk zijn van een
    hardgecodeerde endpoint-URL.
    """
    rijen = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="nl-NL")
        page = ctx.new_page()

        vangst = {}  # url, headers, body van het eerste search-verzoek

        def handler(r):
            try:
                if "/graphql" not in r.url or r.request.method != "POST":
                    return
                pd = r.request.post_data or ""
                if '"operationName":"search"' in pd and "vars" not in vangst:
                    vangst["url"] = r.request.url
                    vangst["headers"] = dict(r.request.headers)
                    vangst["vars"] = json.loads(pd)
                    vangst["body"] = r.text()
            except Exception:
                pass

        page.on("response", handler)

        page.goto(f"{MIJN}/inloggen", timeout=60000, wait_until="domcontentloaded")
        _accept_cookies(page)
        page.wait_for_timeout(1200)
        page.fill("input[name='email']", email)
        page.fill("input[name='password']", wachtwoord)
        (page.query_selector("button[type='submit']")
         or page.query_selector("button:has-text('Inloggen')")).click()
        page.wait_for_timeout(6000)
        if "inloggen" in page.url:
            raise RuntimeError("inloggen mislukt")

        page.goto(f"{MIJN}/opdracht-vinden/zoeken?resultaten=36",
                  timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)

        if "vars" not in vangst:
            raise RuntimeError("search-verzoek niet afgevangen")

        # het ingelogde endpoint begrenst limit op 36
        limit = 36
        basis = vangst["vars"]
        query = basis.get("query")
        variabelen = dict(basis.get("variables") or {})
        variabelen["limit"] = limit

        # behoud de originele headers (incl. accept: multipart/mixed voor @defer);
        # _parse_graphql haalt de JSON uit een multipart-body.
        headers = {k: v for k, v in vangst["headers"].items()
                   if k.lower() not in ("content-length", "host", "accept-encoding")}
        headers["content-type"] = "application/json"

        offset = 0
        totaal = None
        while True:
            variabelen["offset"] = offset
            payload = {"operationName": "search", "variables": variabelen, "query": query}
            resp = ctx.request.post(vangst["url"], data=json.dumps(payload),
                                    headers=headers, timeout=30000)
            if not resp.ok:
                raise RuntimeError(f"search gaf {resp.status}")
            data = _parse_graphql(resp.text())
            if data.get("errors"):
                raise RuntimeError(f"search-fout: {data['errors'][0].get('message')}")
            zoek = ((data.get("data") or {}).get("search")) or {}
            if totaal is None:
                totaal = zoek.get("count") or 0
                print(f"  {totaal} opdrachten beschikbaar (ingelogd)")
            blok = zoek.get("results") or []
            if not blok:
                break
            for r in blok:
                a = r.get("assignment") or {}
                if a.get("id"):
                    rijen.append(_uit_search(a))
            offset += limit
            if offset >= (totaal or 0):
                break

        browser.close()
    print(f"  {len(rijen)} opdrachten opgehaald (ingelogd)")
    return rijen


# ---------------------------------------------------------------- publiek

def _uit_public(a):
    aid = a.get("id")
    titel = a.get("title") or ""
    return {
        "tender_id": str(aid),
        "nummer": str(aid),
        "titel": titel,
        "organisatie": None,
        "status": a.get("status"),
        "deadline": None,
        "publicatiedatum": a.get("publishAt"),
        "locatie": a.get("place") or None,
        "uren_per_week": _uren(a),
        "url": _url(aid, titel),
    }


def _zoek_publiek(ctx, offset, limit):
    payload = {
        "query": PUBLIC_QUERY,
        "variables": {
            "query": {"onLocation": False},
            "sortMethod": "newest",
            "limit": limit,
            "offset": offset,
        },
    }
    resp = ctx.request.post(
        API,
        data=json.dumps(payload),
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "referer": f"{APP}/opdrachten",
        },
        timeout=30000,
    )
    if not resp.ok:
        raise RuntimeError(f"public-api gaf {resp.status}")
    return resp.json()


def _publiek():
    rijen = []
    limit = 100
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="nl-NL")
        page = ctx.new_page()
        page.goto(f"{APP}/opdrachten", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        offset = 0
        totaal = None
        while True:
            data = _zoek_publiek(ctx, offset, limit)
            zoek = (data.get("data") or {}).get("publicSearch") or {}
            if totaal is None:
                totaal = zoek.get("count") or 0
                print(f"  {totaal} opdrachten beschikbaar (publiek)")
            blok = zoek.get("results") or []
            if not blok:
                break
            for r in blok:
                a = r.get("assignment") or {}
                if a.get("id"):
                    rijen.append(_uit_public(a))
            offset += limit
            if offset >= (totaal or 0):
                break
        browser.close()
    print(f"  {len(rijen)} opdrachten opgehaald (publiek)")
    return rijen


# ---------------------------------------------------------------- publiek entrypoint

def haal_op():
    """Wordt aangeroepen door run.py. Geeft een lijst dicts terug.

    Probeert ingelogd (meer velden); valt terug op de publieke API als er geen
    inloggegevens zijn of het inloggen faalt.
    """
    email = os.environ.get("FREELANCE_EMAIL")
    wachtwoord = os.environ.get("FREELANCE_WACHTWOORD")
    if email and wachtwoord:
        # twee pogingen; de ingelogde modus geeft deadlines + omschrijvingen.
        for poging in range(2):
            try:
                return _ingelogd(email, wachtwoord)
            except Exception as e:
                # NOOIT de volledige exception loggen: een Playwright-request-fout
                # bevat de request-headers incl. auth-cookies/tokens. Alleen het type.
                print(f"  ingelogd poging {poging + 1} mislukt ({type(e).__name__})")
        print("  val terug op publiek (geen omschrijvingen)")
    return _publiek()
