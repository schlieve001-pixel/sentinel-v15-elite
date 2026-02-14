"""
VeriFuse Hunter — Google Colab Quick-Start
==========================================
Copy this entire file into a Colab cell and run it.

Cell 1: Install dependencies
Cell 2: Run the hunter
Cell 3: Review results
Cell 4: (Optional) Push to pipeline DB
"""

# ============================================================================
# CELL 1: INSTALL (run this first)
# ============================================================================
# !pip install requests fake_useragent beautifulsoup4 pdfplumber lxml -q

# ============================================================================
# CELL 2: RUN THE HUNTER
# ============================================================================

"""
from verifuse.scrapers.hunter_engine import run_hunter

# Scrape Denver + Jefferson, years 2020-2026
results = run_hunter(
    counties=["Denver", "Jefferson"],
    start_year=2020,
    end_year=2026,
    output_csv="verifuse_hunter_results.csv",
)

# Quick look at top records
for r in results["records"][:5]:
    print(f"  [{r.get('_classification')}] {r.get('county')} | "
          f"${r.get('estimated_surplus', 0):,.0f} | "
          f"{r.get('owner_of_record', 'Unknown')} | "
          f"Quality: {r.get('_litigation_quality')}")
"""

# ============================================================================
# CELL 3: ANALYZE RESULTS (standalone — no imports needed)
# ============================================================================

"""
import pandas as pd

df = pd.read_csv("verifuse_hunter_results.csv")

print("\\n=== CLASSIFICATION BREAKDOWN ===")
print(df["_classification"].value_counts())

print("\\n=== WHALES (>$100K surplus, no junior liens) ===")
whales = df[df["_classification"] == "WHALE"]
if not whales.empty:
    print(whales[["county", "case_number", "owner_of_record",
                   "estimated_surplus", "_estimated_fee"]].to_string())
else:
    print("No whales found in this scrape.")

print("\\n=== ABSENTEE OWNERS ===")
absentee = df[df["_is_absentee"] == True]
print(f"Found {len(absentee)} absentee owners")
if not absentee.empty:
    print(absentee[["county", "owner_of_record", "property_address",
                     "_mailing_address", "estimated_surplus"]].head(10).to_string())

print("\\n=== ATTORNEY EXCLUSIVE WINDOW (< 180 days) ===")
exclusive = df[df["_days_since_sale"] <= 180]
print(f"Found {len(exclusive)} records in attorney-exclusive window")
"""

# ============================================================================
# CELL 4: PUSH TO PIPELINE (optional — only if you have the DB)
# ============================================================================

"""
from verifuse.scrapers.hunter_engine import ingest_to_pipeline

# This feeds results into your canonical verifuse DB
pipeline_results = ingest_to_pipeline(
    results["records"],
    db_path="verifuse/data/verifuse.db"
)
"""
