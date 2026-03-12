"""
Jefferson County Assessor Portal Adapter
Portal: https://propertysearch.jeffco.us/propertyrecordssearch/address
Platform: Angular SPA — split address fields, table results
Status: VERIFIED WORKING (probed 2026-03-12)

Result row cells: [address, city, zip, account, parcel, schedule, owner_name, type, mailing_address]
"""
from playwright.async_api import Page

PORTAL_URL = "https://propertysearch.jeffco.us/propertyrecordssearch/address"


async def lookup(page: Page, address: str, timeout_ms: int = 20000) -> dict | None:
    """
    Search Jefferson County assessor for owner name + mailing address.
    Address is split into house number + street name.
    Returns {"owner_name": str, "mailing_address": str} or None.
    """
    await page.goto(PORTAL_URL, timeout=timeout_ms, wait_until="networkidle")
    await page.wait_for_timeout(3000)

    # Split address into number + street (e.g. "4358 S ALKIRE ST" -> "4358", "S ALKIRE ST")
    import re
    parts = address.split(" ", 1)
    if len(parts) < 2 or not parts[0].isdigit():
        return None
    house_num, street_full = parts[0], parts[1]
    # Strip unit/apt info
    street_full = re.sub(r"\s+(?:unit|apt|suite|ste|#)\s*\S+.*$", "", street_full, flags=re.I).strip()
    # Strip city/state/zip (after comma)
    street_full = re.sub(r",.*$", "", street_full).strip()
    # Strip CO ZIP
    street_full = re.sub(r"\s+CO\s+\d{5}.*$", "", street_full, flags=re.I).strip()
    # Jefferson form wants ONLY the base street name — no pre-directional, no street type
    # e.g. "S ALKIRE ST" → "ALKIRE", "GARRISON ST" → "GARRISON", "W 77TH DR" → "77TH"
    _STREET_TYPES = r"\b(?:ST|AVE|DR|BLVD|LN|RD|WAY|CT|PL|CIR|LOOP|PKWY|HWY|TRL|TER|TERR|PT|RUN|ROW|WALK|PASS|PATH)\b"
    _PREDIRS = r"^(?:N|S|E|W|NE|NW|SE|SW)\s+"
    street_name = re.sub(_STREET_TYPES, "", street_full, flags=re.I).strip()
    street_name = re.sub(_PREDIRS, "", street_name, flags=re.I).strip()
    street_name = street_name.strip()

    num_input = await page.query_selector("#addressNumber")
    street_input = await page.query_selector("#streetName")
    if not num_input or not street_input:
        return None

    await num_input.fill(house_num)
    await street_input.fill(street_name)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(4000)

    rows = await page.query_selector_all("table tbody tr")
    if not rows:
        return None

    cells = await rows[0].query_selector_all("td")
    if len(cells) < 9:
        return None

    owner_name = (await cells[6].inner_text()).strip()
    mailing_address = (await cells[8].inner_text()).strip()

    if not owner_name:
        return None

    return {"owner_name": owner_name, "mailing_address": mailing_address}
