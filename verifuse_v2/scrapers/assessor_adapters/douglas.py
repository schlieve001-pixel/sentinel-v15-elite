"""
Douglas County Assessor Portal Adapter
Portal: https://www.douglas.co.us/assessor/#/
Platform: Angular SPA — single unified search box
Status: PROBED 2026-03-12 — search input renders, placeholder "Search County Properties"

Notes:
  Douglas County uses a custom Angular SPA. The main search accepts address,
  owner name, parcel ID in one field. Results are rendered as list cards.
  Owner name + mailing address are visible in the property detail panel.
"""
from playwright.async_api import Page
import re

PORTAL_URL = "https://www.douglas.co.us/assessor/#/"


async def lookup(page: Page, address: str, timeout_ms: int = 20000) -> dict | None:
    """
    Search Douglas County assessor for owner + mailing address.
    Returns {"owner_name": str, "mailing_address": str} or None.
    """
    await page.goto(PORTAL_URL, timeout=timeout_ms, wait_until="networkidle")
    await page.wait_for_timeout(5000)  # Angular needs time to bootstrap

    # Dismiss any alert/modal
    dismiss = await page.query_selector("button:has-text('OK'), button:has-text('Close'), button:has-text('Continue'), .modal button")
    if dismiss:
        await dismiss.click()
        await page.wait_for_timeout(1000)

    inp = await page.query_selector("input[placeholder*='123 Main'], input[placeholder*='Search County'], .search-bar")
    if not inp:
        inputs = await page.query_selector_all("input[type=text]:not([type=hidden])")
        # Pick the last input (global site search is first, property search is last)
        inp = inputs[-1] if inputs else None
    if not inp:
        return None

    clean = re.sub(r"\s+(?:unit|apt|suite|ste|#)\s*\S+", "", address, flags=re.I)
    clean = re.sub(r",.*$", "", clean).strip()
    clean = re.sub(r"\s+CO\s+\d{5}.*$", "", clean, flags=re.I).strip()

    await inp.fill(clean)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(5000)

    # Click first result card
    result_cards = await page.query_selector_all(".result-card, .search-result, .property-card, [class*='result']")
    if result_cards:
        await result_cards[0].click()
        await page.wait_for_timeout(3000)

    # Extract from detail panel
    detail_text = await page.inner_text("body")
    owner_match = re.search(r"(?:Owner|OWNER)[:\s]+([A-Z][A-Z\s,\.&]{3,80})", detail_text)
    mailing_match = re.search(r"(?:Mailing|MAILING|Mailing Address)[:\s]+([0-9][^\n]{5,100})", detail_text)

    owner_name = owner_match.group(1).strip() if owner_match else ""
    mailing = mailing_match.group(1).strip() if mailing_match else ""

    if not owner_name:
        return None

    return {"owner_name": owner_name, "mailing_address": mailing}
