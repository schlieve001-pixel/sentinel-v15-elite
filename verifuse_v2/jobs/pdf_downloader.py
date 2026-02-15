"""
VERIFUSE V2 — pdf_downloader.py

Downloads PDFs from county public trustee websites.
Reads county config from counties.yaml.

Usage:
    export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
    python -m verifuse_v2.jobs.pdf_downloader
    python -m verifuse_v2.jobs.pdf_downloader --county Denver
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ── Fail-fast ────────────────────────────────────────────────────────

DB_PATH = os.environ.get("VERIFUSE_DB_PATH")
if not DB_PATH:
    print("FATAL: VERIFUSE_DB_PATH not set.")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent.parent
PDF_DIR = BASE_DIR / "data" / "raw_pdfs"
CONFIG_PATH = BASE_DIR / "config" / "counties.yaml"

# ── Config ────────────────────────────────────────────────────────────

def load_counties() -> list[dict]:
    """Load county config from YAML."""
    try:
        import yaml
    except ImportError:
        # Fallback: parse the YAML manually for simple structure
        return _parse_counties_simple()

    with open(CONFIG_PATH) as f:
        data = yaml.safe_load(f)
    return data.get("counties", [])


def _parse_counties_simple() -> list[dict]:
    """Simple YAML parser fallback (no PyYAML dependency)."""
    text = CONFIG_PATH.read_text()
    counties = []
    current = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            if current:
                counties.append(current)
            current = {"name": stripped.split(":", 1)[1].strip(), "enabled": True}
        elif stripped.startswith("code:"):
            current["code"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("public_trustee_url:"):
            current["public_trustee_url"] = stripped.split(":", 1)[1].strip()
            # Fix: url split lost the https:
            if not current["public_trustee_url"].startswith("http"):
                current["public_trustee_url"] = "https:" + stripped.split("https:", 1)[1].strip()
        elif stripped.startswith("enabled:"):
            current["enabled"] = stripped.split(":", 1)[1].strip().lower() == "true"
    if current:
        counties.append(current)
    return counties


# ── Download logic ────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "VeriFuse/2.0 (Colorado Public Records Research)"
}


def find_pdf_links(url: str) -> list[str]:
    """Scrape a page for PDF links."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"    [ERROR] Failed to fetch {url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text() or "").lower()
        href_lower = href.lower()

        # Look for PDF links with surplus/excess keywords
        is_pdf = href_lower.endswith(".pdf")
        has_keyword = any(kw in href_lower or kw in text for kw in [
            "excess", "surplus", "overbid", "overage", "sale result",
            "foreclosure", "proceeds",
        ])

        if is_pdf and has_keyword:
            full_url = urljoin(url, href)
            links.append(full_url)

    return list(set(links))


def download_pdf(url: str, county_dir: Path) -> Optional[Path]:
    """Download a PDF to the county directory. Returns path or None."""
    # Extract filename from URL
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    if not filename.endswith(".pdf"):
        filename += ".pdf"

    # Sanitize filename
    filename = re.sub(r"[^\w\-_.]", "_", filename)
    dest = county_dir / filename

    # Skip if already downloaded (same name)
    if dest.exists():
        return None

    try:
        resp = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        resp.raise_for_status()

        # Verify it's actually a PDF
        content_type = resp.headers.get("Content-Type", "")
        if "pdf" not in content_type and not resp.content[:5] == b"%PDF-":
            print(f"    [SKIP] Not a PDF: {filename}")
            return None

        dest.write_bytes(resp.content)
        print(f"    [DOWNLOAD] {filename} ({len(resp.content)/1024:.0f}KB)")
        return dest

    except Exception as e:
        print(f"    [ERROR] Download failed {filename}: {e}")
        return None


def log_download(county: str, url: str, filename: str) -> None:
    """Log download to pipeline_events table."""
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES (?, 'PDF_DOWNLOAD', ?, ?, 'pdf_downloader', ?, ?)
        """, [
            f"pdf_{county}",
            url,
            filename,
            f"county={county}",
            datetime.now(timezone.utc).isoformat(),
        ])
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────

def run(county_filter: Optional[str] = None) -> dict:
    stats = {"counties_scanned": 0, "pdfs_found": 0, "pdfs_downloaded": 0, "errors": []}

    counties = load_counties()
    print(f"\n{'='*60}")
    print(f"  VERIFUSE PDF DOWNLOADER")
    print(f"{'='*60}")
    print(f"  Counties configured: {len(counties)}")
    print(f"  PDF directory: {PDF_DIR}")

    for county in counties:
        if not county.get("enabled", True):
            continue
        if county_filter and county["name"].lower() != county_filter.lower():
            continue

        name = county["name"]
        code = county.get("code", name.lower().replace(" ", "_"))
        url = county.get("public_trustee_url", "")

        if not url:
            continue

        print(f"\n  [{name}] Scanning {url}")
        stats["counties_scanned"] += 1

        county_dir = PDF_DIR / code
        county_dir.mkdir(parents=True, exist_ok=True)

        links = find_pdf_links(url)
        stats["pdfs_found"] += len(links)
        print(f"    Found {len(links)} PDF links")

        for pdf_url in links:
            path = download_pdf(pdf_url, county_dir)
            if path:
                stats["pdfs_downloaded"] += 1
                log_download(name, pdf_url, path.name)

            # Be polite
            time.sleep(2)

    print(f"\n{'='*60}")
    print(f"  RESULTS: {stats['counties_scanned']} counties, "
          f"{stats['pdfs_found']} found, {stats['pdfs_downloaded']} downloaded")
    print(f"{'='*60}\n")

    return stats


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="VeriFuse PDF Downloader")
    ap.add_argument("--county", type=str, default=None, help="Filter to single county")
    args = ap.parse_args()
    run(county_filter=args.county)
