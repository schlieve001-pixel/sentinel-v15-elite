"""
WITNESS ENGINE — Static File Server + Seal Proxy (Port 8000)
Serves the RTI capture client and proxies /seal to Judge API.
"""

import os
from pathlib import Path

import uvicorn
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="VeriFuse WITNESS", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
JUDGE_URL = os.environ.get("JUDGE_URL", "http://localhost:8001")


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.post("/seal")
async def seal_evidence(request: Request):
    """Proxy: Phone -> Witness -> Judge -> Vault (Judge forwards to Vault)."""
    try:
        data = await request.json()
        print(f"[WITNESS] Evidence received from field unit")

        async with httpx.AsyncClient(timeout=15.0) as client:
            judge_resp = await client.post(f"{JUDGE_URL}/verify", json=data)

            if judge_resp.status_code == 200:
                cert = judge_resp.json()
                print(f"[WITNESS] {cert.get('verdict')} | score={cert.get('score')} | cert={cert.get('certificate_id')}")
                return JSONResponse({
                    "status": "SECURED" if cert.get("verdict") == "VERIFIED" else cert.get("verdict", "UNKNOWN"),
                    "verdict": cert.get("verdict"),
                    "score": cert.get("score"),
                    "certificate_id": cert.get("certificate_id"),
                    "vault_index": 0,
                    "master_hash": cert.get("hashes", {}).get("h5_fused", ""),
                })
            elif judge_resp.status_code == 422:
                detail = judge_resp.json().get("detail", [])
                fields = [d.get("loc", ["?"])[-1] for d in detail[:3]]
                return JSONResponse(
                    {"status": "REJECTED", "reason": f"Schema: missing {', '.join(fields)}", "verdict": "REJECTED"},
                    status_code=400,
                )
            else:
                return JSONResponse(
                    {"status": "ERROR", "reason": f"Judge returned {judge_resp.status_code}", "verdict": "ERROR"},
                    status_code=502,
                )

    except httpx.ConnectError:
        return JSONResponse(
            {"status": "ERROR", "reason": "Judge unreachable", "verdict": "ERROR"},
            status_code=503,
        )
    except Exception as e:
        print(f"[WITNESS] Error: {e}")
        return JSONResponse(
            {"status": "CRITICAL_FAIL", "detail": str(e)},
            status_code=500,
        )


# Static files (must be last — catch-all mount)
app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    print("=" * 60)
    print("VERIFUSE WITNESS ENGINE — Port 8000")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
