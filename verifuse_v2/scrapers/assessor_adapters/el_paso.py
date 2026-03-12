"""
El Paso County Assessor Portal Adapter
Portal: https://property.spatialest.com/co/elpaso/#/
Platform: SpatialEst SPA (same as Denver)
Status: PROBED 2026-03-12 — same platform as Denver, identical adapter logic

Notes:
  El Paso County uses the same SpatialEst platform as Denver.
  Address format rules same as denver.py — strip unit/city/state before search.
"""
from playwright.async_api import Page
import re

PORTAL_URL = "https://property.spatialest.com/co/elpaso/#/"


async def lookup(page: Page, address: str, timeout_ms: int = 20000) -> dict | None:
    """
    Search El Paso County assessor via SpatialEst for owner + mailing address.
    Returns {"owner_name": str, "mailing_address": str} or None.
    """
    await page.goto(PORTAL_URL, timeout=timeout_ms, wait_until="networkidle")
    await page.wait_for_timeout(4000)

    dismiss = await page.query_selector("button:has-text('I Understand'), button:has-text('OK'), button:has-text('Accept')")
    if dismiss:
        await dismiss.click()
        await page.wait_for_timeout(1000)

    inp = await page.query_selector("#primary_search")
    if not inp:
        return None

    clean = re.sub(r"\s+(?:unit|apt|suite|ste|#)\s*\S+", "", address, flags=re.I)
    clean = re.sub(r",.*$", "", clean).strip()
    clean = re.sub(r"\s+CO\s+\d{5}.*$", "", clean, flags=re.I).strip()
    tokens = clean.split()[:5]
    clean = " ".join(tokens)

    await inp.fill(clean)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(5000)

    result_items = await page.query_selector_all(".search-result-item, .result-item, ul.results li, [ng-repeat*='result']")
    if not result_items:
        suggestions = await page.query_selector_all("[class*='suggestion'], [class*='autocomplete'] li, [class*='dropdown'] li")
        if suggestions:
            await suggestions[0].click()
            await page.wait_for_timeout(3000)
        else:
            return None

    if result_items:
        await result_items[0].click()
        await page.wait_for_timeout(3000)

    owner_el = await page.query_selector("[class*='owner'], [data-field='owner'], .owner-name")
    mailing_el = await page.query_selector("[class*='mailing'], [data-field='mailing'], .mailing-address")

    owner_name = (await owner_el.inner_text()).strip() if owner_el else ""
    mailing = (await mailing_el.inner_text()).strip() if mailing_el else ""

    if not owner_name:
        body = await page.inner_text("body")
        owner_match = re.search(r"Owner[:\s]+([A-Z][A-Z\s,\.]{3,60})", body)
        mailing_match = re.search(r"Mailing[:\s]+([0-9][^\n]{5,80})", body)
        owner_name = owner_match.group(1).strip() if owner_match else ""
        mailing = mailing_match.group(1).strip() if mailing_match else ""

    if not owner_name:
        return None

    return {"owner_name": owner_name, "mailing_address": mailing}
