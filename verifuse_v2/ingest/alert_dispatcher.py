"""
VeriFuse — GOLD Lead Alert Dispatcher
======================================
Runs after every scrape cycle. Finds leads promoted to GOLD in the last 48 hours
and emails all active subscribed attorneys about new opportunities in their counties.

Usage:
    python3 -m verifuse_v2.ingest.alert_dispatcher
    python3 -m verifuse_v2.ingest.alert_dispatcher --hours 72   # wider window
    python3 -m verifuse_v2.ingest.alert_dispatcher --dry-run    # print without sending
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

DB_PATH = os.environ.get("VERIFUSE_DB_PATH",
    str(__import__("pathlib").Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"))

SITE_URL = os.environ.get("VERIFUSE_SITE_URL", "https://verifuse.tech")
FROM_EMAIL = "support@verifuse.tech"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode = WAL")
    return c


def _send_alert(to: str, lead: sqlite3.Row, dry_run: bool = False) -> bool:
    """Send a single GOLD lead alert email. Returns True on success."""
    county_display = lead["county"].replace("_", " ").title()
    surplus_fmt = f"${lead['surplus_amount']:,.0f}" if lead["surplus_amount"] else "Confirmed"
    addr = lead["property_address"] or "Address on file"
    lead_url = f"{SITE_URL}/lead/{lead['id']}"

    subject = f"🏆 New GOLD Lead: {surplus_fmt} surplus — {county_display} County"
    body = f"""New GOLD Lead Available — VeriFuse

Property: {addr}
County: {county_display}
Confirmed Surplus: {surplus_fmt}
Sale Date: {lead['sale_date'] or 'Recently sold'}

View full intel → {lead_url}

This lead has been math-validated via VeriFuse Gate 4 cross-check.
Surplus confirmed: successful bid - total indebtedness = {surplus_fmt}.

Act quickly — the 6-month claim window under C.R.S. § 38-38-111 may apply.

---
VeriFuse | {SITE_URL}
Unsubscribe: {SITE_URL}/account/notifications
"""
    html_body = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#0f172a;color:#e2e8f0;padding:24px;border-radius:8px">
  <div style="text-align:center;margin-bottom:20px">
    <span style="font-size:28px;font-weight:900;color:#22c55e;letter-spacing:2px">VERIFUSE</span>
    <div style="color:#64748b;font-size:12px;letter-spacing:3px">GOLD LEAD ALERT</div>
  </div>
  <div style="background:#166534;border:1px solid #22c55e;border-radius:6px;padding:20px;margin-bottom:20px">
    <div style="font-size:32px;font-weight:900;color:#22c55e;text-align:center">{surplus_fmt}</div>
    <div style="text-align:center;color:#86efac;font-size:14px">CONFIRMED SURPLUS — MATH VALIDATED</div>
  </div>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="color:#64748b;padding:8px 0;border-bottom:1px solid #1e293b">Property</td>
        <td style="color:#e2e8f0;padding:8px 0;border-bottom:1px solid #1e293b"><strong>{addr}</strong></td></tr>
    <tr><td style="color:#64748b;padding:8px 0;border-bottom:1px solid #1e293b">County</td>
        <td style="color:#e2e8f0;padding:8px 0;border-bottom:1px solid #1e293b">{county_display}</td></tr>
    <tr><td style="color:#64748b;padding:8px 0">Sale Date</td>
        <td style="color:#e2e8f0;padding:8px 0">{lead['sale_date'] or 'Recently sold'}</td></tr>
  </table>
  <div style="text-align:center;margin-top:24px">
    <a href="{lead_url}" style="background:#22c55e;color:#0f172a;padding:14px 32px;border-radius:4px;text-decoration:none;font-weight:900;font-size:16px;letter-spacing:1px">
      VIEW FULL INTEL →
    </a>
  </div>
  <p style="color:#475569;font-size:12px;margin-top:20px;text-align:center">
    VeriFuse Gate 4 cross-validated: bid − debt = {surplus_fmt} to the penny.<br>
    Claim window: C.R.S. § 38-38-111. <a href="{SITE_URL}/account/notifications" style="color:#475569">Unsubscribe</a>
  </p>
</div>"""

    if dry_run:
        log.info("[alert] DRY RUN → %s | %s | %s", to, subject, county_display)
        return True

    sg_key = os.environ.get("SENDGRID_API_KEY", "")
    if not sg_key:
        log.warning("[alert] SENDGRID_API_KEY not set — skipping send to %s", to)
        return False

    try:
        import httpx
        resp = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {sg_key}", "Content-Type": "application/json"},
            json={
                "personalizations": [{"to": [{"email": to}]}],
                "from": {"email": FROM_EMAIL, "name": "VeriFuse Alerts"},
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": body},
                    {"type": "text/html", "value": html_body},
                ],
            },
            timeout=15,
        )
        if resp.status_code < 400:
            log.info("[alert] Sent → %s (%d)", to, resp.status_code)
            return True
        else:
            log.error("[alert] SendGrid %d for %s: %s", resp.status_code, to, resp.text[:200])
            return False
    except Exception as e:
        log.error("[alert] Send failed for %s: %s", to, e)
        return False


def run(hours: int = 48, dry_run: bool = False) -> dict:
    """Find GOLD leads promoted in last `hours` hours and alert attorneys."""
    conn = _conn()
    cutoff_ts = int(time.time()) - (hours * 3600)

    cutoff_iso = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Find recently-updated GOLD leads (updated_at is ISO text in this schema)
    new_gold = conn.execute("""
        SELECT l.id, l.county, l.case_number, l.surplus_amount, l.sale_date, l.property_address
        FROM leads l
        WHERE l.data_grade = 'GOLD'
          AND l.surplus_amount > 0
          AND l.updated_at >= ?
        ORDER BY l.surplus_amount DESC NULLS LAST
    """, [cutoff_iso]).fetchall()

    if not new_gold:
        log.info("[alert] No new GOLD leads in last %dh — nothing to send", hours)
        conn.close()
        return {"new_gold": 0, "alerts_sent": 0, "attorneys_notified": 0}

    log.info("[alert] Found %d new GOLD leads in last %dh", len(new_gold), hours)

    # Find all active subscribed attorneys (Investigator+ tier, email_verified)
    attorneys = conn.execute("""
        SELECT u.user_id as id, u.email, u.tier, u.email_verified,
               GROUP_CONCAT(at.territory_value) as territories
        FROM users u
        LEFT JOIN attorney_territories at ON at.user_id = u.user_id AND at.territory_type = 'county'
        WHERE u.is_admin = 0
          AND u.tier IN ('investigator', 'partner', 'enterprise', 'associate', 'sovereign')
          AND u.email_verified = 1
          AND (u.locked_until IS NULL OR u.locked_until < ?)
        GROUP BY u.user_id
    """, [int(time.time())]).fetchall()

    log.info("[alert] %d active subscribed attorneys to consider", len(attorneys))

    alerts_sent = 0
    attorneys_notified = set()

    for lead in new_gold:
        lead_county = lead["county"]
        surplus = lead["surplus_amount"] or 0

        # Skip very small surplus (< $1K) — not worth alerting
        if surplus < 1000:
            continue

        for atty in attorneys:
            territories = atty["territories"] or ""
            county_list = [t.strip().lower() for t in territories.split(",") if t.strip()]

            # Send if: no territory lock (receives all alerts) OR has this county locked
            if not county_list or lead_county.lower() in county_list:
                if _send_alert(atty["email"], lead, dry_run=dry_run):
                    alerts_sent += 1
                    attorneys_notified.add(atty["id"])

    conn.close()
    result = {
        "new_gold": len(new_gold),
        "alerts_sent": alerts_sent,
        "attorneys_notified": len(attorneys_notified),
    }
    log.info("[alert] Complete: %s", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=48,
                        help="Look back N hours for new GOLD leads (default: 48)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log alerts without sending emails")
    args = parser.parse_args()
    result = run(hours=args.hours, dry_run=args.dry_run)
    print(result)
