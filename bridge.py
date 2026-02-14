from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os, shutil, uvicorn

app = FastAPI()

class FileMove(BaseModel):
    src: str
    dest: str

@app.get("/system/audit")
async def system_audit():
    db_path = "verifuse_v2/data/verifuse_v2.db"
    pdf_path = "verifuse_v2/data/input_pdfs"
    return {
        "database": "Online" if os.path.exists(db_path) else "MISSING",
        "pdf_count": len(os.listdir(pdf_path)) if os.path.exists(pdf_path) else 0,
        "current_dir": os.getcwd()
    }

@app.post("/system/repair")
async def fix_file(move: FileMove):
    # Safety: Only allow moves within the origin directory
    if ".." in move.src or ".." in move.dest:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    
    try:
        if os.path.exists(move.src):
            os.makedirs(os.path.dirname(move.dest), exist_ok=True)
            shutil.move(move.src, move.dest)
            return {"status": "success", "message": f"Moved {move.src} to {move.dest}"}
        return {"status": "error", "message": "Source file not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
