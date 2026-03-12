"""
Adams County Assessor Portal Adapter
Portal: https://gisapp.adcogov.org/PropertySearch
Platform: GIS Web App — universal search box
Status: CLOUDFLARE BLOCKED (probed 2026-03-12)

Notes:
  The Adams County GIS Property Search portal (gisapp.adcogov.org) is protected
  by Cloudflare bot detection. Headless Playwright requests are intercepted with
  a "Security verification" challenge page. Cannot be scraped without Cloudflare
  bypass (e.g., browser fingerprint spoofing or residential proxy).

  Alternative: Adams County also exposes data via their open data portal at
  https://opendata.adcogov.org but owner mailing addresses are not included there.

  Future option: Use Residential Neighborhood Sales Search which may not be CF-protected,
  or request an API key from Adams County GIS department.
"""
from playwright.async_api import Page

PORTAL_URL = "https://gisapp.adcogov.org/PropertySearch"
BLOCKED = True


async def lookup(page: Page, address: str, timeout_ms: int = 20000) -> dict | None:
    """
    Adams County lookup — BLOCKED by Cloudflare.
    Returns None always. Implement Cloudflare bypass to enable.
    """
    # Cloudflare bot protection blocks headless browsers on this portal.
    # Cannot proceed without residential proxy or browser fingerprint bypass.
    return None
