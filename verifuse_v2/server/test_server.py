"""
VERIFUSE V2 — Engine 4: Integration Test

Generates dummy records, tests obfuscation, tests PDF generation.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from verifuse_v2.contracts.schemas import EntityRecord, OutcomeRecord, SignalRecord
from verifuse_v2.server.obfuscator import text_to_image
from verifuse_v2.server.motion_gen import generate_motion
from verifuse_v2.server.dossier_gen import generate_dossier


def main() -> None:
    print("=" * 60)
    print("  VERIFUSE V2 — Engine 4 Integration Test")
    print("=" * 60)

    # ── 1. Dummy records ─────────────────────────────────────────────
    entity = EntityRecord(
        signal_id="TEST-SIGNAL-001",
        entity_type="OWNER",
        name="Jane R. Martinez",
        mailing_address="1234 Colfax Ave, Denver, CO 80204",
        contact_score=80,
        is_deceased=False,
        zombie_flag=False,
    )

    outcome = OutcomeRecord(
        signal_id="TEST-SIGNAL-001",
        outcome_type="OVERBID",
        gross_amount=425000.00,
        net_amount=47250.00,
        holding_entity="Trustee",
        confidence_score=0.92,
        source_url="https://example.com/foreclosure/TEST-SIGNAL-001",
    )

    print("\n[1] Dummy EntityRecord created")
    print(f"    Name:    {entity.name}")
    print(f"    Address: {entity.mailing_address}")
    print(f"    Score:   {entity.contact_score}")

    print("\n[2] Dummy OutcomeRecord created")
    print(f"    Type:    {outcome.outcome_type}")
    print(f"    Surplus: ${outcome.net_amount:,.2f}")
    print(f"    Conf:    {outcome.confidence_score}")

    # ── 2. Test obfuscation ──────────────────────────────────────────
    print("\n[3] Testing text_to_image obfuscation...")
    name_b64 = text_to_image(entity.name)
    addr_b64 = text_to_image(entity.mailing_address)

    assert name_b64.startswith("data:image/png;base64,"), "Name image prefix wrong"
    assert addr_b64.startswith("data:image/png;base64,"), "Address image prefix wrong"
    assert len(name_b64) > 100, "Name image too small"
    assert len(addr_b64) > 100, "Address image too small"
    # Raw text must NOT appear in the base64 payload
    assert entity.name not in name_b64, "Raw name leaked into base64!"
    assert entity.mailing_address not in addr_b64, "Raw address leaked into base64!"

    print(f"    Name image:    {len(name_b64)} chars (OK)")
    print(f"    Address image: {len(addr_b64)} chars (OK)")
    print("    No raw text leakage detected (OK)")

    # ── 3. Test PDF generation ───────────────────────────────────────
    print("\n[4] Testing motion PDF generation...")
    output_dir = Path(__file__).resolve().parent.parent / "data" / "motions"
    pdf_path = generate_motion(outcome, entity, output_dir=output_dir)
    pdf_file = Path(pdf_path)

    assert pdf_file.exists(), f"PDF not found at {pdf_path}"
    assert pdf_file.stat().st_size > 500, "PDF too small — likely empty"

    print(f"    PDF generated: {pdf_path}")
    print(f"    PDF size:      {pdf_file.stat().st_size:,} bytes (OK)")

    # ── 4. Test dossier PDF generation ──────────────────────────────
    print("\n[5] Testing dossier PDF generation...")
    signal = SignalRecord(
        signal_id="TEST-SIGNAL-001",
        county="Denver",
        signal_type="FORECLOSURE_FILED",
        case_number="2025CV030456",
        event_date="2025-06-15",
        source_url="https://example.com/foreclosure/TEST-SIGNAL-001",
        property_address="4720 E Colfax Ave, Denver, CO 80220",
    )

    dossier_dir = Path(__file__).resolve().parent.parent / "data" / "dossiers"
    dossier_path = generate_dossier(signal, outcome, entity, output_dir=dossier_dir)
    dossier_file = Path(dossier_path)

    assert dossier_file.exists(), f"Dossier PDF not found at {dossier_path}"
    assert dossier_file.stat().st_size > 500, "Dossier PDF too small"

    print(f"    Dossier PDF:   {dossier_path}")
    print(f"    Dossier size:  {dossier_file.stat().st_size:,} bytes (OK)")

    # ── 5. Test API module import ────────────────────────────────────
    print("\n[6] Testing API module import...")
    from verifuse_v2.server.api import app
    assert app.title == "VeriFuse V2 — Product API"
    routes = [r.path for r in app.routes]
    assert "/api/leads" in routes, "/api/leads endpoint missing"
    assert "/api/unlock/{signal_id}" in routes, "/api/unlock endpoint missing"
    assert "/api/dossier/{signal_id}" in routes, "/api/dossier endpoint missing"
    assert "/health" in routes, "/health endpoint missing"
    print(f"    FastAPI app:   {app.title} v{app.version}")
    print(f"    Routes:        {[r for r in routes if r.startswith('/api') or r == '/health']}")

    # ── Done ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Engine 4: ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
