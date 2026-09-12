from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
import os
from supabase import create_client
from pathlib import Path

app = FastAPI(title="Physical Event API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

APP_DIR = Path(__file__).resolve().parent
ENV_FILE = APP_DIR / ".env.extractor"

def load_env_file():
    if not ENV_FILE.exists(): return
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and not os.environ.get(k, "").strip():
            os.environ[k] = v

load_env_file()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = (os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SECRET_KEY") or "").strip()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

class PhysicalEventCreate(BaseModel):
    text: str                       # Event title
    description: str                # Event description
    date: Optional[str] = None      # YYYY-MM-DD
    time: Optional[str] = None      # e.g. "14:00" or "2:00 PM"
    location: Optional[str] = None
    category: Optional[str] = None
    organizer_id: Optional[str] = None
    image_url: Optional[str] = None # URL from Supabase Storage

@app.get("/physical_events")
def get_physical_events():
    if not supabase: raise HTTPException(500, "Supabase not configured")
    res = supabase.table("events").select("*").eq("is_physical", True).order("created_at", desc=True).execute()
    return {"events": res.data or []}

@app.post("/physical_events")
def create_physical_event(event: PhysicalEventCreate):
    if not supabase: raise HTTPException(500, "Supabase not configured")
    if not event.text.strip(): raise HTTPException(400, "Event title is required")
    if not event.description.strip(): raise HTTPException(400, "Description is required")

    data = {
        "text": event.text.strip(),
        "description": event.description.strip(),
        "is_physical": True,
    }
    # Only add optional fields if provided
    if event.date and event.date.strip():
        data["date"] = event.date.strip()
    if event.time and event.time.strip():
        data["time"] = event.time.strip()
    if event.location and event.location.strip():
        data["location"] = event.location.strip()
    if event.category and event.category.strip():
        data["category"] = event.category.strip()
    if event.organizer_id and event.organizer_id.strip():
        data["organizer_id"] = event.organizer_id.strip()
    if event.image_url and event.image_url.strip():
        data["image"] = event.image_url.strip()

    try:
        res = supabase.table("events").insert(data).execute()
        return {"status": "success", "event": res.data[0] if res.data else None}
    except Exception as e:
        raise HTTPException(500, f"Failed to create event: {str(e)}")

if __name__ == "__main__":
    uvicorn.run("Physical_Event:app", host="127.0.0.1", port=8003, reload=True)
