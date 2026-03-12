"""
Arapahoe County Assessor Portal Adapter
Portal: https://www.arapahoeco.gov/your_county/county_departments/assessor/property_search/
Platform: Custom CMS — residential search via POST form
Status: PROBED 2026-03-12 — search form is CMS-rendered, input not directly accessible via Playwright
Fallback: Uses SpatialEst hosted instance if available

Notes:
  The arapahoeco.gov property search page uses a CMS-generated form that is not
  accessible via standard Playwright selectors. The input labeled "Search Residential,
  Commercial, Ag and Vacant" is inside a CMS freeform block. Direct URL approach used.
"""
from playwright.async_api import Page

PORTAL_URL = "https://www.arapahoeco.gov/your_county/county_departments/assessor/property_search/index.php"
SEARCH_URL = "https://www.arapahoeco.gov/your_county/county_departments/assessor/property_search/residential_commercial_search.php"


async def lookup(page: Page, address: str, timeout_ms: int = 20000) -> dict | None:
    """
    Search Arapahoe County assessor for owner name + mailing address.
    Returns {"owner_name": str, "mailing_address": str} or None.
    """
    import re

    # Try direct residential search page
    try:
        await page.goto(SEARCH_URL, timeout=timeout_ms, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # Find address input
        inp = await page.query_selector("input[type=text][name*='address'], input[type=text][id*='address'], input[placeholder*='ddress']")
        if not inp:
            # Try any visible text input
            inputs = await page.query_selector_all("input[type=text]:visible")
            inp = inputs[0] if inputs else None

        if not inp:
            return None

        # Strip unit info
        clean = re.sub(r"\s+(?:unit|apt|suite|ste|#)\s*\S+.*$", "", address, flags=re.I).strip()
        await inp.fill(clean)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(4000)

        # Parse results table
        rows = await page.query_selector_all("table tbody tr, table tr:not(:first-child)")
        if not rows:
            return None

        cells = await rows[0].query_selector_all("td")
        if len(cells) < 2:
            return None

        # Try common column layouts
        owner_name = ""
        mailing = ""
        for i, cell in enumerate(cells):
            text = (await cell.inner_text()).strip()
            if text and not owner_name and len(text) > 3 and not text.replace(" ", "").isdigit():
                owner_name = text
            if i > 0 and text and text != owner_name and len(text) > 5:
                mailing = text

        if owner_name:
            return {"owner_name": owner_name, "mailing_address": mailing}
        return None

    except Exception:
        return None
