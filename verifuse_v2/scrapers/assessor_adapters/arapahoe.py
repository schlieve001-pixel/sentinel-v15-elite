"""
Arapahoe County Assessor Portal Adapter
Portal: https://parcelsearch.arapahoegov.com/
Platform: ASP.NET — split address form (number + street name), links to detail
Status: VERIFIED URL (probed 2026-03-12) — correct portal is parcelsearch.arapahoegov.com

Form:
  #txtAddressNumFrom = house number
  #txtAddressStreet  = street name (no suffix, min 3 chars)
Results: links to PPINum.aspx?PPINum=<id> with full owner/mailing on detail page.
"""
from playwright.async_api import Page
import re

PORTAL_URL = "https://parcelsearch.arapahoegov.com/"


async def lookup(page: Page, address: str, timeout_ms: int = 20000) -> dict | None:
    """
    Search Arapahoe County parcel search for owner + mailing address.
    Returns {"owner_name": str, "mailing_address": str} or None.
    """
    await page.goto(PORTAL_URL, timeout=timeout_ms, wait_until="networkidle")
    await page.wait_for_timeout(2000)

    # Split address into number + street
    parts = address.split(" ", 1)
    if len(parts) < 2 or not parts[0].isdigit():
        return None
    house_num = parts[0]
    street_full = parts[1]

    # Strip unit/apt, city/state/zip
    street_full = re.sub(r"\s+(?:unit|apt|suite|ste|#)\s*\S+.*$", "", street_full, flags=re.I).strip()
    street_full = re.sub(r",.*$", "", street_full).strip()
    street_full = re.sub(r"\s+CO\s+\d{5}.*$", "", street_full, flags=re.I).strip()

    # Strip pre-directional + street type — form wants base name only
    _STREET_TYPES = r"\b(?:ST|AVE|DR|BLVD|LN|RD|WAY|CT|PL|CIR|LOOP|PKWY|HWY|TRL|TER|TERR|PT)\b"
    _PREDIRS = r"^(?:N|S|E|W|NE|NW|SE|SW)\s+"
    street_name = re.sub(_STREET_TYPES, "", street_full, flags=re.I).strip()
    street_name = re.sub(_PREDIRS, "", street_name, flags=re.I).strip()

    num_inp = await page.query_selector("#txtAddressNumFrom, input[name='txtAddressNumFrom']")
    street_inp = await page.query_selector("#txtAddressStreet, input[name='txtAddressStreet']")
    if not num_inp or not street_inp:
        return None

    await num_inp.fill(house_num)
    await street_inp.fill(street_name)

    submit = await page.query_selector("input[type='submit'], button[type='submit']")
    if submit:
        await submit.click()
    else:
        await page.keyboard.press("Enter")
    await page.wait_for_timeout(4000)

    # Results: links to detail page
    result_links = await page.query_selector_all("a[href*='PPINum']")
    if not result_links:
        result_links = await page.query_selector_all("table tbody tr td a")
    if not result_links:
        return None

    await result_links[0].click()
    await page.wait_for_timeout(4000)

    detail_text = await page.inner_text("body")

    owner_match = re.search(
        r"(?:Owner|OWNER)\s*(?:Name|NAME)?[:\s]+([A-Z][A-Z\s,\.&]{3,80})",
        detail_text,
    )
    mailing_match = re.search(
        r"(?:Mailing|MAILING)\s*(?:Address|ADDRESS)?[:\s]+([0-9][^\n]{5,100})",
        detail_text,
    )

    owner_name = owner_match.group(1).strip() if owner_match else ""
    mailing = mailing_match.group(1).strip() if mailing_match else ""

    # Fallback: scan table rows for label/value pairs
    if not owner_name:
        rows = await page.query_selector_all("table tr")
        for row in rows:
            cells = await row.query_selector_all("td")
            if len(cells) >= 2:
                label = (await cells[0].inner_text()).strip().lower()
                value = (await cells[1].inner_text()).strip()
                if "owner" in label and value:
                    owner_name = value
                elif "mailing" in label and value:
                    mailing = value

    if not owner_name:
        return None

    return {"owner_name": owner_name, "mailing_address": mailing}
