"""
Boulder County Assessor Portal Adapter
Portal: https://maps.bouldercounty.org/boco/PropertySearch/
Platform: Esri/ArcGIS Web AppBuilder SPA
Status: PROBED 2026-03-12 — search input found, uses Esri search widget

Notes:
  Boulder uses Esri ArcGIS Web AppBuilder. The search widget renders a text input
  with placeholder "Type your search here..." — accepts address, owner name,
  parcel ID, or subdivision. Results appear as a feature list in the map panel.
  Owner/mailing data extracted from the property info popup panel.
"""
from playwright.async_api import Page
import re

PORTAL_URL = "https://maps.bouldercounty.org/boco/PropertySearch/"


async def lookup(page: Page, address: str, timeout_ms: int = 20000) -> dict | None:
    """
    Search Boulder County assessor via ArcGIS for owner + mailing address.
    Returns {"owner_name": str, "mailing_address": str} or None.
    """
    await page.goto(PORTAL_URL, timeout=timeout_ms, wait_until="networkidle")
    await page.wait_for_timeout(6000)  # ArcGIS takes longer to fully render

    inp = await page.query_selector("input[placeholder='Type your search here...']")
    if not inp:
        inputs = await page.query_selector_all("input[type=text]")
        inp = inputs[0] if inputs else None
    if not inp:
        return None

    # Clean address
    clean = re.sub(r"\s+(?:unit|apt|suite|ste|#)\s*\S+", "", address, flags=re.I)
    clean = re.sub(r",.*$", "", clean).strip()
    clean = re.sub(r"\s+CO\s+\d{5}.*$", "", clean, flags=re.I).strip()

    await inp.fill(clean)
    await page.wait_for_timeout(2000)

    # ArcGIS search shows a dropdown of suggestions — select first
    suggestions = await page.query_selector_all(".searchMenu li, .searchSuggestions li, [class*='suggestion']")
    if suggestions:
        await suggestions[0].click()
        await page.wait_for_timeout(4000)
    else:
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(5000)

    # Get the popup/info panel text
    popup = await page.query_selector(".esriPopup, .popup-content, .feature-info, .infoWindow, [class*='popup']")
    if popup:
        popup_text = await popup.inner_text()
    else:
        # Fall back to full page text
        popup_text = await page.inner_text("body")

    # Parse owner + mailing from property info
    owner_match = re.search(r"(?:Owner|OWNER)[:\s]+([A-Z][A-Z\s,\.&]{3,80})", popup_text)
    mailing_match = re.search(r"(?:Mailing|MAILING|Mail Addr)[:\s]+([0-9][^\n]{5,100})", popup_text)

    owner_name = owner_match.group(1).strip() if owner_match else ""
    mailing = mailing_match.group(1).strip() if mailing_match else ""

    if not owner_name:
        return None

    return {"owner_name": owner_name, "mailing_address": mailing}
