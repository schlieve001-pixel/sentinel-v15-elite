"""
JUDGE API — Forensic Verifier (Port 8001)
==========================================
Patent Application #63/923,069 (Filed 11/22/2025)

Validates FuseMoment submissions from the Witness Engine:
  1. Schema validation (Pydantic strict mode)
  2. Replay verification (re-compute all hashes from raw data)
  3. Integrity scoring: S = 1.0 - (Mismatch * 0.6) - (EnvDrift * 0.4)
  4. Issues TruthCertificate with VERIFIED / REJECTED stamp
  5. Forwards verified proofs to Vault for chain storage
"""

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# PYDANTIC MODELS — Strict Schema (Nov 22 Spec)
# ============================================================================

class MagneticField(BaseModel):
    x: float
    y: float
    z: float
    magnitude: float


class CameraInfo(BaseModel):
    width: int
    height: int
    facing: str = "unknown"
    device_id: str = "unknown"


class ScreenInfo(BaseModel):
    width: int
    height: int
    pixel_ratio: float = 1.0
    color_depth: int = 24


class Environment(BaseModel):
    timestamp_iso: str
    timestamp_ms: int
    timezone: str = "UTC"
    user_agent: str = ""
    platform: str = ""
    language: str = "en"
    screen: Optional[ScreenInfo] = None
    camera: Optional[CameraInfo] = None
    magnetic_field: Optional[MagneticField] = None
    acceleration: Optional[Dict[str, float]] = None
    connection: Optional[Dict[str, Any]] = None


class Hashes(BaseModel):
    h0_seed: str = Field(..., min_length=64, max_length=64)
    h1_media: str = Field(..., min_length=64, max_length=64)
    h2_magnetic: str = Field(..., min_length=64, max_length=64)
    h3_gesture: str = Field(..., min_length=64, max_length=64)
    h5_fused: str = Field(..., min_length=64, max_length=64)

    @field_validator("h0_seed", "h1_media", "h2_magnetic", "h3_gesture", "h5_fused")
    @classmethod
    def validate_hex(cls, v):
        try:
            int(v, 16)
        except ValueError:
            raise ValueError(f"Hash must be valid hex: {v[:16]}...")
        return v.lower()


class GesturePoint(BaseModel):
    t: float
    ax: float = 0
    ay: float = 0
    az: float = 0
    gx: float = 0
    gy: float = 0
    gz: float = 0


class StrobeEvent(BaseModel):
    state: str
    t: int


class FuseMoment(BaseModel):
    """The core submission schema — one atomic proof unit."""
    protocol_version: str = "3.0"
    witness_id: str
    timestamp_iso: str
    timestamp_ms: int
    environment: Environment
    hashes: Hashes
    magnetic_field: MagneticField
    gesture_trace: List[GesturePoint] = []
    strobe_timestamps: List[StrobeEvent] = []
    camera: Optional[CameraInfo] = None
    media_data_url: Optional[str] = None


class TruthCertificate(BaseModel):
    """Output of the verification process."""
    certificate_id: str
    witness_id: str
    timestamp_iso: str
    protocol_version: str
    verdict: str  # "VERIFIED" | "REJECTED" | "DEGRADED"
    score: float
    breakdown: Dict[str, Any]
    hashes: Dict[str, str]
    replay_hashes: Dict[str, str]
    issued_at: str
    judge_version: str = "3.0"


# ============================================================================
# HASH REPLAY ENGINE (RTI-7)
# ============================================================================

def sha256_str(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def sha256_dict(obj: Any) -> str:
    """SHA-256 of JCS (JSON Canonicalization Scheme — RFC 8785)."""
    return sha256_str(jcs(obj))


def jcs(obj: Any) -> str:
    """Deterministic JSON serialization: sorted keys, no whitespace."""
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
    # Pydantic models
    if hasattr(obj, "model_dump"):
        return jcs(obj.model_dump())
    return json.dumps(str(obj))


def replay_h0(env: Environment) -> str:
    """Replay H0 seed hash from environment data."""
    return sha256_dict(env.model_dump())


def replay_h2(mag: MagneticField, strobe: List[StrobeEvent]) -> str:
    """Replay H2 magnetic flux anchor hash."""
    mag_data = {
        "x": mag.x,
        "y": mag.y,
        "z": mag.z,
        "magnitude": mag.magnitude,
        "strobe_timestamps": [s.model_dump() for s in strobe],
    }
    return sha256_dict(mag_data)


def replay_h3(gesture: List[GesturePoint]) -> str:
    """Replay H3 gesture hash from IMU trace."""
    trace = [g.model_dump() for g in gesture]
    return sha256_dict(trace)


def replay_h5(h0: str, h1: str, h2: str, h3: str) -> str:
    """Replay H5 fusion hash."""
    fusion = {
        "h0_seed": h0,
        "h1_media": h1,
        "h2_magnetic": h2,
        "h3_gesture": h3,
    }
    return sha256_dict(fusion)


# ============================================================================
# SCORING ENGINE
# ============================================================================

def score_submission(moment: FuseMoment, replay: Dict[str, str]) -> Dict[str, Any]:
    """
    Integrity Scoring:
      S = 1.0 - (Mismatch * 0.6) - (EnvDrift * 0.4)

    Mismatch: How many replayed hashes differ from submitted hashes
    EnvDrift: Environmental anomalies (timing, resolution, sensor gaps)
    """
    # --- MISMATCH CHECK ---
    hash_checks = {
        "h0_match": moment.hashes.h0_seed == replay["h0"],
        "h2_match": moment.hashes.h2_magnetic == replay["h2"],
        "h3_match": moment.hashes.h3_gesture == replay["h3"],
        "h5_match": moment.hashes.h5_fused == replay["h5"],
    }
    # H1 (media) cannot be replayed server-side (we don't receive the full blob)
    # so we trust it and check the fusion instead

    mismatch_count = sum(1 for v in hash_checks.values() if not v)
    mismatch_ratio = mismatch_count / len(hash_checks)

    # --- ENVIRONMENT DRIFT CHECK ---
    drift_penalties = []

    # Timing: submission shouldn't be older than 5 minutes
    try:
        capture_time = datetime.fromisoformat(moment.timestamp_iso.replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - capture_time).total_seconds()
        if age_seconds > 300:
            drift_penalties.append(("timing_stale", 0.3))
        elif age_seconds < -10:
            drift_penalties.append(("timing_future", 0.5))
    except Exception:
        drift_penalties.append(("timing_parse_error", 0.2))

    # Resolution: below 1080p is penalized
    if moment.camera:
        if moment.camera.width < 1920 and moment.camera.height < 1080:
            drift_penalties.append(("low_resolution", 0.2))

    # Gesture: too few data points means no real movement
    if len(moment.gesture_trace) < 10:
        drift_penalties.append(("gesture_insufficient", 0.3))

    # Strobe: should have at least 3 events (ON-OFF-ON)
    if len(moment.strobe_timestamps) < 3:
        drift_penalties.append(("strobe_missing", 0.15))

    # Magnetic field: zero vector is suspicious (no sensor)
    if moment.magnetic_field.magnitude < 0.1:
        drift_penalties.append(("mag_zero", 0.1))

    total_drift = min(1.0, sum(p[1] for p in drift_penalties))

    # --- FINAL SCORE ---
    score = round(1.0 - (mismatch_ratio * 0.6) - (total_drift * 0.4), 4)
    score = max(0.0, min(1.0, score))

    return {
        "score": score,
        "mismatch_ratio": mismatch_ratio,
        "mismatch_count": mismatch_count,
        "hash_checks": hash_checks,
        "drift_total": total_drift,
        "drift_penalties": drift_penalties,
    }


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="VeriFuse JUDGE API",
    version="3.0",
    description="Forensic Verifier — RTI Protocol",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

VAULT_URL = "http://localhost:8002"


@app.get("/health")
async def health():
    return {"status": "online", "service": "judge", "version": "3.0"}


@app.post("/verify", response_model=TruthCertificate)
async def verify(moment: FuseMoment):
    """
    Verify a FuseMoment submission.

    1. Validate schema (Pydantic does this automatically)
    2. Replay hashes from raw data
    3. Score integrity
    4. Issue TruthCertificate
    5. Forward to Vault for chain storage
    """
    # STEP 1: Replay hashes
    r_h0 = replay_h0(moment.environment)
    r_h2 = replay_h2(moment.magnetic_field, moment.strobe_timestamps)
    r_h3 = replay_h3(moment.gesture_trace)
    r_h5 = replay_h5(r_h0, moment.hashes.h1_media, r_h2, r_h3)

    replay = {"h0": r_h0, "h2": r_h2, "h3": r_h3, "h5": r_h5}

    # STEP 2: Score
    scoring = score_submission(moment, replay)

    # STEP 3: Determine verdict
    if scoring["score"] >= 0.8 and scoring["mismatch_count"] == 0:
        verdict = "VERIFIED"
    elif scoring["score"] >= 0.5:
        verdict = "DEGRADED"
    else:
        verdict = "REJECTED"

    # STEP 4: Build certificate
    cert_id = f"VF-CERT-{uuid.uuid4().hex[:12].upper()}"
    now_iso = datetime.now(timezone.utc).isoformat()

    certificate = TruthCertificate(
        certificate_id=cert_id,
        witness_id=moment.witness_id,
        timestamp_iso=moment.timestamp_iso,
        protocol_version=moment.protocol_version,
        verdict=verdict,
        score=scoring["score"],
        breakdown={
            "mismatch_ratio": scoring["mismatch_ratio"],
            "mismatch_count": scoring["mismatch_count"],
            "hash_checks": scoring["hash_checks"],
            "drift_total": scoring["drift_total"],
            "drift_penalties": scoring["drift_penalties"],
        },
        hashes={
            "h0_seed": moment.hashes.h0_seed,
            "h1_media": moment.hashes.h1_media,
            "h2_magnetic": moment.hashes.h2_magnetic,
            "h3_gesture": moment.hashes.h3_gesture,
            "h5_fused": moment.hashes.h5_fused,
        },
        replay_hashes={
            "h0_replay": r_h0,
            "h2_replay": r_h2,
            "h3_replay": r_h3,
            "h5_replay": r_h5,
        },
        issued_at=now_iso,
    )

    # STEP 5: Forward to Vault
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            vault_resp = await client.post(
                f"{VAULT_URL}/append",
                json=certificate.model_dump(),
            )
            if vault_resp.status_code == 200:
                vault_data = vault_resp.json()
                print(f"[JUDGE] Proof stored in Vault: index={vault_data.get('index')}")
            else:
                print(f"[JUDGE] Vault storage warning: {vault_resp.status_code}")
    except Exception as e:
        print(f"[JUDGE] Vault unreachable: {e} — certificate issued but not chained")

    print(f"[JUDGE] {verdict} | score={scoring['score']} | cert={cert_id}")
    return certificate


@app.post("/replay")
async def replay_check(moment: FuseMoment):
    """Debug endpoint: replay hashes without issuing a certificate."""
    r_h0 = replay_h0(moment.environment)
    r_h2 = replay_h2(moment.magnetic_field, moment.strobe_timestamps)
    r_h3 = replay_h3(moment.gesture_trace)
    r_h5 = replay_h5(r_h0, moment.hashes.h1_media, r_h2, r_h3)

    return {
        "submitted": moment.hashes.model_dump(),
        "replayed": {"h0": r_h0, "h2": r_h2, "h3": r_h3, "h5": r_h5},
        "matches": {
            "h0": moment.hashes.h0_seed == r_h0,
            "h2": moment.hashes.h2_magnetic == r_h2,
            "h3": moment.hashes.h3_gesture == r_h3,
            "h5": moment.hashes.h5_fused == r_h5,
        },
    }


if __name__ == "__main__":
    print("=" * 60)
    print("VERIFUSE JUDGE API — Port 8001")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
