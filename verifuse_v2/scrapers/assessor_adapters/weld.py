"""
Weld County Assessor Portal Adapter
Portal: https://apps.weld.gov/propertyportal/
Platform: Custom ASP-style web app — simple form + table results + detail page
Status: VERIFIED WORKING (probed 2026-03-12) — search form functional,
        results render as table, need to navigate to detail for owner/mailing

Notes:
  Weld County has a clean property portal at apps.weld.gov. The search field
  (name=searchInput) accepts address, owner name, or account number.
  Results show in a table (Account, Parcel, Location, Subdivision).
  Clicking a result row navigates to a detail page with owner + mailing info.
"""
from playwright.async_api import Page
import re

PORTAL_URL = "https://apps.weld.gov/propertyportal/"


async def lookup(page: Page, address: str, timeout_ms: int = 20000) -> dict | None:
    """
    Search Weld County property portal for owner + mailing address.
    Returns {"owner_name": str, "mailing_address": str} or None.
    """
    await page.goto(PORTAL_URL, timeout=timeout_ms, wait_until="networkidle")
    await page.wait_for_timeout(3000)

    inp = await page.query_selector("input[name=searchInput]")
    if not inp:
        return None

    # Clean address for search
    clean = re.sub(r"\s+(?:unit|apt|suite|ste|#)\s*\S+", "", address, flags=re.I)
    clean = re.sub(r",.*$", "", clean).strip()
    clean = re.sub(r"\s+CO\s+\d{5}.*$", "", clean, flags=re.I).strip()

    await inp.fill(clean)

    btn = await page.query_selector("input[type=submit], .buttonInput, button[type=submit]")
    if btn:
        await btn.click()
    else:
        await page.keyboard.press("Enter")
    await page.wait_for_timeout(4000)

    # Click first result row link (Account number link)
    result_links = await page.query_selector_all("table td a, .results a")
    if not result_links:
        return None

    await result_links[0].click()
    await page.wait_for_timeout(4000)

    # Parse detail page for owner + mailing
    detail_text = await page.inner_text("body")
    owner_match = re.search(r"(?:Owner|OWNER\s*NAME)[:\s]+([A-Z][A-Z\s,\.&]{3,80})", detail_text)
    mailing_match = re.search(r"(?:Mailing|MAILING\s*ADDRESS)[:\s]+([0-9][^\n]{5,100})", detail_text)

    # Also try table-based layout
    if not owner_match:
        owner_match = re.search(r"([A-Z]{2,}\s+[A-Z]{2,}(?:\s+[A-Z]{2,})?)\s*\n.*(?:PO BOX|[0-9]+\s+[A-Z])", detail_text)

    owner_name = owner_match.group(1).strip() if owner_match else ""
    mailing = mailing_match.group(1).strip() if mailing_match else ""

    # Fallback: look for table rows with label/value pairs
    if not owner_name:
        rows = await page.query_selector_all("table tr")
        for row in rows:
            cells = await row.query_selector_all("td, th")
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
