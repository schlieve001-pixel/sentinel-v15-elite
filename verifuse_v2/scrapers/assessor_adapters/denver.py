"""
Denver County Assessor Portal Adapter
Portal: https://property.spatialest.com/co/denver
Platform: SpatialEst — Laravel backend, Bootstrap frontend, typeahead search
Status: PROBED 2026-03-12 — SPA loads, search via JSON API (session established by page load)

API:
  GET /co/denver/api/v1/search?term=ADDRESS → list of matching parcels with schedule IDs
  GET /co/denver/api/v1/recordcard/{schedule} → owner name + mailing address
"""
from playwright.async_api import Page
import re

PORTAL_URL = "https://property.spatialest.com/co/denver"


async def lookup(page: Page, address: str, timeout_ms: int = 25000) -> dict | None:
    await page.goto(PORTAL_URL, timeout=timeout_ms, wait_until="networkidle")
    await page.wait_for_timeout(3000)

    clean = re.sub(r"\s+(?:unit|apt|suite|ste|#)\s*\S+", "", address, flags=re.I)
    clean = re.sub(r",.*$", "", clean).strip()
    clean = re.sub(r"\s+CO\s+\d{5}.*$", "", clean, flags=re.I).strip()

    schedule = None
    try:
        sr = await page.evaluate(
            "async (t) => { const r = await fetch(`/co/denver/api/v1/search?term=${encodeURIComponent(t)}&limit=5`,{headers:{'Accept':'application/json','X-Requested-With':'XMLHttpRequest'}}); if(!r.ok) return null; return r.json(); }",
            clean,
        )
        if sr:
            items = sr if isinstance(sr, list) else (sr.get("data") or sr.get("results") or [])
            if items:
                f = items[0] if isinstance(items, list) else {}
                schedule = f.get("schedule") or f.get("id") or f.get("parcel_id")
    except Exception:
        pass

    if schedule:
        try:
            rec = await page.evaluate(
                "async (s) => { const r = await fetch(`/co/denver/api/v1/recordcard/${s}`,{headers:{'Accept':'application/json','X-Requested-With':'XMLHttpRequest'}}); if(!r.ok) return null; return r.json(); }",
                str(schedule),
            )
            if rec:
                d = rec.get("data", rec)
                on = d.get("owner_name") or d.get("owner") or d.get("OwnerName", "")
                ma = d.get("mailing_address") or d.get("MailingAddress") or ""
                if on:
                    return {"owner_name": str(on).strip(), "mailing_address": str(ma).strip()}
        except Exception:
            pass

    try:
        inp = await page.wait_for_selector("#primary_search, input[placeholder*='earch']", timeout=8000)
        await inp.fill(clean)
        await page.wait_for_timeout(3000)
        sug = await page.query_selector(".tt-suggestion, [class*='suggestion'], [class*='autocomplete'] li")
        if sug:
            await sug.click()
            await page.wait_for_timeout(3000)
    except Exception:
        pass

    body = await page.inner_text("body")
    om = re.search(r"(?:Owner|OWNER)\s*(?:Name)?[:\s]+([A-Z][A-Z\s,\.&]{3,60})", body)
    mm = re.search(r"(?:Mailing|MAILING)[:\s]+([0-9][^\n]{5,80})", body)
    on = om.group(1).strip() if om else ""
    ma = mm.group(1).strip() if mm else ""
    if not on:
        return None
    return {"owner_name": on, "mailing_address": ma}
