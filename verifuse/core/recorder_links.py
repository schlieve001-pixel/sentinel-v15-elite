"""
VeriFuse Surplus Engine — County Recorder & Assessor Link Generator
====================================================================
Generates county-specific recorder search URLs and assessor lookup URLs.

DECISION: These are SEARCH URLs, not direct document links.
They are explicitly labeled as such in the attorney UI and case packet.
An attorney clicks the link and searches using owner name or case number.

This unblocks Tier 2 recorder_link for counties where we have a known
recorder site URL pattern.
"""

from typing import Optional
from urllib.parse import quote_plus


# County → URL template
# {owner} = URL-encoded owner name
# {case} = case number
RECORDER_URL_TEMPLATES = {
    # Colorado counties
    "Denver": "https://denvergov.org/recorder/search?query={owner}",
    "Jefferson": "https://gts.co.jefferson.co.us/recorder/eagleweb/docSearch.jsp?search={owner}",
    "Arapahoe": "https://clerk.arapahoegov.com/recorder/eagleweb/docSearch.jsp?search={owner}",
    "Adams": "http://recording.adcogov.org/LandmarkWeb/search/index?nameFilter={owner}",
    "Douglas": "https://apps.douglas.co.us/recorder/web/search?name={owner}",
    "Mesa": "https://www.mesacounty.us/clerk-and-recorder/recording/search?name={owner}",
    "Eagle": "https://eaglecounty.us/Clerk/Recording/Search?name={owner}",
    "Teller": "https://www.co.teller.co.us/Clerk/Recording/search?name={owner}",
    "Summit": "https://www.summitcountyco.gov/clerk/recording/search?name={owner}",
    "San Miguel": "https://www.sanmiguelcountyco.gov/clerk/recording?name={owner}",
    "Pitkin": "https://www.pitkinclerk.com/clerk-recorder/search?q={owner}",
    "Routt": "https://www.co.routt.co.us/clerk/recording/search?name={owner}",
    "El Paso": "https://www.elpasoco.com/recorder/search?query={owner}",
    "Larimer": "https://www.larimer.gov/clerk/recording/search?name={owner}",
    "Boulder": "https://recorder.bouldercounty.gov/search?name={owner}",
    "Weld": "https://www.weldgov.com/recorder/search?query={owner}",
    "Garfield": "https://www.garfield-county.com/clerk/recording/search?name={owner}",
    "Grand": "https://www.co.grand.co.us/clerk/recording/search?name={owner}",

    # Florida
    "Palm Beach": "https://www.mypalmbeachclerk.com/court-records/search?case={case}",
}


def generate_recorder_link(county: str, owner: Optional[str] = None,
                           case_number: Optional[str] = None) -> Optional[str]:
    """Generate a county recorder search URL.

    Returns None if:
    - County not in template registry
    - No owner AND no case number provided
    """
    template = RECORDER_URL_TEMPLATES.get(county)
    if not template:
        return None

    # Use case number for FL (case-based searches)
    if "{case}" in template and case_number:
        return template.replace("{case}", quote_plus(str(case_number)))

    # Use owner for CO (name-based searches)
    if "{owner}" in template and owner and owner != "Unknown":
        return template.replace("{owner}", quote_plus(str(owner)))

    return None


def backfill_recorder_links(conn):
    """Backfill recorder_link for assets that are missing it.

    Only updates assets where recorder_link is NULL and we can generate one.
    Logs as FIELD_UPDATE event.
    """
    from .pipeline import _now, _log_event, EventType

    assets = conn.execute("""
        SELECT asset_id, county, owner_of_record, case_number
        FROM assets
        WHERE recorder_link IS NULL OR recorder_link = '' OR recorder_link = 'Check County Site'
    """).fetchall()

    updated = 0
    for asset_id, county, owner, case_num in assets:
        link = generate_recorder_link(county, owner, case_num)
        if link:
            conn.execute(
                "UPDATE assets SET recorder_link = ?, updated_at = ? WHERE asset_id = ?",
                (link, _now(), asset_id)
            )
            _log_event(conn, asset_id, EventType.FIELD_UPDATE,
                       None, f"recorder_link={link[:80]}", "system:recorder_link_generator",
                       "backfill_recorder_link")
            updated += 1

    conn.commit()
    return updated


# ============================================================================
# COUNTY ASSESSOR LOOKUP URLS
# ============================================================================
# Used for owner verification and property value enrichment.
# {address} = URL-encoded property address
# {owner} = URL-encoded owner name
# {parcel} = parcel/schedule number

ASSESSOR_URL_TEMPLATES = {
    "Denver": "https://www.denvergov.org/property/realproperty/summary/{address}",
    "Jefferson": "https://www.jeffco.us/assessor/property-search?address={address}",
    "Arapahoe": "https://www.arapahoegov.com/assessor/property-search?address={address}",
    "Adams": "https://adcogov.org/assessor/property-search?address={address}",
    "Douglas": "https://www.douglas.co.us/assessor/property-search?address={address}",
    "El Paso": "https://assessor.elpasoco.com/property-search?address={address}",
    "Larimer": "https://www.larimer.gov/assessor/property-search?address={address}",
    "Boulder": "https://www.bouldercounty.gov/property-and-land/assessor/search?address={address}",
    "Weld": "https://www.weldgov.com/departments/assessor/property-search?address={address}",
    "Mesa": "https://www.mesacounty.us/assessor/property-search?address={address}",
    "Eagle": "https://www.eaglecounty.us/assessor/property-search?address={address}",
    "Summit": "https://www.summitcountyco.gov/assessor/property-search?address={address}",
    "Pitkin": "https://www.pitkinclerk.com/assessor/search?address={address}",
    "Routt": "https://www.co.routt.co.us/assessor/property-search?address={address}",
    "Garfield": "https://www.garfield-county.com/assessor/property-search?address={address}",
    "Grand": "https://www.co.grand.co.us/assessor/property-search?address={address}",
    "Teller": "https://www.co.teller.co.us/assessor/property-search?address={address}",
    "San Miguel": "https://www.sanmiguelcountyco.gov/assessor/search?address={address}",
    "Palm Beach": "https://www.pbcgov.org/papa/property-search?address={address}",
}

TREASURER_URL_TEMPLATES = {
    "Denver": "https://www.denvergov.org/property/realproperty/taxes/{address}",
    "Jefferson": "https://www.jeffco.us/treasurer/tax-search?address={address}",
    "Arapahoe": "https://www.arapahoegov.com/treasurer/tax-search?address={address}",
    "Adams": "https://adcogov.org/treasurer/tax-search?address={address}",
    "Douglas": "https://www.douglas.co.us/treasurer/tax-search?address={address}",
    "El Paso": "https://treasurer.elpasoco.com/tax-search?address={address}",
    "Larimer": "https://www.larimer.gov/treasurer/tax-search?address={address}",
    "Boulder": "https://www.bouldercounty.gov/property-and-land/treasurer/search?address={address}",
    "Weld": "https://www.weldgov.com/departments/treasurer/tax-search?address={address}",
    "Mesa": "https://www.mesacounty.us/treasurer/tax-search?address={address}",
    "Eagle": "https://www.eaglecounty.us/treasurer/tax-search?address={address}",
}


def generate_assessor_link(county: str, address: Optional[str] = None) -> Optional[str]:
    """Generate a county assessor property search URL."""
    template = ASSESSOR_URL_TEMPLATES.get(county)
    if not template or not address:
        return None
    return template.replace("{address}", quote_plus(str(address)))


def generate_treasurer_link(county: str, address: Optional[str] = None) -> Optional[str]:
    """Generate a county treasurer tax search URL."""
    template = TREASURER_URL_TEMPLATES.get(county)
    if not template or not address:
        return None
    return template.replace("{address}", quote_plus(str(address)))
