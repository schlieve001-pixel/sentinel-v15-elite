# Parser Development

How to write a custom `CountyParser` subclass for parsing county-specific PDF formats.

---

## Overview

The parser registry (`verifuse_v2/scrapers/registry.py`) contains abstract and concrete parser classes. When Engine V2 processes a PDF, it iterates through `PARSER_REGISTRY` and uses the first parser whose `detect()` method returns `True`.

### Parser Interface

Every parser must implement three methods:

```python
class CountyParser(ABC):
    county: str = "Unknown"
    state: str = "CO"

    @abstractmethod
    def detect(self, text: str) -> bool:
        """Does this text match this county's PDF format?"""
        ...

    @abstractmethod
    def extract(self, text: str, source_file: str = "") -> list[dict]:
        """Extract structured records from full PDF text."""
        ...

    def score(self, result: dict) -> float:
        """Confidence Function C. Default implementation provided."""
        ...
```

Additionally, the base class provides these utility methods:

| Method | Purpose |
|--------|---------|
| `score(result)` | Confidence Function C (default: 0.25*bid + 0.25*debt + ...) |
| `grade(surplus, confidence)` | Data grade: GOLD/SILVER/BRONZE/IRON |
| `make_lead_id(case_number, source_file)` | Deterministic SHA256-based lead ID |
| `compute_deadline(sale_date, days=180)` | Compute claim deadline |

---

## Step 1: Study the PDF Format

Before writing code, obtain sample PDFs from the county and study their structure.

```bash
# Extract text from a PDF to see what the parser will receive
python -c "
import pdfplumber
with pdfplumber.open('sample.pdf') as pdf:
    for page in pdf.pages:
        print(page.extract_text())
"
```

Identify:
- **Header patterns:** What text uniquely identifies this county's PDFs?
- **Record boundaries:** How are individual foreclosure records separated?
- **Field extraction:** Where are case numbers, names, addresses, amounts?
- **Date formats:** What date format does the county use?
- **Money formats:** How are dollar amounts formatted?

---

## Step 2: Create the Parser Class

Add your parser to `verifuse_v2/scrapers/registry.py`:

```python
class LarimerParser(CountyParser):
    """Larimer County surplus funds list parser.

    Format: [describe the PDF layout]
    Fields: [list the fields you extract]
    """
    county = "Larimer"

    def detect(self, text: str) -> bool:
        """Return True if this text is from Larimer County surplus list."""
        return bool(
            re.search(r"Larimer\s+County", text, re.IGNORECASE)
            and re.search(r"(?:excess|surplus)\s+funds", text, re.IGNORECASE)
        )

    def extract(self, text: str, source_file: str = "") -> list[dict]:
        """Extract records from Larimer surplus fund PDF text."""
        records = []

        # Extract sale date from header
        sale_date = None
        hdr = re.search(r"Sale\s+Date:\s+(\w+\s+\d{1,2},?\s+\d{4})", text, re.IGNORECASE)
        if hdr:
            sale_date = parse_date(hdr.group(1))

        # Split into individual records
        blocks = re.split(r"(?=Case\s*#\s*:)", text)

        for block in blocks:
            # Extract case number
            case_m = re.search(r"Case\s*#\s*:\s*(\S+)", block)
            if not case_m:
                continue
            case_num = case_m.group(1)

            # Extract owner name
            owner_m = re.search(r"Owner\s*:\s*(.+?)(?=Address|$)", block, re.DOTALL)
            owner = re.sub(r"\s+", " ", owner_m.group(1).strip()) if owner_m else ""

            # Extract address
            addr_m = re.search(r"Address\s*:\s*(.+?)(?=Bid|$)", block, re.DOTALL)
            address = re.sub(r"\s+", " ", addr_m.group(1).strip()) if addr_m else ""

            # Extract financial data
            bid_m = re.search(r"Bid\s*:\s*(\$[\d,]+\.?\d*)", block)
            bid = clean_money(bid_m.group(1)) if bid_m else 0.0

            debt_m = re.search(r"Debt\s*:\s*(\$[\d,]+\.?\d*)", block)
            debt = clean_money(debt_m.group(1)) if debt_m else 0.0

            surplus = max(0.0, bid - debt) if bid > 0 and debt > 0 else 0.0

            records.append({
                "case_number": case_num,
                "county": self.county,
                "owner_name": owner,
                "property_address": address,
                "winning_bid": bid,
                "total_debt": debt,
                "surplus_amount": surplus,
                "overbid_amount": surplus,
                "sale_date": sale_date,
                "source_file": source_file,
            })

        return records
```

### Required Record Fields

Each record dict must include:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `case_number` | str | Yes | County case/foreclosure number |
| `county` | str | Yes | County name (use `self.county`) |
| `owner_name` | str | No | Former property owner |
| `property_address` | str | No | Full property address |
| `winning_bid` | float | No | Auction winning bid |
| `total_debt` | float | No | Total indebtedness |
| `surplus_amount` | float | Yes | Verified or computed surplus |
| `overbid_amount` | float | No | Explicit overbid if available |
| `sale_date` | str | No | ISO date (YYYY-MM-DD) |
| `source_file` | str | No | Relative path to source PDF |

---

## Step 3: Override score() (Optional)

The default `score()` method works for most counties. Override it when:

- The county provides **pre-verified** surplus amounts (like Denver's excess funds list)
- The county has **additional** verification signals (like Adams' explicit overbid field)
- The county format has **known limitations** (e.g., no bid/debt data)

Example: Denver-style override for county-verified amounts:

```python
def score(self, result: dict) -> float:
    """County-verified surplus. Higher base confidence."""
    surplus = result.get("surplus_amount") or 0.0
    c = 0.40 if surplus > 0 else 0.0
    if result.get("sale_date"):
        c += 0.20
    if result.get("property_address") and len(result["property_address"]) > 5:
        c += 0.20
    if result.get("owner_name") and len(result["owner_name"]) > 2:
        c += 0.15
    if result.get("case_number"):
        c += 0.05
    return min(c, 1.0)
```

---

## Step 4: Register the Parser

Add your parser to the `PARSER_REGISTRY` list in `registry.py`. **Order matters** -- specific parsers go before the generic fallback:

```python
PARSER_REGISTRY: list[CountyParser] = [
    AdamsParser(),
    DenverExcessParser(),
    ElPasoPreSaleParser(),
    ElPasoPostSaleParser(),
    LarimerParser(),              # <-- Add before GenericExcessFundsParser
    GenericExcessFundsParser(),   # Fallback -- always last
]
```

---

## Step 5: Update counties.yaml

Set the `parser` field to your new class name:

```yaml
- name: Larimer
  code: larimer
  platform: realforeclose
  parser: LarimerParser         # <-- Use your new parser
```

Note: The `parser` field in counties.yaml is informational (for documentation). The actual parser selection happens via `detect()` in the registry. But keep it updated for reference.

---

## Step 6: Test

```bash
# Run Engine V2 with verbose output
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
python -m verifuse_v2.scrapers.engine_v2 --verbose --dry-run

# Check that your parser matches the county's PDFs
# Look for: [LarimerParser] larimer/larimer_xxx.pdf: N records
```

---

## Utility Functions

The registry module provides helper functions for parsing:

### clean_money(raw: str) -> float

Parses dollar amounts from various formats:

```python
clean_money("$155,300.00")  # → 155300.0
clean_money("($43.00)")     # → -43.0
clean_money("$ 2 99,937.74") # → 299937.74 (OCR artifacts)
```

### parse_date(raw: str) -> Optional[str]

Parses dates from multiple formats to ISO:

```python
parse_date("06/15/25")       # → "2025-06-15"
parse_date("06/15/2025")     # → "2025-06-15"
parse_date("2025-06-15")     # → "2025-06-15"
parse_date("June 15, 2025")  # → "2025-06-15"
```

---

## Common Patterns

### Key-Value Block Format (Adams, El Paso)

```
Foreclosure #: A123456
Property Address: 1234 Main St
Bid Amount: $285,000.00
Total Indebtedness: $210,000.00
```

Parse with: `re.split(r"(?=Foreclosure\s*#\s*:)", text)` then extract fields from each block.

### Tabular Format (Denver)

```
SMITH, JOHN  1234 MAIN ST  DENVER  CO  80202  06/15/25  2025-001234  $ 45,231.50
```

Parse with: Single regex pattern matching the entire line, or line-by-line with fallback.

### Post-Sale Continuance (El Paso)

Tabular with case numbers and multiple dollar amounts per line. Parse line-by-line, looking for case number patterns and `$` amounts.

---

## Debugging Tips

1. **Start with `detect()`:** Make sure your parser only matches the intended county's PDFs. Use specific text patterns unique to that county.

2. **Print extracted text:** Use `pdfplumber` directly to see what text your parser receives. Line breaks and spacing may differ from what you see in the PDF viewer.

3. **Test with multiple PDFs:** County formats may change between reporting periods. Test with PDFs from different dates.

4. **Check the anomaly log:** If records are landing in `engine_v2_anomalies.jsonl`, they scored below 0.5. Examine why.

5. **Beware OCR artifacts:** Some county PDFs are scanned images. Text extraction may have spacing issues (e.g., `$ 2 99,937.74` instead of `$299,937.74`).
