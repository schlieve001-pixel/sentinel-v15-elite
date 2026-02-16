"""
VERIFUSE V2 — Scraper Runner
===============================
Config-driven scraper orchestrator. counties.yaml is the SINGLE SOURCE OF TRUTH.

Loads counties.yaml, instantiates correct adapter per county's platform field,
runs scrapers, feeds PDFs to engine_v2, ingests HTML records, logs to pipeline_events.

Usage:
    python -m verifuse_v2.scrapers.runner --all
    python -m verifuse_v2.scrapers.runner --county adams
    python -m verifuse_v2.scrapers.runner --dry-run
    python -m verifuse_v2.scrapers.runner --status
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from verifuse_v2.scrapers.adapters.realforeclose_adapter import RealForecloseAdapter
from verifuse_v2.scrapers.adapters.gts_adapter import GTSSearchAdapter
from verifuse_v2.scrapers.adapters.county_page_adapter import CountyPageAdapter
from verifuse_v2.scrapers.adapters.govease_adapter import GovEaseAdapter

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "counties.yaml"
DB_PATH = os.environ.get(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)


ADAPTER_MAP = {
    "realforeclose": RealForecloseAdapter,
    "gts": GTSSearchAdapter,
    "county_page": CountyPageAdapter,
    "govease": GovEaseAdapter,
}


def load_counties(config_path: Path = CONFIG_PATH) -> list[dict]:
    """Load county configurations from YAML."""
    if not config_path.exists():
        log.error("counties.yaml not found at %s", config_path)
        return []
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data.get("counties", data) if isinstance(data, dict) else data


class ScraperRunner:
    """Orchestrates county scrapers based on counties.yaml config."""

    def __init__(self, config_path: Path = CONFIG_PATH):
        self.counties = load_counties(config_path)
        self.results: list[dict] = []

    def run_all(self, county_filter: str | None = None, dry_run: bool = False, force: bool = False) -> list[dict]:
        """Run scrapers for all enabled counties (or filtered subset)."""
        self.results = []

        for county_cfg in self.counties:
            code = county_cfg.get("code", "")
            name = county_cfg.get("name", "")
            enabled = county_cfg.get("enabled", False)
            platform = county_cfg.get("platform", "county_page")

            # Filter
            if county_filter and code.lower() != county_filter.lower():
                continue

            if not enabled and not force:
                log.debug("Skipping disabled county: %s", name)
                continue

            # Get adapter class
            adapter_cls = ADAPTER_MAP.get(platform)
            if not adapter_cls:
                log.warning("Unknown platform '%s' for %s — skipping", platform, name)
                continue

            log.info("=" * 50)
            log.info("Running: %s (%s via %s)", name, code, platform)
            log.info("=" * 50)

            try:
                with adapter_cls(county_cfg) as adapter:
                    result = adapter.run(dry_run=dry_run)
                    self.results.append(result)
                    self._log_result(result)
            except Exception as e:
                log.error("FATAL error for %s: %s", name, e)
                self.results.append({
                    "county": name,
                    "county_code": code,
                    "platform": platform,
                    "errors": [str(e)],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        return self.results

    def run_one(self, county_code: str, dry_run: bool = False) -> dict:
        """Run scraper for a single county."""
        results = self.run_all(county_filter=county_code, dry_run=dry_run, force=True)
        if results:
            return results[0]
        return {"error": f"County '{county_code}' not found in config"}

    def _log_result(self, result: dict):
        """Log scraper result to pipeline_events."""
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("PRAGMA journal_mode=WAL")
            now = datetime.now(timezone.utc).isoformat()

            status = "SUCCESS" if not result.get("errors") else "ERROR"
            details = (
                f"pdfs={result.get('pdfs_discovered', 0)}, "
                f"downloaded={result.get('pdfs_downloaded', 0)}, "
                f"html={result.get('html_records', 0)}"
            )
            if result.get("errors"):
                details += f", errors={result['errors'][:3]}"

            conn.execute("""
                INSERT INTO pipeline_events
                (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                VALUES (?, ?, NULL, ?, ?, ?, ?)
            """, [
                f"SCRAPER:{result.get('county_code', '?')}",
                f"SCRAPER_{status}",
                details,
                f"runner:{result.get('platform', '?')}",
                f"county={result.get('county', '?')}",
                now,
            ])
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning("Could not log result: %s", e)

    def print_status(self):
        """Print county coverage status."""
        print("=" * 70)
        print("  VERIFUSE — COUNTY COVERAGE STATUS")
        print("=" * 70)
        print(f"  {'County':<20s} {'Code':<12s} {'Platform':<15s} {'Enabled':<8s} {'Tier'}")
        print("-" * 70)

        enabled_count = 0
        for c in self.counties:
            enabled = c.get("enabled", False)
            if enabled:
                enabled_count += 1
            mark = "YES" if enabled else "no"
            print(f"  {c.get('name', '?'):<20s} {c.get('code', '?'):<12s} "
                  f"{c.get('platform', '?'):<15s} {mark:<8s} {c.get('population_tier', '?')}")

        print("-" * 70)
        print(f"  Total: {len(self.counties)} counties, {enabled_count} enabled")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="VeriFuse Scraper Runner")
    parser.add_argument("--all", action="store_true", help="Run all enabled counties")
    parser.add_argument("--county", type=str, help="Run a specific county by code")
    parser.add_argument("--dry-run", action="store_true", help="Discover only, no downloads")
    parser.add_argument("--force", action="store_true", help="Run even if disabled")
    parser.add_argument("--status", action="store_true", help="Print county coverage status")
    parser.add_argument("--config", type=str, help="Path to counties.yaml")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else CONFIG_PATH
    runner = ScraperRunner(config_path)

    if args.status:
        runner.print_status()
        return

    if args.county:
        result = runner.run_one(args.county, dry_run=args.dry_run)
        print(f"\nResult: {result}")
    elif args.all:
        results = runner.run_all(dry_run=args.dry_run, force=args.force)
        print(f"\n{'=' * 50}")
        print(f"  Completed: {len(results)} counties")
        for r in results:
            status = "OK" if not r.get("errors") else "ERROR"
            print(f"  {r.get('county', '?'):20s} [{status}] pdfs={r.get('pdfs_discovered', 0)} html={r.get('html_records', 0)}")
        print(f"{'=' * 50}")
    else:
        parser.print_help()
        print("\nUse --all to run all counties, --county <code> for one, or --status to see coverage.")


if __name__ == "__main__":
    main()
