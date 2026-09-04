"""Mercell Source-to-Contract.

Twee ingangen:
  1. Per organisatie waar het account bij hoort (via de nx-current-domainorganizationid header)
  2. Alle gepubliceerde tenders (/today)

Beide leveren tender-ID's uit dezelfde nummerreeks, dus overlap wordt vanzelf
gededupliceerd op (bron, tender_id).
"""

import os
import urllib3
import requests
from playwright.sync_api import sync_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BRON = "mercell"

API = "https://api.s2c.mercell.com/api/v1"
ORGANIZATION_ID = "2666"  # Profource
FOLDER_GUID = "a14e5f3c-bf4f-4dd6-9f7a-995eddd63ada"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ---------------------------------------------------------------- login

def _token():
    email = os.environ.get("MERCELL_EMAIL")
    wachtwoord = os.environ.get("MERCELL_WACHTWOORD")
    if not email or not wachtwoord:
        raise RuntimeError("MERCELL_EMAIL of MERCELL_WACHTWOORD ontbreekt")

    token = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()

        def onderschep(request):
            nonlocal token
            if "api.s2c.mercell.com" in request.url and not token:
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    token = auth.replace("Bearer ", "")

        page.on("request", onderschep)

        # Twee-staps login: eerst e-mail, dan verschijnt pas het wachtwoordveld.
        page.goto("https://s2c.mercell.com/", timeout=60000)
        page.wait_for_selector("input[name='Username']", timeout=30000)
        page.fill("input[name='Username']", email)
        page.click("#loginBtn")

        page.wait_for_selector("input[name='Password']", state="visible", timeout=30000)
        page.wait_for_timeout(1000)
        page.fill("input[name='Password']", wachtwoord)
        page.click("#loginBtn")
        page.wait_for_timeout(8000)

        if not token:
            page.goto("https://s2c.mercell.com/today", timeout=60000)
            page.wait_for_timeout(10000)

        if not token:
            try:
                page.screenshot(path="debug_mercell_login.png", full_page=True)
            except Exception:
                pass

        browser.close()

    if not token:
        raise RuntimeError("Geen token onderschept, zie debug_mercell_login.png")

    return token


def _headers(token, domain_org_id=None):
    h = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "nx-current-organizationid": ORGANIZATION_ID,
        "nx-is-user-buyer-for-current-domain": "false",
        "origin": "https://s2c.mercell.com",
        "x-requested-with": "XMLHttpRequest",
        "user-agent": UA,
    }
    if domain_org_id is not None:
        h["nx-current-domainorganizationid"] = str(domain_org_id)
    return h


# ---------------------------------------------------------------- ophalen

def _organisaties(token):
    r = requests.get(
        f"{API}/User/GetCurrentUserDomainOrganizationsByOrganizationId",
        params={"organizationId": ORGANIZATION_ID},
        headers=_headers(token),
        verify=False,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _org_tenders(token, domain_org_id):
    payload = {
        "FolderGuid": FOLDER_GUID,
        "SearchParameters": {
            "StartIndex": 1,
            "EndIndex": 200,
            "Keywords": [],
            "PropertyFilters": [],
            "OrderAscending": False,
            "OrderColumn": "Id",
        },
    }
    r = requests.post(
        f"{API}/Folder/GetTendersFolderContentBySpecified",
        headers=_headers(token, domain_org_id),
        json=payload,
        verify=False,
        timeout=30,
    )
    if r.status_code != 200:
        print(f"    fout {r.status_code}: {r.text[:100]}")
        return []
    return r.json().get("CurrentPageResults") or []


def _gepubliceerd(token, blok=200):
    """Haalt alle gepubliceerde tenders op, gepagineerd."""
    alles = []
    start = 1
    totaal = None

    while True:
        payload = {
            "SearchParameters": {
                "StartIndex": start,
                "EndIndex": start + blok - 1,
                "Keywords": [],
                "PropertyFilters": [],
                "SearchText": "",
                "OrderAscending": False,
                "OrderColumn": "PublicationDate",
                "SearchProperty": {
                    "PropertyDisplayName": "str_Today_opened",
                    "PropertyName": "Status",
                    "PropertyValue": "1",
                },
            }
        }
        r = requests.post(
            f"{API}/PublishedTender/GetPublishedTendersBySpecified",
            headers=_headers(token, 19377),
            json=payload,
            verify=False,
            timeout=60,
        )
        if r.status_code != 200:
            print(f"    fout {r.status_code}: {r.text[:100]}")
            break

        d = r.json()
        if totaal is None:
            totaal = d.get("ResultsCount", 0)
            print(f"    {totaal} gepubliceerde tenders beschikbaar")

        pagina = d.get("CurrentPageResults") or []
        if not pagina:
            break

        alles.extend(pagina)
        start += blok
        if start > (totaal or 0):
            break

    return alles


# ---------------------------------------------------------------- normaliseren

def _uit_org(t, org_naam):
    tid = t.get("Id")
    return {
        "tender_id": str(tid),
        "nummer": t.get("DisplayNumber"),
        "titel": t.get("Name"),
        "organisatie": t.get("BuyerOrganizationDisplayName") or org_naam,
        "status": t.get("DisplayStatus"),
        "deadline": t.get("OfferEndDate"),
        "publicatiedatum": t.get("OfferStartDate"),
        "url": f"https://s2c.mercell.com/tender/{tid}/supplier",
    }


def _uit_gepubliceerd(t):
    tid = t.get("TenderId")
    return {
        "tender_id": str(tid),
        "nummer": t.get("SpecialNumber") or None,
        "titel": t.get("TenderName"),
        "organisatie": t.get("OrganizationName"),
        "status": "Open",
        "deadline": t.get("Deadline"),
        "publicatiedatum": t.get("PublicationDate"),
        "url": f"https://s2c.mercell.com/today/{tid}",
    }


# ---------------------------------------------------------------- publiek

def haal_op():
    """Wordt aangeroepen door run.py. Geeft een lijst dicts terug."""
    # De browser-login is af en toe flakey; twee pogingen voordat we opgeven.
    token = None
    for poging in range(2):
        try:
            token = _token()
            break
        except Exception as e:
            print(f"  login-poging {poging + 1} mislukt ({type(e).__name__})")
    if not token:
        raise RuntimeError("inloggen mislukt na 2 pogingen")
    print("  ingelogd")

    rijen = []

    orgs = _organisaties(token)
    print(f"  {len(orgs)} organisaties")
    for org in orgs:
        naam = org.get("Name")
        tenders = _org_tenders(token, org.get("DomainOrganizationId"))
        if tenders:
            print(f"    {naam}: {len(tenders)}")
        rijen.extend(_uit_org(t, naam) for t in tenders)

    print("  gepubliceerde tenders")
    rijen.extend(_uit_gepubliceerd(t) for t in _gepubliceerd(token))
    print(rijen)
    return rijen
