"""
MASTER VAULT — Append-Only Merkle-Chained Ledger (Port 8002)
=============================================================
Patent Application #63/923,069 (Filed 11/22/2025)

Persistence layer for verified proofs:
  1. Append-only JSONL file (no edits, no deletes)
  2. Hash chaining: Record[N].prev_hash == Record[N-1].master_hash
  3. Master hash includes the record data + prev_hash (Merkle chain)
  4. Query API for verification and audit trail
"""

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ============================================================================
# CONFIG
# ============================================================================

DATA_DIR = Path(__file__).parent / "data"
LEDGER_FILE = DATA_DIR / "ledger.jsonl"
INDEX_FILE = DATA_DIR / "chain_head.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# MODELS
# ============================================================================

class LedgerEntry(BaseModel):
    index: int
    master_hash: str
    prev_hash: str
    data_hash: str
    certificate_id: str
    witness_id: str
    verdict: str
    score: float
    h5_fused: str
    stored_at: str
    data: Dict[str, Any]


class ChainHead(BaseModel):
    index: int
    master_hash: str
    updated_at: str


class AppendResponse(BaseModel):
    status: str
    index: int
    master_hash: str
    prev_hash: str
    chain_length: int


# ============================================================================
# CHAIN ENGINE
# ============================================================================

def sha256_str(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def jcs(obj: Any) -> str:
    """Deterministic JSON serialization (RFC 8785)."""
    if obj is None or isinstance(obj, (int, float, bool)):
        return json.dumps(obj)
    if isinstance(obj, str):
        return json.dumps(obj)
    if isinstance(obj, list):
        return "[" + ",".join(jcs(item) for item in obj) + "]"
    if isinstance(obj, dict):
        keys = sorted(obj.keys())
        return "{" + ",".join(
            json.dumps(k) + ":" + jcs(obj[k]) for k in keys
        ) + "}"
    return json.dumps(str(obj))


class VaultChain:
    """Thread-safe append-only hash chain backed by JSONL."""

    GENESIS_HASH = "0" * 64  # Genesis block prev_hash

    def __init__(self, ledger_path: Path, index_path: Path):
        self.ledger_path = ledger_path
        self.index_path = index_path
        self.lock = threading.Lock()
        self.head = self._load_head()

    def _load_head(self) -> ChainHead:
        """Load chain head from index file, or initialize genesis."""
        if self.index_path.exists():
            try:
                data = json.loads(self.index_path.read_text())
                return ChainHead(**data)
            except Exception:
                pass

        # Reconstruct from ledger if index is missing
        if self.ledger_path.exists():
            last_line = None
            with open(self.ledger_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
            if last_line:
                try:
                    entry = json.loads(last_line)
                    head = ChainHead(
                        index=entry["index"],
                        master_hash=entry["master_hash"],
                        updated_at=entry["stored_at"],
                    )
                    self._save_head(head)
                    return head
                except Exception:
                    pass

        # Genesis state
        return ChainHead(
            index=-1,
            master_hash=self.GENESIS_HASH,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _save_head(self, head: ChainHead):
        self.index_path.write_text(json.dumps(head.model_dump(), indent=2))

    def append(self, certificate: Dict[str, Any]) -> LedgerEntry:
        """Append a verified certificate to the chain. Thread-safe."""
        with self.lock:
            prev_hash = self.head.master_hash
            new_index = self.head.index + 1
            now_iso = datetime.now(timezone.utc).isoformat()

            # Hash the certificate data
            data_hash = sha256_str(jcs(certificate))

            # Master hash = SHA-256(prev_hash + data_hash + index)
            chain_input = f"{prev_hash}|{data_hash}|{new_index}"
            master_hash = sha256_str(chain_input)

            entry = LedgerEntry(
                index=new_index,
                master_hash=master_hash,
                prev_hash=prev_hash,
                data_hash=data_hash,
                certificate_id=certificate.get("certificate_id", "unknown"),
                witness_id=certificate.get("witness_id", "unknown"),
                verdict=certificate.get("verdict", "unknown"),
                score=certificate.get("score", 0.0),
                h5_fused=certificate.get("hashes", {}).get("h5_fused", "unknown"),
                stored_at=now_iso,
                data=certificate,
            )

            # Append to JSONL (atomic write: single line, then flush)
            with open(self.ledger_path, "a") as f:
                f.write(json.dumps(entry.model_dump()) + "\n")
                f.flush()
                os.fsync(f.fileno())

            # Update head
            self.head = ChainHead(
                index=new_index,
                master_hash=master_hash,
                updated_at=now_iso,
            )
            self._save_head(self.head)

            print(f"[VAULT] Appended #{new_index} | master={master_hash[:16]}... | "
                  f"cert={entry.certificate_id} | {entry.verdict}")

            return entry

    def get_entry(self, index: int) -> Optional[Dict]:
        """Retrieve a specific entry by index."""
        if not self.ledger_path.exists():
            return None
        with open(self.ledger_path, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("index") == index:
                        return entry
                except Exception:
                    continue
        return None

    def verify_chain(self) -> Dict[str, Any]:
        """
        Full chain verification — re-compute every master_hash
        and verify prev_hash linkage.
        """
        if not self.ledger_path.exists():
            return {"valid": True, "length": 0, "errors": []}

        entries = []
        with open(self.ledger_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception as e:
                        entries.append({"_parse_error": str(e)})

        errors = []
        prev_hash = self.GENESIS_HASH

        for i, entry in enumerate(entries):
            if "_parse_error" in entry:
                errors.append({"index": i, "error": "parse_error", "detail": entry["_parse_error"]})
                continue

            # Check prev_hash linkage
            if entry.get("prev_hash") != prev_hash:
                errors.append({
                    "index": entry.get("index", i),
                    "error": "broken_chain",
                    "expected_prev": prev_hash,
                    "actual_prev": entry.get("prev_hash"),
                })

            # Re-compute master_hash
            data_hash = entry.get("data_hash", "")
            idx = entry.get("index", i)
            expected_master = sha256_str(f"{entry.get('prev_hash', '')}|{data_hash}|{idx}")

            if entry.get("master_hash") != expected_master:
                errors.append({
                    "index": idx,
                    "error": "hash_mismatch",
                    "expected": expected_master,
                    "actual": entry.get("master_hash"),
                })

            prev_hash = entry.get("master_hash", prev_hash)

        return {
            "valid": len(errors) == 0,
            "length": len(entries),
            "head_index": self.head.index,
            "head_hash": self.head.master_hash[:32] + "...",
            "errors": errors,
        }

    def get_recent(self, n: int = 10) -> List[Dict]:
        """Get the N most recent entries."""
        if not self.ledger_path.exists():
            return []
        entries = []
        with open(self.ledger_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
        return entries[-n:]


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="VeriFuse VAULT",
    version="3.0",
    description="Append-Only Merkle-Chained Ledger",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

chain = VaultChain(LEDGER_FILE, INDEX_FILE)


@app.get("/health")
async def health():
    return {
        "status": "online",
        "service": "vault",
        "version": "3.0",
        "chain_length": chain.head.index + 1,
        "head_hash": chain.head.master_hash[:32] + "...",
    }


@app.post("/append", response_model=AppendResponse)
async def append(certificate: Dict[str, Any]):
    """Append a verified certificate to the chain."""
    entry = chain.append(certificate)
    return AppendResponse(
        status="stored",
        index=entry.index,
        master_hash=entry.master_hash,
        prev_hash=entry.prev_hash,
        chain_length=entry.index + 1,
    )


@app.get("/entry/{index}")
async def get_entry(index: int):
    """Retrieve a specific chain entry by index."""
    entry = chain.get_entry(index)
    if not entry:
        raise HTTPException(404, f"Entry {index} not found")
    return entry


@app.get("/verify")
async def verify_chain():
    """Full chain integrity verification."""
    return chain.verify_chain()


@app.get("/recent")
async def recent(n: int = 10):
    """Get the N most recent entries."""
    entries = chain.get_recent(n)
    return {"count": len(entries), "entries": entries}


@app.get("/head")
async def head():
    """Get current chain head."""
    return chain.head.model_dump()


if __name__ == "__main__":
    print("=" * 60)
    print("VERIFUSE MASTER VAULT — Port 8002")
    print(f"Ledger: {LEDGER_FILE}")
    print(f"Chain head: index={chain.head.index} hash={chain.head.master_hash[:24]}...")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")
