"""Platform adapters for county scrapers."""

from verifuse_v2.scrapers.adapters.realforeclose_adapter import RealForecloseAdapter
from verifuse_v2.scrapers.adapters.gts_adapter import GTSSearchAdapter
from verifuse_v2.scrapers.adapters.county_page_adapter import CountyPageAdapter
from verifuse_v2.scrapers.adapters.govease_adapter import GovEaseAdapter

__all__ = [
    "RealForecloseAdapter",
    "GTSSearchAdapter",
    "CountyPageAdapter",
    "GovEaseAdapter",
]
