"""
VeriFuse Surplus Engine — System Integrity Watchdog
=====================================================
Detects:
  - Scraper breakage (no run in 2x cadence)
  - Null-rate inflation in Tier 2 fields
  - Statute expiry (auto-closes)
  - Attorney view integrity (sanity check)
  - Event log stagnation
  - Class distribution drift

No silent degradation allowed.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

import requests

from .schema import RecordClass, EventType
from .pipeline import _now, _log_event, evaluate_all, TIER_2_FIELDS, _is_real_value


def run_daily_checks(conn: sqlite3.Connection) -> dict:
    """Run all daily watchdog checks. Returns report dict."""
    report = {
        "timestamp": _now(),
        "checks": {},
        "actions_taken": [],
        "alerts": [],
    }

    # CHECK 1: Scraper freshness
    report["checks"]["scraper_freshness"] = _check_scraper_freshness(conn, report)

    # CHECK 2: Statute expiry sweep (auto-close)
    report["checks"]["statute_expiry"] = _run_statute_sweep(conn, report)

    # CHECK 3: Null rate analysis
    report["checks"]["null_rates"] = _check_null_rates(conn, report)

    # CHECK 4: Attorney view integrity
    report["checks"]["attorney_integrity"] = _check_attorney_integrity(conn, report)

    # CHECK 5: Re-evaluate all non-closed assets
    results = evaluate_all(conn)
    report["checks"]["evaluation"] = results

    return report


def run_weekly_checks(conn: sqlite3.Connection) -> dict:
    """Run weekly watchdog checks."""
    report = {
        "timestamp": _now(),
        "checks": {},
        "alerts": [],
    }

    # CHECK: Event log growth
    report["checks"]["event_growth"] = _check_event_growth(conn, report, days=7)

    # CHECK: Class distribution
    report["checks"]["class_distribution"] = _get_class_distribution(conn)

    return report


def run_monthly_checks(conn: sqlite3.Connection) -> dict:
    """Run monthly watchdog checks. Produces items requiring human sign-off."""
    report = {
        "timestamp": _now(),
        "checks": {},
        "human_signoff_required": [],
    }

    # CHECK: Statute authority freshness
    report["checks"]["statute_freshness"] = _check_statute_freshness(conn, report)

    # CHECK: Scraper registry audit
    report["checks"]["scraper_audit"] = _check_scraper_audit(conn, report)

    return report


# ============================================================================
# INDIVIDUAL CHECKS
# ============================================================================

def _check_scraper_freshness(conn: sqlite3.Connection, report: dict) -> dict:
    """Check if any scraper hasn't run within 2x its declared cadence."""
    scrapers = conn.execute("""
        SELECT scraper_name, jurisdiction, update_frequency_days, last_run_at, enabled
        FROM scraper_registry WHERE enabled = 1
    """).fetchall()

    results = {"ok": [], "stale": [], "never_run": []}
    now = datetime.utcnow()

    for name, jurisdiction, freq, last_run, enabled in scrapers:
        if not last_run:
            results["never_run"].append(name)
            continue

        try:
            last = datetime.fromisoformat(last_run.rstrip("Z"))
            age_days = (now - last).days
            if age_days > freq * 2:
                results["stale"].append({
                    "scraper": name,
                    "jurisdiction": jurisdiction,
                    "age_days": age_days,
                    "threshold": freq * 2,
                })
                report["alerts"].append(
                    f"STALE SCRAPER: {name} ({jurisdiction}) — {age_days} days since last run "
                    f"(threshold: {freq * 2} days)"
                )
            else:
                results["ok"].append(name)
        except (ValueError, TypeError):
            results["stale"].append({"scraper": name, "error": "unparseable last_run_at"})

    return results


def _run_statute_sweep(conn: sqlite3.Connection, report: dict) -> dict:
    """Close any ATTORNEY asset with days_remaining <= 0."""
    expired = conn.execute("""
        SELECT a.asset_id, ls.days_remaining
        FROM assets a
        JOIN legal_status ls ON a.asset_id = ls.asset_id
        WHERE ls.record_class = 'ATTORNEY' AND ls.days_remaining <= 0
    """).fetchall()

    closed = 0
    for asset_id, days in expired:
        _log_event(conn, asset_id, EventType.KILL_SWITCH,
                   RecordClass.ATTORNEY.value, RecordClass.CLOSED.value,
                   "system:watchdog", f"statute_expired:days={days}")
        conn.execute("""
            UPDATE legal_status SET
                record_class = 'CLOSED', closed_at = ?, close_reason = 'kill_switch:statute_expired'
            WHERE asset_id = ?
        """, (_now(), asset_id))
        closed += 1
        report["actions_taken"].append(f"CLOSED {asset_id}: statute expired (days={days})")

    if closed:
        conn.commit()

    return {"expired_closed": closed}


def _check_null_rates(conn: sqlite3.Connection, report: dict) -> dict:
    """Check null rates for Tier 2 fields across non-CLOSED assets."""
    total = conn.execute("""
        SELECT COUNT(*) FROM assets a
        JOIN legal_status ls ON a.asset_id = ls.asset_id
        WHERE ls.record_class != 'CLOSED'
    """).fetchone()[0]

    if total == 0:
        return {"total": 0, "fields": {}}

    results = {"total": total, "fields": {}}
    for field in TIER_2_FIELDS:
        nulls = conn.execute(f"""
            SELECT COUNT(*) FROM assets a
            JOIN legal_status ls ON a.asset_id = ls.asset_id
            WHERE ls.record_class != 'CLOSED'
            AND (a.{field} IS NULL OR a.{field} = '' OR LOWER(a.{field}) IN
                 ('unknown', 'n/a', 'na', 'none', 'tbd', 'check records',
                  'check county site', 'not available', 'pending', 'see file'))
        """).fetchone()[0]

        pct = round(nulls / total * 100, 1)
        results["fields"][field] = {"null_count": nulls, "null_pct": pct}

        if pct > 50:
            report["alerts"].append(
                f"HIGH NULL RATE: {field} is {pct}% null across {total} non-CLOSED assets"
            )

    return results


def _check_attorney_integrity(conn: sqlite3.Connection, report: dict) -> dict:
    """Verify attorney_view only shows assets that pass all gates."""
    # This should be impossible by SQL VIEW construction, but check anyway
    bad_rows = conn.execute("""
        SELECT asset_id FROM attorney_view
        WHERE days_remaining <= 0 OR days_remaining IS NULL
    """).fetchall()

    if bad_rows:
        report["alerts"].append(
            f"CRITICAL: {len(bad_rows)} assets in attorney_view with expired/null days_remaining"
        )
        return {"integrity": "FAILED", "bad_assets": [r[0] for r in bad_rows]}

    return {"integrity": "PASSED"}


def _check_event_growth(conn: sqlite3.Connection, report: dict, days: int) -> dict:
    """Check if pipeline_events has grown in the last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
    recent = conn.execute(
        "SELECT COUNT(*) FROM pipeline_events WHERE created_at > ?", (cutoff,)
    ).fetchone()[0]

    total = conn.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0]

    if recent < 10:
        report["alerts"].append(
            f"LOW ACTIVITY: Only {recent} events in last {days} days. "
            "Scrapers may be broken or no new data."
        )

    return {"recent_events": recent, "total_events": total, "period_days": days}


def _get_class_distribution(conn: sqlite3.Connection) -> dict:
    """Get current class distribution."""
    dist = {}
    for cls in ("PIPELINE", "QUALIFIED", "ATTORNEY", "CLOSED"):
        count = conn.execute(
            "SELECT COUNT(*) FROM legal_status WHERE record_class = ?", (cls,)
        ).fetchone()[0]
        dist[cls] = count
    return dist


def _check_statute_freshness(conn: sqlite3.Connection, report: dict) -> dict:
    """Check if any statute_authority entry is older than 365 days."""
    stale = conn.execute("""
        SELECT jurisdiction, verified_date, verified_by
        FROM statute_authority
        WHERE verified_date < date('now', '-365 days')
    """).fetchall()

    for jurisdiction, vdate, vby in stale:
        report["human_signoff_required"].append(
            f"STATUTE REVIEW NEEDED: {jurisdiction} — last verified {vdate} by {vby}"
        )

    return {"stale_entries": len(stale)}


def _check_scraper_audit(conn: sqlite3.Connection, report: dict) -> dict:
    """Check for enabled scrapers that have never run."""
    never_run = conn.execute("""
        SELECT scraper_name, jurisdiction
        FROM scraper_registry
        WHERE enabled = 1 AND last_run_at IS NULL
    """).fetchall()

    for name, jurisdiction in never_run:
        report["human_signoff_required"].append(
            f"SCRAPER NEVER RUN: {name} ({jurisdiction}) — enabled but no recorded run"
        )

    return {"never_run_count": len(never_run)}


# ============================================================================
# URL HEALTH MONITOR — Self-Healing
# ============================================================================

def check_url_health(timeout: int = 15) -> dict:
    """
    Test all 17 county scraper endpoints. Returns per-county health status.

    Categories:
      GREEN  — HTTP 200, serves real content (>5KB)
      YELLOW — HTTP 200 but suspiciously small (<5KB) or redirected to corporate
      RED    — HTTP error, DNS failure, timeout, or redirect to realauction.com
      DEAD   — Connection refused / DNS not found
    """
    try:
        from ..scrapers.hunter_engine import _build_config_map
    except ImportError:
        return {"error": "Cannot import hunter_engine"}

    configs = _build_config_map()
    results = {"green": [], "yellow": [], "red": [], "dead": []}
    details = {}

    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")

    for county, config in configs.items():
        url = config["search_url"]
        platform = config.get("platform", "standard")
        status_info = {
            "county": county,
            "platform": platform,
            "url": url[:80],
        }

        try:
            resp = requests.get(url, headers={"User-Agent": ua},
                                timeout=timeout, allow_redirects=True)
            status_info["http_code"] = resp.status_code
            status_info["final_url"] = resp.url[:80]
            status_info["size_bytes"] = len(resp.content)

            # Check for corporate redirect (DEAD data endpoint)
            if "realauction.com" in resp.url and "realforeclose" not in resp.url:
                status_info["status"] = "RED"
                status_info["reason"] = "redirected_to_corporate"
                results["red"].append(county)
            elif resp.status_code == 200 and len(resp.content) > 5000:
                status_info["status"] = "GREEN"
                results["green"].append(county)
            elif resp.status_code == 200:
                status_info["status"] = "YELLOW"
                status_info["reason"] = f"small_response_{len(resp.content)}B"
                results["yellow"].append(county)
            else:
                status_info["status"] = "RED"
                status_info["reason"] = f"http_{resp.status_code}"
                results["red"].append(county)

        except requests.exceptions.ConnectionError:
            status_info["status"] = "DEAD"
            status_info["reason"] = "connection_failed"
            results["dead"].append(county)
        except requests.exceptions.Timeout:
            status_info["status"] = "RED"
            status_info["reason"] = "timeout"
            results["red"].append(county)
        except Exception as e:
            status_info["status"] = "RED"
            status_info["reason"] = str(e)[:60]
            results["red"].append(county)

        details[county] = status_info

    results["details"] = details
    results["summary"] = {
        "total": len(configs),
        "green": len(results["green"]),
        "yellow": len(results["yellow"]),
        "red": len(results["red"]),
        "dead": len(results["dead"]),
    }
    return results


def auto_disable_broken_scrapers(conn: sqlite3.Connection,
                                 health: dict) -> list:
    """Auto-disable scrapers whose URLs are DEAD or RED.

    Logs the action so it can be reversed. Returns list of disabled scrapers.
    """
    disabled = []
    for county in health.get("dead", []) + health.get("red", []):
        detail = health.get("details", {}).get(county, {})
        source_name = None
        try:
            from ..scrapers.hunter_engine import _build_config_map
            configs = _build_config_map()
            source_name = configs.get(county, {}).get("source_name")
        except ImportError:
            continue

        if source_name:
            conn.execute("""
                UPDATE scraper_registry SET
                    enabled = 0,
                    disabled_reason = ?
                WHERE scraper_name = ? AND enabled = 1
            """, (f"auto_disabled:{detail.get('reason', 'url_failed')}", source_name))
            disabled.append(source_name)

    if disabled:
        conn.commit()
    return disabled


def print_system_status(conn: sqlite3.Connection, url_health: dict = None):
    """Print a comprehensive system status dashboard."""
    print()
    print("=" * 70)
    print("  VERIFUSE SYSTEM STATUS DASHBOARD")
    print("=" * 70)

    # --- DATABASE ---
    total = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    classes = {}
    for row in conn.execute("SELECT record_class, COUNT(*) FROM legal_status GROUP BY record_class"):
        classes[row[0]] = row[1]

    atty_count = conn.execute("SELECT COUNT(*) FROM attorney_view").fetchone()[0]
    total_surplus = conn.execute(
        "SELECT COALESCE(SUM(estimated_surplus), 0) FROM attorney_view"
    ).fetchone()[0]

    print(f"\n  DATABASE")
    print(f"  {'Total assets':.<30} {total}")
    print(f"  {'PIPELINE':.<30} {classes.get('PIPELINE', 0)}")
    print(f"  {'QUALIFIED':.<30} {classes.get('QUALIFIED', 0)}")
    print(f"  {'ATTORNEY':.<30} {classes.get('ATTORNEY', 0)}")
    print(f"  {'CLOSED':.<30} {classes.get('CLOSED', 0)}")
    print(f"  {'Attorney-ready leads':.<30} {atty_count}")
    print(f"  {'Total surplus (visible)':.<30} ${total_surplus:,.0f}")

    # --- SCRAPER HEALTH ---
    print(f"\n  SCRAPER REGISTRY")
    scrapers = conn.execute("""
        SELECT scraper_name, last_run_status, records_produced, enabled,
               last_run_at, disabled_reason
        FROM scraper_registry ORDER BY scraper_name
    """).fetchall()
    for name, status, records, enabled, last_run, reason in scrapers:
        flag = "ON " if enabled else "OFF"
        status = status or "NEVER"
        last = last_run[:10] if last_run else "never"
        line = f"  {flag} {name:25s} | {status:10s} | {records:4d} records | last: {last}"
        if not enabled and reason:
            line += f" | {reason}"
        print(line)

    # --- URL HEALTH ---
    if url_health:
        s = url_health.get("summary", {})
        print(f"\n  URL HEALTH CHECK")
        print(f"  {'GREEN':.<15} {s.get('green', 0)}")
        print(f"  {'YELLOW':.<15} {s.get('yellow', 0)}")
        print(f"  {'RED':.<15} {s.get('red', 0)}")
        print(f"  {'DEAD':.<15} {s.get('dead', 0)}")

        for status_type in ("red", "dead"):
            for county in url_health.get(status_type, []):
                detail = url_health.get("details", {}).get(county, {})
                print(f"  !! {county}: {detail.get('reason', 'unknown')}")

    # --- ATTORNEY LEADS ---
    print(f"\n  TOP ATTORNEY LEADS")
    leads = conn.execute("""
        SELECT county, asset_id, estimated_surplus, days_remaining,
               owner_of_record, property_address
        FROM attorney_view ORDER BY estimated_surplus DESC LIMIT 10
    """).fetchall()
    for county, aid, surplus, days, owner, addr in leads:
        owner_short = (owner or "?")[:20]
        print(f"  ${surplus:>10,.0f} | {days:4d}d | {county:10s} | {owner_short}")

    print()
    print("=" * 70)
    print(f"  Report generated: {datetime.utcnow().isoformat()}Z")
    print("=" * 70)


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

    from .schema import DB_PATH

    conn = sqlite3.connect(str(DB_PATH))

    print("=" * 70)
    print("VERIFUSE WATCHDOG — DAILY CHECK")
    print("=" * 70)

    report = run_daily_checks(conn)

    print(f"\nTimestamp: {report['timestamp']}")
    print(f"\nChecks:")
    for name, result in report["checks"].items():
        print(f"  {name}: {json.dumps(result, indent=4)}")

    if report["actions_taken"]:
        print(f"\nActions Taken:")
        for action in report["actions_taken"]:
            print(f"  - {action}")

    if report["alerts"]:
        print(f"\nALERTS:")
        for alert in report["alerts"]:
            print(f"  !! {alert}")
    else:
        print(f"\nNo alerts.")

    conn.close()
