# Platform Guide

VeriFuse V2 uses four platform adapters to scrape different types of county websites. Each adapter inherits from `CountyScraper` (defined in `verifuse_v2/scrapers/base_scraper.py`) and implements the `discover_pdfs()` and `fetch_html_data()` methods.

---

## RealForeclose Adapter

**File:** `verifuse_v2/scrapers/adapters/realforeclose_adapter.py`
**Class:** `RealForecloseAdapter`
**Platform field:** `realforeclose`

### Overview

RealForeclose is an online auction platform used by several Colorado counties. Each county has a subdomain: `{county}.realforeclose.com`.

### Counties Using This Platform

| County | Base URL |
|--------|---------|
| El Paso | https://elpaso.realforeclose.com |
| Larimer | https://larimer.realforeclose.com |
| Mesa | https://mesa.realforeclose.com |
| Summit | https://summit.realforeclose.com |
| Eagle | https://eagle.realforeclose.com |

### How It Works

1. **Discovery:** Scrapes the calendar page (`/index.cfm`) for auction listings
2. **PDF Links:** Finds links to surplus/excess fund documents in the listing pages
3. **HTML Data:** Parses auction preview pages for structured foreclosure data (bid amounts, debtor info, sale dates)
4. **URL Construction:** If `base_url` is not set in counties.yaml, it is constructed as `https://{county_code}.realforeclose.com`

### Challenges

- JavaScript-rendered content: Some auction details require waiting for page load
- Session cookies: The platform may require an active session to access some pages
- Rate limiting: RealForeclose may throttle or block aggressive scrapers

### Configuration

```yaml
- name: El Paso
  code: el_paso
  platform: realforeclose
  base_url: https://elpaso.realforeclose.com
  public_trustee_url: https://publictrustee.elpasoco.com/
  pdf_patterns: ["*excess*", "*surplus*", "*sale*"]
```

---

## GTS Adapter

**File:** `verifuse_v2/scrapers/adapters/gts_adapter.py`
**Class:** `GTSSearchAdapter`
**Platform field:** `gts`

### Overview

GTS (Government Technology Solutions) provides ASP.NET-based foreclosure search portals for county public trustees. These portals typically have a search form with ViewState management.

### Counties Using This Platform

| County | Notes |
|--------|-------|
| Adams | Custom search at `apps.adcogov.org/PTForeclosureSearch/` |
| Arapahoe | Standard GTS portal |
| Boulder | Uses `GTSPreSaleParser` for pre-sale list format |
| Douglas | Standard GTS portal |
| Weld | Custom `WeldParser` |
| Garfield | Has its own subdomain |

### How It Works

1. **Initial GET:** Fetch the search page to obtain ASP.NET `__VIEWSTATE` and `__EVENTVALIDATION` tokens
2. **POST Search:** Submit the form with search criteria and ViewState tokens
3. **Parse Results:** Extract foreclosure records from the HTML result table
4. **PDF Discovery:** Find links to excess/surplus fund PDF documents

### ASP.NET ViewState Handling

GTS portals use ASP.NET server-side state management. The adapter:
- Extracts `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, and `__EVENTVALIDATION` from the initial page
- Includes these tokens in every POST request
- Maintains a session with cookies across requests

### Configuration

```yaml
- name: Adams
  code: adams
  platform: gts
  base_url: https://apps.adcogov.org/PTForeclosureSearch/
  public_trustee_url: https://adcogov.org/public-trustee
  pdf_patterns: ["*POST*SALE*", "*excess*", "*surplus*"]
```

---

## CountyPage Adapter

**File:** `verifuse_v2/scrapers/adapters/county_page_adapter.py`
**Class:** `CountyPageAdapter`
**Platform field:** `county_page`

### Overview

The most common adapter. Scrapes a county's Public Trustee webpage for links to PDF documents containing excess/surplus fund information. Works with any static or semi-dynamic website.

### Counties Using This Platform

This is the default adapter for counties that do not use RealForeclose, GTS, or GovEase. Used by Denver, Jefferson, Pueblo, Pitkin, Routt, Grand, Broomfield, and approximately 20 other counties.

### How It Works

1. **Fetch Page:** GET the `public_trustee_url`
2. **Parse HTML:** Use BeautifulSoup to find all `<a>` tags with PDF links
3. **Pattern Match:** Filter links using `pdf_patterns` from counties.yaml
4. **Download:** Save matching PDFs to `raw_pdfs/{county_code}/`

### Link Matching Logic

The adapter matches PDF links by checking:
- The `href` attribute for `.pdf` extension
- The anchor text for keywords (excess, surplus, overbid, foreclosure)
- The URL path for pattern matches against `pdf_patterns`

### Configuration

```yaml
- name: Denver
  code: denver
  platform: county_page
  parser: DenverExcessParser
  public_trustee_url: https://www.denvergov.org/Government/Departments/Department-of-Finance/Public-Trustee
  pdf_patterns: ["*excess*funds*", "*surplus*", "*foreclosure*sale*results*"]
```

### Tips

- Some county websites have nested pages. You may need to update the URL to point directly to the page with PDF links.
- If the county redesigns their website, the `public_trustee_url` may need updating.
- County pages with frames or iframes may require the inner frame URL instead.

---

## GovEase Adapter

**File:** `verifuse_v2/scrapers/adapters/govease_adapter.py`
**Class:** `GovEaseAdapter`
**Platform field:** `govease`

### Overview

GovEase is a government auction platform. It typically requires more complex interaction (JavaScript rendering, session management) than static county pages.

### Counties Using This Platform

| County | Status |
|--------|--------|
| Teller | Disabled by default |
| San Miguel | Disabled by default |

**Note:** GovEase counties are disabled by default because the platform requires additional configuration and may have more aggressive anti-bot protections.

### Configuration

```yaml
- name: Teller
  code: teller
  platform: govease
  public_trustee_url: https://www.co.teller.co.us/PublicTrustee/
  enabled: false  # GovEase -- disabled by default
```

### Enabling GovEase Counties

To enable a GovEase county:

1. Verify the GovEase portal is accessible and has surplus fund data
2. Update the adapter if the platform has changed
3. Set `enabled: true` in counties.yaml
4. Test with: `python -m verifuse_v2.scrapers.runner --county teller --force --dry-run`

---

## Manual Platform

**Platform field:** `manual`

### Overview

For counties with no web presence or no machine-readable data. These counties are handled through Colorado Open Records Act (CORA) requests.

### Counties

Approximately 15 rural counties use the manual platform: Baca, Bent, Cheyenne, Conejos, Costilla, Crowley, Custer, Dolores, Hinsdale, Huerfano, Jackson, Kiowa, Kit Carson, and others.

### Ingestion Process

1. Submit a CORA request to the county's Public Trustee office
2. Receive documents (usually PDF or paper)
3. Scan/save to `verifuse_v2/data/raw_pdfs/{county_code}/`
4. Run Engine V2 to parse: `python -m verifuse_v2.scrapers.engine_v2`
5. Or use forensic ingest: `python -m verifuse_v2.scripts.forensic_ingest`

---

## Adapter Lifecycle

All adapters follow the same lifecycle, defined by `CountyScraper`:

```python
with adapter_cls(county_config) as adapter:
    result = adapter.run(dry_run=False)
    # result contains: pdfs_discovered, pdfs_downloaded, html_records, errors
```

The `run()` method executes three phases:
1. `discover_pdfs()` -- Find PDF URLs
2. `download_pdfs()` -- Download and deduplicate by SHA256
3. `fetch_html_data()` -- Scrape structured HTML data

All HTTP requests go through `PoliteCrawler` with configurable rate limiting (default: 2 requests/minute).

---

## Adding a New Platform

If a county uses a platform not covered by the four existing adapters:

1. Create a new adapter in `verifuse_v2/scrapers/adapters/`
2. Inherit from `CountyScraper`
3. Implement `discover_pdfs()` and `fetch_html_data()`
4. Add the adapter to `ADAPTER_MAP` in `verifuse_v2/scrapers/runner.py`:
   ```python
   ADAPTER_MAP = {
       "realforeclose": RealForecloseAdapter,
       "gts": GTSSearchAdapter,
       "county_page": CountyPageAdapter,
       "govease": GovEaseAdapter,
       "new_platform": NewPlatformAdapter,  # Add here
   }
   ```
5. Use the new platform name in counties.yaml: `platform: new_platform`
