"""
VERIFUSE V2 — Manual Ingest CLI
=================================
For counties where operator manually downloads PDFs (CORA responses, email attachments).

Usage:
    python -m verifuse_v2.scrapers.manual_ingest --county Baca --file /path/to/pdf
    python -m verifuse_v2.scrapers.manual_ingest --county Baca --dir /path/to/pdfs/
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

RAW_PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_pdfs"


def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def ingest_pdf(county_code: str, pdf_path: Path) -> dict:
    """Copy PDF into raw_pdfs/{county}/ for engine_v2 processing."""
    county_dir = RAW_PDF_DIR / county_code.lower()
    county_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        return {"error": f"File not found: {pdf_path}"}
    if not pdf_path.suffix.lower() == ".pdf":
        return {"error": f"Not a PDF: {pdf_path}"}

    file_hash = sha256_file(pdf_path)
    dest_name = f"{county_code}_{file_hash[:12]}_{pdf_path.stem}.pdf"
    dest = county_dir / dest_name

    if dest.exists():
        return {"status": "duplicate", "path": str(dest), "sha256": file_hash}

    shutil.copy2(pdf_path, dest)
    log.info("Ingested: %s -> %s", pdf_path, dest)

    return {
        "status": "ingested",
        "county": county_code,
        "source": str(pdf_path),
        "path": str(dest),
        "sha256": file_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Manual PDF ingest for county data")
    parser.add_argument("--county", required=True, help="County code (e.g., baca, bent)")
    parser.add_argument("--file", type=str, help="Single PDF file to ingest")
    parser.add_argument("--dir", type=str, help="Directory of PDFs to ingest")
    args = parser.parse_args()

    results = []

    if args.file:
        result = ingest_pdf(args.county, Path(args.file))
        results.append(result)
        print(f"  {result.get('status', 'error')}: {result.get('path', result.get('error', ''))}")

    elif args.dir:
        pdf_dir = Path(args.dir)
        if not pdf_dir.is_dir():
            print(f"ERROR: Not a directory: {args.dir}")
            sys.exit(1)

        for pdf_file in sorted(pdf_dir.glob("*.pdf")):
            result = ingest_pdf(args.county, pdf_file)
            results.append(result)
            print(f"  {result.get('status', 'error')}: {pdf_file.name}")

    else:
        parser.print_help()
        print("\nProvide --file or --dir to ingest PDFs.")
        sys.exit(1)

    ingested = sum(1 for r in results if r.get("status") == "ingested")
    dupes = sum(1 for r in results if r.get("status") == "duplicate")
    errors = sum(1 for r in results if "error" in r)
    print(f"\nSummary: {ingested} ingested, {dupes} duplicates, {errors} errors")
    print(f"Run `python -m verifuse_v2.scrapers.engine_v2` to process ingested PDFs.")


if __name__ == "__main__":
    main()
