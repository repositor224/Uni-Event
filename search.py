
from __future__ import annotations
import os, re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

APP_DIR = Path(__file__).resolve().parent
ENV_FILE = APP_DIR / ".env.extractor"

UW_DOMAINS = {
    "uwaterloo.ca", "wusa.ca", "engsoc.uwaterloo.ca", "mathsoc.uwaterloo.ca",
    "uwafsa.com", "csclub.uwaterloo.ca", "athletics.uwaterloo.ca"
}
CATEGORIES = [
    "All", "Key Deadlines", "Design Teams", "Competitions", "Residence Events",
    "Academic Events", "Clubs", "Career & Job Fairs", "Recreation", "Sports",
    "Workshops & Learning", "Tech & Entrepreneurship", "Arts & Culture",
    "Community", "Social Events", "General"
]


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
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL/SUPABASE_KEY. Put them in .env.extractor beside search.py.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
app = FastAPI(title="UniEvent Search API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET"], allow_headers=["*"])


def norm(v):
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def event_scope(link):
    host = (urlsplit(str(link or "")).hostname or "").lower().removeprefix("www.")
    return "uwaterloo" if host in UW_DOMAINS or host.endswith(".uwaterloo.ca") else "outside"


MONTH_RE = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?"
)
DATE_RE = re.compile(
    rf"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday,\s*)?"
    rf"(?P<month>{MONTH_RE})\.?\s+(?P<day>\d{{1,2}})"
    rf"(?:,\s*(?P<year>20\d{{2}}))?\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:AM|PM)"
    r"(?:\s*(?:to|-|–|—)\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))?\b",
    re.IGNORECASE,
)

def extract_date_from_text(text, today):
    match = DATE_RE.search(text)
    if not match:
        return None
    month_token = match.group("month").rstrip(".")
    day = int(match.group("day"))
    explicit_year = match.group("year")

    month_lookup = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
        "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }
    month = month_lookup.get(month_token.lower())
    if not month:
        return None

    if explicit_year:
        year = int(explicit_year)
    else:
        year = today.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if (today - candidate).days > 45:
            year += 1
            
    try:
        return date(year, month, day)
    except ValueError:
        return None

def parse_date(value, text_fallback, today):
    if value:
        extracted = extract_date_from_text(str(value), today)
        if extracted:
            return extracted
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            pass
    if text_fallback:
        extracted = extract_date_from_text(text_fallback, today)
        if extracted:
            return extracted
    return None


def time_match(event_date, filt, today):
    if filt == "all": return True
    if event_date is None: return False
    if filt == "before": return event_date < today
    if filt == "recent15": return today <= event_date <= today + timedelta(days=15)
    if filt == "future": return event_date > today + timedelta(days=15)
    return True


def text_match(row, query):
    q = norm(query)
    if not q: return True
    haystack = norm(" ".join(str(row.get(k) or "") for k in ("text", "description", "location", "category")))
    return all(term in haystack for term in q.split())


@app.get("/health")
def health():
    return {"ok": True}

@app.get("/categories")
def categories():
    return {"categories": CATEGORIES[1:]}

@app.get("/events")
def events(
    time_filter: str = Query("all", pattern="^(all|before|recent15|future)$"),
    scope: str = Query("all", pattern="^(all|uwaterloo|outside)$"),
    category: str = Query("all"),
    q: str = Query(""),
    limit: int = Query(500, ge=1, le=500),
):
    response = (supabase.table("events").select("*").order("created_at", desc=True).limit(5000).execute())
    rows = response.data or []
    today = datetime.now().date()
    out = []
    for row in rows:
        s = event_scope(row.get("link_to_external"))
        if scope != "all" and s != scope: continue
        if category.strip().lower() not in ("", "all") and norm(row.get("category")) != norm(category): continue
        parsed_d = parse_date(row.get("date"), row.get("description"), today)
        if not time_match(parsed_d, time_filter, today): continue
        if not text_match(row, q): continue
        item = dict(row)
        item["event_scope"] = s
        if parsed_d:
            item["date"] = parsed_d.isoformat()
        if not item.get("time"):
            time_match_str = TIME_RE.search(str(row.get("description") or ""))
            if time_match_str:
                item["time"] = time_match_str.group(0)
        out.append(item)
        if len(out) >= limit: break
    return {"events": out, "count": len(out)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("search:app", host="127.0.0.1", port=8000, reload=True)