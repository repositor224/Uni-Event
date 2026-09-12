from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import os
from supabase import create_client
from pathlib import Path

app = FastAPI(title="Rating API")
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

class OrganizerCreate(BaseModel):
    name: str

class ReviewCreate(BaseModel):
    user_id: str
    user_name: str
    rating: int
    comment: str

class EventLink(BaseModel):
    event_id: str
    organizer_id: str

@app.get("/organizers")
def get_organizers():
    if not supabase: raise HTTPException(500, "Supabase not configured")
    res = supabase.table("organizers").select("*").execute()
    orgs = res.data or []
    
    rev_res = supabase.table("organizer_reviews").select("organizer_id, rating").execute()
    reviews = rev_res.data or []
    
    for org in orgs:
        org_reviews = [r["rating"] for r in reviews if r["organizer_id"] == org["id"]]
        org["average_rating"] = sum(org_reviews) / len(org_reviews) if org_reviews else 0
        org["review_count"] = len(org_reviews)
    return {"organizers": orgs}

@app.post("/organizers")
def create_organizer(org: OrganizerCreate):
    if not supabase: raise HTTPException(500, "Supabase not configured")
    if not org.name.strip(): raise HTTPException(400, "Name cannot be empty")
    res = supabase.table("organizers").insert({"name": org.name.strip()}).execute()
    return {"status": "success", "organizer": res.data[0] if res.data else None}

@app.get("/organizers/{org_id}/reviews")
def get_reviews(org_id: str):
    if not supabase: raise HTTPException(500, "Supabase not configured")
    res = supabase.table("organizer_reviews").select("*").eq("organizer_id", org_id).order("created_at", desc=True).execute()
    return {"reviews": res.data or []}

@app.post("/organizers/{org_id}/reviews")
def create_review(org_id: str, review: ReviewCreate):
    if not supabase: raise HTTPException(500, "Supabase not configured")
    if review.rating < 1 or review.rating > 5: raise HTTPException(400, "Rating must be between 1 and 5")
    data = {
        "organizer_id": org_id,
        "user_id": review.user_id,
        "user_name": review.user_name,
        "rating": review.rating,
        "comment": review.comment.strip()
    }
    res = supabase.table("organizer_reviews").insert(data).execute()
    return {"status": "success", "review": res.data[0] if res.data else None}

@app.post("/events/link")
def link_event(payload: EventLink):
    if not supabase: raise HTTPException(500, "Supabase not configured")
    # event id may be an integer (bigint) in the DB, so cast if numeric
    eid = int(payload.event_id) if str(payload.event_id).isdigit() else payload.event_id
    try:
        res = supabase.table("events").update({"organizer_id": payload.organizer_id}).eq("id", eid).execute()
        if not res.data:
            raise HTTPException(404, f"No event found with id {eid}")
        return {"status": "success", "event": res.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to link event: {str(e)}")

@app.get("/organizers/{org_id}/events")
def get_org_events(org_id: str):
    if not supabase: raise HTTPException(500, "Supabase not configured")
    res = supabase.table("events").select("*").eq("organizer_id", org_id).execute()
    return {"events": res.data or []}

if __name__ == "__main__":
    uvicorn.run("Rating:app", host="127.0.0.1", port=8002, reload=True)
