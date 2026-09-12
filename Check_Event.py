from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import os
import json
import google.generativeai as genai
from supabase import create_client
from pathlib import Path
from datetime import datetime

app = FastAPI(title="Check Event API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

APP_DIR = Path(__file__).resolve().parent
ENV_FILE = APP_DIR / ".env.extractor"

def load_env_file():
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and not os.environ.get(k, "").strip():
            os.environ[k] = v

load_env_file()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = (os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SECRET_KEY") or "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

class Preferences(BaseModel):
    introvertExtrovert: str
    academicSocial: str
    eventTypes: str
    year: str
    faculty: str
    groupSize: str
    startDate: str
    endDate: str

def parse_date(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None

@app.post("/check_events")
def check_events(prefs: Preferences):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured in .env.extractor")
        
    for field_name, value in prefs.dict().items():
        if not value or not str(value).strip():
            raise HTTPException(status_code=400, detail=f"Please complete all fields before submitting. Missing: {field_name}")

    try:
        start_date = datetime.strptime(prefs.startDate, "%Y-%m-%d").date()
        end_date = datetime.strptime(prefs.endDate, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format")

    response = supabase.table("events").select("*").execute()
    all_events = response.data or []
    
    valid_events = []
    for evt in all_events:
        d = parse_date(evt.get("date"))
        if d and start_date <= d <= end_date:
            valid_events.append(evt)
            
    if not valid_events:
        return {"status": "success", "events": []}
        
    events_text = ""
    for i, evt in enumerate(valid_events):
        events_text += f"(Event {i+1}) {evt.get('text', 'Unknown')}, (Description): {evt.get('description', '')}\n"
        
    prompt = f"""You are an advisor helping a student to decide the event they want to attend for. The student is an {prefs.introvertExtrovert} person, prefer {prefs.academicSocial}, prefer {prefs.eventTypes}, is {prefs.year} under faculty of {prefs.faculty}. prefer a {prefs.groupSize} group. Here are the events for them to choose:
{events_text}

Your output should only include a JSON of the following with EVENT NAME ONLY: {{"Event 1": "Event Name", "Event 2": "Event Name", "Event 3": "Event Name"}}. Do not MODIFY the format or wording of the event."""

    model = genai.GenerativeModel('gemini-flash-latest')
    try:
        result = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        rec_json = json.loads(result.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM Error: {str(e)}")
        
    recommended_names = [v for v in rec_json.values() if isinstance(v, str)]
    
    final_events = []
    for name in recommended_names:
        for evt in valid_events:
            if evt.get("text") == name:
                final_events.append(evt)
                break
                
    if len(final_events) < 3 and len(valid_events) >= 3:
        for evt in valid_events:
            if evt not in final_events:
                final_events.append(evt)
            if len(final_events) == 3:
                break
                
    return {"status": "success", "events": final_events}

if __name__ == "__main__":
    uvicorn.run("Check_Event:app", host="127.0.0.1", port=8001, reload=True)
