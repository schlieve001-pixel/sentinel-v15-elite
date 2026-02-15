"""
VERIFUSE V2 — Titanium Parser Registry

Abstract Base Class for deterministic county PDF parsing.
Every parser MUST implement:
  detect(text)  → bool     : Does this text belong to my county?
  extract(text) → List[dict] : Pull structured records from text.
  score(result) → float    : Confidence Function C ∈ [0.0, 1.0]

Confidence Function C:
  C = 0.25·I(bid>0) + 0.25·I(debt>0) + 0.15·I(sale_date) +
      0.15·I(address) + 0.10·I(owner) + 0.10·V(Δ)

  Where V(Δ) = 1.0 if |surplus - (bid - debt)| ≤ $5.00 (variance check)
               0.5 if Δ ≤ $50
               0.0 otherwise

Usage:
    from verifuse_v2.scrapers.registry import PARSER_REGISTRY
    for parser in PARSER_REGISTRY:
        if parser.detect(text):
            records = parser.extract(text)
            for r in records:
                r["confidence_score"] = parser.score(r)
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional


# ── Abstract Base Class ──────────────────────────────────────────────

class CountyParser(ABC):
    """Abstract parser interface. One per county PDF format."""

    county: str = "Unknown"
    state: str = "CO"

    @abstractmethod
    def detect(self, text: str) -> bool:
        """Return True if this text matches this county's PDF format."""
        ...

    @abstractmethod
    def extract(self, text: str, source_file: str = "") -> list[dict]:
        """Extract structured records from full PDF text.

        Each dict must have at minimum:
          case_number, county, owner_name, property_address,
          winning_bid, total_debt, surplus_amount, sale_date
        """
        ...

    def score(self, result: dict) -> float:
        """Confidence Function C ∈ [0.0, 1.0].

        C = 0.25·I(bid) + 0.25·I(debt) + 0.15·I(date) +
            0.15·I(addr) + 0.10·I(owner) + 0.10·V(Δ)
        """
        bid = result.get("winning_bid") or 0.0
        debt = result.get("total_debt") or 0.0
        surplus = result.get("surplus_amount") or 0.0
        sale_date = result.get("sale_date")
        address = result.get("property_address") or ""
        owner = result.get("owner_name") or ""

        c = 0.0
        if bid > 0:
            c += 0.25
        if debt > 0:
            c += 0.25
        if sale_date:
            c += 0.15
        if address and len(address) > 5:
            c += 0.15
        if owner and len(owner) > 2:
            c += 0.10

        # Variance check V(Δ): |surplus - (bid - debt)| ≤ $5
        if bid > 0 and debt > 0:
            computed = max(0.0, bid - debt)
            delta = abs(surplus - computed)
            if delta <= 5.0:
                c += 0.10
            elif delta <= 50.0:
                c += 0.05
            # else 0.0 — anomalous variance
        elif surplus > 0:
            c += 0.05  # Has surplus but can't verify

        return min(c, 1.0)

    def grade(self, surplus: float, confidence: float) -> str:
        """Compute data grade from surplus and confidence."""
        if surplus >= 10000 and confidence >= 0.8:
            return "GOLD"
        if surplus >= 5000 and confidence >= 0.6:
            return "SILVER"
        if surplus > 0:
            return "BRONZE"
        return "IRON"

    def make_lead_id(self, case_number: str, source_file: str = "") -> str:
        """Deterministic lead ID."""
        key = f"{self.county}_{case_number}_{source_file}"
        h = hashlib.sha256(key.encode()).hexdigest()[:12]
        return f"{self.county.lower().replace(' ', '_')}_reg_{h}"

    def compute_deadline(self, sale_date: Optional[str], days: int = 180) -> Optional[str]:
        """Compute claim deadline from sale date + N days."""
        if not sale_date:
            return None
        try:
            dt = datetime.fromisoformat(sale_date)
            return (dt + timedelta(days=days)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return None


# ── Money/Date Parsing Utilities ─────────────────────────────────────

def clean_money(raw: str) -> float:
    """Parse money: '$155,300.00' → 155300.0, '($43.00)' → -43.0"""
    if not raw:
        return 0.0
    s = raw.replace("$", "").replace(",", "").replace(" ", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        m = re.search(r"[\d.]+", s)
        return float(m.group(0)) if m else 0.0


def parse_date(raw: str) -> Optional[str]:
    """Parse various date formats → ISO."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%B %d %Y"):
        try:
            dt = datetime.strptime(raw.replace(",", ""), fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Try regex fallback
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
    if m:
        mo, dy, yr = m.groups()
        if len(yr) == 2:
            yr = "20" + yr
        return f"{yr}-{int(mo):02d}-{int(dy):02d}"
    return None


# ═══════════════════════════════════════════════════════════════════════
#  CONCRETE PARSERS
# ═══════════════════════════════════════════════════════════════════════


class AdamsParser(CountyParser):
    """Adams County Post-Sale List PDF parser.

    Format: Key-value blocks separated by "Foreclosure #:"
    Fields: Foreclosure #, Property Address, Certificate of Purchase to,
            Bid Amount, Deficiency Amount, Overbid Amount, Total Indebtedness
    """
    county = "Adams"

    def detect(self, text: str) -> bool:
        return bool(
            re.search(r"Adams\s+County\s+Post\s+Sale", text, re.IGNORECASE)
            or re.search(r"Foreclosure\s*#\s*:\s*A\d{6,}", text)
        )

    def extract(self, text: str, source_file: str = "") -> list[dict]:
        # Extract sale date from header
        sale_date = None
        hdr = re.search(r"Sale\s+Date:\s+(\w+\s+\d{1,2},?\s+\d{4})", text, re.IGNORECASE)
        if hdr:
            sale_date = parse_date(hdr.group(1))

        # Also try filename
        if not sale_date and source_file:
            m = re.search(r"(\d{1,2})-(\d{1,2})-(\d{2,4})", source_file)
            if m:
                mo, dy, yr = m.groups()
                if len(yr) == 2:
                    yr = "20" + yr
                sale_date = f"{yr}-{int(mo):02d}-{int(dy):02d}"

        blocks = re.split(r"(?=Foreclosure\s*#\s*:)", text)
        records = []

        for block in blocks:
            if not block.strip().startswith("Foreclosure"):
                continue

            fc = re.search(r"Foreclosure\s*#\s*:\s*([A-Z0-9]+)", block)
            if not fc:
                continue
            case_num = fc.group(1)
            if not re.match(r"^[A-Z]\d{6,}", case_num):
                continue

            addr = re.search(
                r"Property\s+Address\s*:\s*(.+?)(?=Certificate\s+of\s+Purchase|$)",
                block, re.DOTALL
            )
            property_address = re.sub(r"\s+", " ", addr.group(1).strip()) if addr else ""

            buyer = re.search(
                r"Certificate\s+of\s+Purchase\s+to\s*:\s*(.+?)(?=Purchaser\s+Address|$)",
                block, re.DOTALL
            )
            owner_name = re.sub(r"\s+", " ", buyer.group(1).strip()) if buyer else ""

            bid_m = re.search(r"Bid\s+Amount\s*:\s*(\$[\d,]+\.?\d*)", block)
            bid = clean_money(bid_m.group(1)) if bid_m else 0.0

            def_m = re.search(r"Deficiency\s+Amount\s*:\s*(\$[\d,]+\.?\d*)", block)
            deficiency = clean_money(def_m.group(1)) if def_m else 0.0

            over_m = re.search(r"Overbid\s+Amount\s*:\s*(\$[\d,]+\.?\d*)", block)
            overbid = clean_money(over_m.group(1)) if over_m else 0.0

            indebt_m = re.search(r"Total\s+Indebtedness\s*:\s*(\$[\d,]+\.?\d*)", block)
            total_debt = clean_money(indebt_m.group(1)) if indebt_m else 0.0

            # Surplus: use overbid if present, else compute bid - debt
            surplus = overbid
            if surplus == 0.0 and bid > 0 and total_debt > 0:
                surplus = max(0.0, bid - total_debt)

            records.append({
                "case_number": case_num,
                "county": self.county,
                "owner_name": owner_name,
                "property_address": property_address,
                "winning_bid": bid,
                "total_debt": total_debt,
                "surplus_amount": surplus,
                "overbid_amount": overbid,
                "deficiency": deficiency,
                "sale_date": sale_date,
                "source_file": source_file,
            })

        return records

    def score(self, result: dict) -> float:
        """Adams-specific: also check the Δ ≤ 5 variance between
        overbid_amount and (bid - debt).
        """
        base = super().score(result)

        # Bonus: Adams has explicit overbid — verify it matches bid-debt
        overbid = result.get("overbid_amount") or 0.0
        bid = result.get("winning_bid") or 0.0
        debt = result.get("total_debt") or 0.0

        if overbid > 0 and bid > 0 and debt > 0:
            computed = max(0.0, bid - debt)
            delta = abs(overbid - computed)
            if delta <= 5.0:
                # Perfect match: boost confidence
                base = min(base + 0.05, 1.0)

        return base


class DenverExcessParser(CountyParser):
    """Denver County Excess Funds list parser.

    Format: Tabular (space-separated columns on single lines)
    Columns: Borrower's Name, Property Address, City, State, Zip,
             Sale Date, File Number, Pending Amount

    IMPORTANT: Excess funds are COUNTY-VERIFIED. The county holds
    the money. So surplus_amount IS the verified amount. No bid/debt
    cross-check needed — override score() accordingly.
    """
    county = "Denver"

    def detect(self, text: str) -> bool:
        return bool(
            re.search(r"Available\s+Excess\s+Funds", text, re.IGNORECASE)
            or re.search(r"Denver\s+Public\s+Trustee", text, re.IGNORECASE)
        )

    def score(self, result: dict) -> float:
        """Denver excess funds are county-verified. Higher base confidence."""
        surplus = result.get("surplus_amount") or 0.0
        sale_date = result.get("sale_date")
        address = result.get("property_address") or ""
        owner = result.get("owner_name") or ""

        # Base: 0.40 for having county-verified surplus
        c = 0.40 if surplus > 0 else 0.0
        if sale_date:
            c += 0.20
        if address and len(address) > 5:
            c += 0.20
        if owner and len(owner) > 2:
            c += 0.15
        # Case number from county
        if result.get("case_number"):
            c += 0.05

        return min(c, 1.0)

    def extract(self, text: str, source_file: str = "") -> list[dict]:
        records = []

        # Each line: NAME ADDRESS CITY STATE ZIP MM/DD/YY FILE# $ AMOUNT
        # The $ amount may have spaces: "$ 2 99,937.74" (OCR artifact)
        pattern = re.compile(
            r"^([A-Z][A-Z\s,.']+?)\s+"          # Owner name (ALL CAPS)
            r"(\d+\s+[A-Z0-9\s.]+?(?:ST|AVE|DR|CT|CIR|BLVD|PL|WAY|LN|RD|UNIT\s+\S+)?)\s+"  # Address
            r"([A-Z\s]+?)\s+"                    # City
            r"(CO)\s+"                            # State
            r"(\d{5})\s+"                         # Zip
            r"(\d{2}/\d{2}/\d{2})\s+"            # Sale date
            r"(\d{4}-\d{6})\s+"                  # File number
            r"\$\s*([\d\s,]+\.?\d*)",             # Amount (may have spaces)
            re.MULTILINE,
        )

        for m in pattern.finditer(text):
            owner = m.group(1).strip()
            address = m.group(2).strip()
            city = m.group(3).strip()
            state = m.group(4).strip()
            zipcode = m.group(5).strip()
            sale_date = parse_date(m.group(6))
            case_num = m.group(7).strip()
            amount_raw = m.group(8).replace(" ", "")
            surplus = clean_money(amount_raw)

            full_address = f"{address}, {city}, {state} {zipcode}"

            records.append({
                "case_number": case_num,
                "county": self.county,
                "owner_name": owner,
                "property_address": full_address,
                "winning_bid": 0.0,  # Excess funds list doesn't have bid
                "total_debt": 0.0,   # Or debt
                "surplus_amount": surplus,
                "overbid_amount": surplus,
                "sale_date": sale_date,
                "source_file": source_file,
            })

        # Fallback: line-by-line for all Denver excess fund lines
        # Format: "NAME ADDRESS CITY CO ZIP MM/DD/YY CASE# $ AMOUNT"
        # OCR note: "$ 2 99,937.74" = "$299,937.74" (spaces in amount)
        if not records:
            lines = text.split("\n")
            for line in lines:
                # Must have $ and a case number pattern
                if "$" not in line:
                    continue

                case_match = re.search(r"(\d{4}-\d{4,6})", line)
                if not case_match:
                    continue
                case_num = case_match.group(1)

                # Extract amount: everything after $ to end of line
                dollar_idx = line.rfind("$")
                if dollar_idx < 0:
                    continue
                amount_raw = line[dollar_idx + 1:].strip()
                # Remove ALL spaces in the amount (OCR artifact)
                amount = clean_money(amount_raw.replace(" ", ""))
                if amount < 10:
                    continue

                # Sale date: MM/DD/YY before case number
                date_match = re.search(r"(\d{2}/\d{2}/\d{2})", line)
                sale_date = parse_date(date_match.group(1)) if date_match else None

                # Owner: ALL-CAPS text at start of line
                owner_match = re.match(r"^([A-Z][A-Z\s,.\-']+?)\s+\d", line)
                owner = owner_match.group(1).strip() if owner_match else ""

                # Address: between owner and DENVER/city
                addr = ""
                if owner:
                    after_owner = line[len(owner):].strip()
                    addr_match = re.match(r"(.+?)\s+DENVER\s+CO", after_owner)
                    if addr_match:
                        addr = addr_match.group(1).strip()
                        addr = f"{addr}, DENVER, CO"

                records.append({
                    "case_number": case_num,
                    "county": self.county,
                    "owner_name": owner,
                    "property_address": addr,
                    "winning_bid": 0.0,
                    "total_debt": 0.0,
                    "surplus_amount": amount,
                    "overbid_amount": amount,
                    "sale_date": sale_date,
                    "source_file": source_file,
                })

        return records


class ElPasoPreSaleParser(CountyParser):
    """El Paso County Pre-Sale List PDF parser.

    Format: Key-value blocks separated by "Foreclosure #:"
    Fields: Foreclosure #, Grantor, Street Address, City, State, Zip,
            Lender's Bid Amount, Deficiency Amount, Total Indebtedness
    Note: Pre-sale — no overbid/surplus until auction occurs.
    """
    county = "El Paso"

    def detect(self, text: str) -> bool:
        return bool(
            re.search(r"El\s+Paso\s+County", text, re.IGNORECASE)
            or re.search(r"elpasopublictrustee", text, re.IGNORECASE)
            or re.search(r"Pre\s+Sale\s+(?:list|report)", text, re.IGNORECASE)
        )

    def extract(self, text: str, source_file: str = "") -> list[dict]:
        sale_date = None
        hdr = re.search(r"Sale\s+Date:\s+(\w+\s+\d{1,2},?\s+\d{4})", text, re.IGNORECASE)
        if hdr:
            sale_date = parse_date(hdr.group(1))

        if not sale_date and source_file:
            m = re.search(r"(\d{8})", source_file)
            if m:
                d = m.group(1)
                sale_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"

        blocks = re.split(r"(?=Foreclosure\s*#\s*:)", text)
        records = []

        for block in blocks:
            if not block.strip().startswith("Foreclosure"):
                continue

            fc = re.search(r"Foreclosure\s*#\s*:\s*(\S+)", block)
            if not fc:
                continue
            case_num = fc.group(1)

            grantor_m = re.search(r"Grantor\s*:\s*(.+?)(?=Street|$)", block, re.DOTALL)
            owner = re.sub(r"\s+", " ", grantor_m.group(1).strip()) if grantor_m else ""

            addr_m = re.search(r"Street\s+Address\s*:\s*(.+?)(?=City|$)", block, re.DOTALL)
            address = re.sub(r"\s+", " ", addr_m.group(1).strip()) if addr_m else ""

            city_m = re.search(r"City\s*:\s*(\S+)", block)
            city = city_m.group(1) if city_m else ""
            if city and address:
                address = f"{address}, {city}, CO"

            bid_m = re.search(r"(?:Lender.?s?\s+)?Bid\s+Amount\s*:\s*(\$[\d,]+\.?\d*)", block)
            bid = clean_money(bid_m.group(1)) if bid_m else 0.0

            indebt_m = re.search(r"Total\s+Indebtedness\s*:\s*(\$[\d,]+\.?\d*)", block)
            total_debt = clean_money(indebt_m.group(1)) if indebt_m else 0.0

            # Pre-sale: no surplus yet
            records.append({
                "case_number": case_num,
                "county": self.county,
                "owner_name": owner,
                "property_address": address,
                "winning_bid": bid,
                "total_debt": total_debt,
                "surplus_amount": 0.0,  # Pre-sale, unknown
                "overbid_amount": 0.0,
                "sale_date": sale_date,
                "source_file": source_file,
            })

        return records


class ElPasoPostSaleParser(CountyParser):
    """El Paso County Post-Sale Continuance list.

    Detects documents with "Continuance" or "Post Sale" in header
    from El Paso County. These contain sale outcomes.
    """
    county = "El Paso"

    def detect(self, text: str) -> bool:
        return bool(
            re.search(r"(?:Post\s+Sale|Continuance)", text, re.IGNORECASE)
            and re.search(r"(?:El\s+Paso|elpaso)", text, re.IGNORECASE)
        )

    def extract(self, text: str, source_file: str = "") -> list[dict]:
        # Post-sale continuance lists are tabular
        records = []
        lines = text.split("\n")

        for line in lines:
            # Look for lines with foreclosure numbers and money amounts
            fc_m = re.search(r"(\d{2}-\d{4,6}|\d{6,})", line)
            money_m = re.findall(r"\$[\d,]+\.?\d*", line)

            if fc_m and money_m:
                case_num = fc_m.group(1)
                amounts = [clean_money(m) for m in money_m]

                bid = amounts[0] if len(amounts) >= 1 else 0.0
                debt = amounts[1] if len(amounts) >= 2 else 0.0
                surplus = max(0.0, bid - debt) if bid > 0 and debt > 0 else 0.0

                records.append({
                    "case_number": case_num,
                    "county": self.county,
                    "owner_name": "",
                    "property_address": "",
                    "winning_bid": bid,
                    "total_debt": debt,
                    "surplus_amount": surplus,
                    "overbid_amount": surplus,
                    "sale_date": None,
                    "source_file": source_file,
                })

        return records


class GenericExcessFundsParser(CountyParser):
    """Fallback parser for generic excess/surplus funds lists.

    Detects: "excess funds", "surplus funds", "unclaimed funds"
    Extracts tabular data with $ amounts.
    """
    county = "Unknown"

    def detect(self, text: str) -> bool:
        return bool(
            re.search(r"(?:excess|surplus|unclaimed)\s+funds", text, re.IGNORECASE)
        )

    def extract(self, text: str, source_file: str = "") -> list[dict]:
        records = []
        lines = text.split("\n")

        for line in lines:
            money_m = re.search(r"\$\s*([\d\s,]+\.\d{2})", line)
            if not money_m:
                continue

            amount = clean_money(money_m.group(1).replace(" ", ""))
            if amount < 10:
                continue

            case_m = re.search(r"(\d{4}-\d{4,6})", line)
            case_num = case_m.group(1) if case_m else f"GEN-{hash(line) % 100000:05d}"

            date_m = re.search(r"(\d{2}/\d{2}/\d{2,4})", line)
            sale_date = parse_date(date_m.group(1)) if date_m else None

            owner_m = re.match(r"^([A-Z][A-Z\s,.']+?)\s+\d", line)
            owner = owner_m.group(1).strip() if owner_m else ""

            records.append({
                "case_number": case_num,
                "county": self.county,
                "owner_name": owner,
                "property_address": "",
                "winning_bid": 0.0,
                "total_debt": 0.0,
                "surplus_amount": amount,
                "overbid_amount": amount,
                "sale_date": sale_date,
                "source_file": source_file,
            })

        return records


# ── Parser Registry (order matters — specific before generic) ────────

PARSER_REGISTRY: list[CountyParser] = [
    AdamsParser(),
    DenverExcessParser(),
    ElPasoPreSaleParser(),
    ElPasoPostSaleParser(),
    GenericExcessFundsParser(),  # Fallback — always last
]


def get_parser_for(text: str) -> Optional[CountyParser]:
    """Return the first matching parser for the given text."""
    for parser in PARSER_REGISTRY:
        if parser.detect(text):
            return parser
    return None
