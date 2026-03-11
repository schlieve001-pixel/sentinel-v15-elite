"""
VeriFuse — County Sources Registry

Canonical registry of all counties, their scraper adapter, URL, and schema version.
Used by govsoft_engine, health checks, and the Admin panel.
"""
from __future__ import annotations

from typing import TypedDict


class CountyConfig(TypedDict, total=False):
    adapter: str          # govsoft | custom | unknown
    url: str
    search_path: str
    schedule: str         # daily | weekly
    parser_version: str
    schema_version: str
    active: bool
    notes: str


COUNTY_SOURCES: dict[str, CountyConfig] = {
    "adams": {
        "adapter": "govsoft",
        "url": "https://adams.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "arapahoe": {
        "adapter": "govsoft",
        "url": "https://arapahoe.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "boulder": {
        "adapter": "govsoft",
        "url": "https://boulder.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "broomfield": {
        "adapter": "govsoft",
        "url": "https://broomfield.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "denver": {
        "adapter": "custom",
        "url": "https://www.denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Public-Trustee",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.0",
        "schema_version": "1",
        "active": True,
        "notes": "PDF-based scraper — not GovSoft",
    },
    "douglas": {
        "adapter": "govsoft",
        "url": "https://douglas.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "el_paso": {
        "adapter": "govsoft",
        "url": "https://elpaso.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "eagle": {
        "adapter": "govsoft",
        "url": "https://eagle.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "garfield": {
        "adapter": "govsoft",
        "url": "https://garfield.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "gilpin": {
        "adapter": "govsoft",
        "url": "https://gilpin.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.1",
        "schema_version": "2",
        "active": True,
    },
    "jefferson": {
        "adapter": "govsoft",
        "url": "https://jefferson.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "larimer": {
        "adapter": "govsoft",
        "url": "https://larimer.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "la_plata": {
        "adapter": "govsoft",
        "url": "https://foreclosures.lpcgov.org",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.1",
        "schema_version": "2",
        "active": True,
        "notes": "requires_accept_terms=1",
    },
    "weld": {
        "adapter": "govsoft",
        "url": "https://weld.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.2",
        "schema_version": "2",
        "active": True,
    },
    "teller": {
        "adapter": "govsoft",
        "url": "https://teller.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.1",
        "schema_version": "2",
        "active": True,
    },
    "elbert": {
        "adapter": "govsoft",
        "url": "https://elbert.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.1",
        "schema_version": "2",
        "active": True,
    },
    "archuleta": {
        "adapter": "govsoft",
        "url": "https://archuleta.gtslegal.com",
        "search_path": "/",
        "schedule": "daily",
        "parser_version": "1.1",
        "schema_version": "2",
        "active": True,
    },
    "san_miguel": {
        "adapter": "govsoft",
        "url": "https://sanmiguel.gtslegal.com",
        "search_path": "/",
        "schedule": "weekly",
        "parser_version": "1.1",
        "schema_version": "2",
        "active": True,
    },
    "clear_creek": {
        "adapter": "govsoft",
        "url": "https://clearcreek.gtslegal.com",
        "search_path": "/",
        "schedule": "weekly",
        "parser_version": "1.1",
        "schema_version": "2",
        "active": True,
        "notes": "ignore_ssl=true",
    },
    "fremont": {
        "adapter": "govsoft",
        "url": "https://fremontcountyco.gov",
        "search_path": "/web/treasurer/ForeclosureSearch/index.aspx",
        "schedule": "weekly",
        "parser_version": "1.0",
        "schema_version": "1",
        "active": True,
        "notes": "referer_url required",
    },
}


def get_county(county_slug: str) -> CountyConfig | None:
    """Return config for a county slug, or None if not registered."""
    return COUNTY_SOURCES.get(county_slug)


def active_counties() -> list[str]:
    """Return list of active county slugs."""
    return [k for k, v in COUNTY_SOURCES.items() if v.get("active", True)]
