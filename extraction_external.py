from __future__ import annotations

import argparse
import getpass
import hashlib
import html
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger("unievent_external")
TORONTO = ZoneInfo("America/Toronto")
FIELDS = ("text", "description", "image", "link_to_external", "category")

EVENT_WORDS = (
    "event", "workshop", "seminar", "lecture", "conference", "competition",
    "hackathon", "fair", "job fair", "career fair", "social", "mixer", "gala",
    "concert", "festival", "reception", "information session", "meetup",
    "tournament", "drop-in", "drop in", "skate", "swim", "class", "program",
    "market", "show", "performance", "screening", "networking", "open house",
)

# Strong signals that an event is outside the Waterloo/Kitchener target area.
# Kitchener is intentionally NOT in this list: Kitchener events are accepted.
OUTSIDE_WATERLOO_WORDS = (
    "cambridge", "elmira", "wellesley", "wilmot", "woolwich",
    "new hamburg", "baden", "st. jacobs", "st jacobs", "st. clements",
    "st clements", "ayr, ontario", "brantford", "guelph",
)

# These sources are themselves geographically specific to Waterloo city.
# Regional aggregators are intentionally excluded from this allowlist and must
# provide Waterloo evidence at the individual-event level.
# Known legacy/dead source URLs that have moved to a current public endpoint.
# Keeping this alias here means an old links_external.txt will still work.
SOURCE_URL_ALIASES = {
    "https://calendar.waterlooregionmuseum.ca/Default/Month":
        "https://calendar.regionofwaterloo.ca/museum",
}

WATERLOO_SCOPED_HOSTS = {
    "events.waterloo.ca",
    "www.waterloo.ca",
    "uptownwaterloobia.com",
    "maxwellswaterloo.com",
    "princesscinemas.com",
    "waterloojazzfest.com",
    "waterloobuskers.com",
    "www.cigionline.org",
    "cigionline.org",
    "perimeterinstitute.ca",
    "www.perimeterinstitute.ca",
    "theclayandglass.ca",
    "www.theclayandglass.ca",
}


def text_of(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return " ".join(
        BeautifulSoup(html.unescape(str(value)), "html.parser")
        .get_text(" ", strip=True)
        .split()
    )


def http_url(base, value, keep_fragment=False):
    if not value or not str(value).strip():
        return ""
    p = urlsplit(urljoin(base, str(value).strip()))
    if p.scheme not in ("https", "http") or not p.hostname or p.username:
        return ""
    fragment = p.fragment if keep_fragment else ""
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, fragment))


def canonical_url(url):
    p = urlsplit(url.strip())
    # Keep query because many event calendars use it for stable event URLs.
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))


def stable_source_link(source_url, identity):
    digest = hashlib.sha1(identity.encode("utf-8", errors="ignore")).hexdigest()[:16]
    p = urlsplit(source_url)
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, "unievent-" + digest))


def resolve_source_url(source_url):
    """Map known retired public URLs to their current public event endpoint."""
    replacement = SOURCE_URL_ALIASES.get(source_url)
    if replacement:
        LOG.info("Source URL moved; using %s instead of %s", replacement, source_url)
        return replacement
    return source_url


def classify_event(title, description):
    combined = (title + " " + description).lower()
    rules = [
        ("Career & Job Fairs", ["job fair", "career fair", "career expo", "hiring", "recruitment", "employer"]),
        ("Competitions", ["competition", "hackathon", "tournament", "contest", "pitch competition", "race"]),
        ("Recreation", ["drop-in", "drop in", "recreation", "swim", "skating", "skate", "fitness", "aquafit", "camp"]),
        ("Sports", ["sport", "hockey", "basketball", "soccer", "volleyball", "baseball", "lacrosse", "curling", "tennis"]),
        ("Workshops & Learning", ["workshop", "seminar", "lecture", "class", "training", "information session", "webinar"]),
        ("Tech & Entrepreneurship", ["startup", "technology", "tech", "entrepreneur", "founder", "innovation", "accelerator"]),
        ("Arts & Culture", ["concert", "music", "museum", "gallery", "art", "film", "screening", "theatre", "festival", "performance"]),
        ("Community", ["community", "market", "volunteer", "open house", "family", "public meeting", "doors open"]),
        ("Social Events", ["social", "mixer", "gala", "reception", "networking", "party"]),
    ]
    for category, words in rules:
        if any(word in combined for word in words):
            return category
    return "General"


def make_row(title, description, link, image="", category=None):
    title = clean_text(title)
    description = clean_text(description)
    link = str(link or "").strip()
    image = str(image or "").strip()
    if not title or not link:
        return None
    return {
        "text": title[:500],
        "description": description[:12000],
        "image": image[:2000],
        "link_to_external": link[:4000],
        "category": category or classify_event(title, description),
    }


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "UniEventExternalImporter/1.0 (public Waterloo event listings)"
        )
        retry = Retry(
            total=2,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.last_request_by_host = {}

    def response(self, url, accept=None):
        host = urlsplit(url).netloc.lower()
        last = self.last_request_by_host.get(host, 0.0)
        time.sleep(max(0.0, 0.7 - (time.monotonic() - last)))
        headers = {"Accept": accept} if accept else None
        response = self.session.get(url, timeout=(10, 35), headers=headers)
        self.last_request_by_host[host] = time.monotonic()
        response.raise_for_status()
        return response

    def get_html(self, url):
        response = self.response(url, "text/html,application/xhtml+xml")
        ctype = response.headers.get("Content-Type", "").lower()
        if "html" not in ctype and not response.text.lstrip().startswith("<"):
            raise ValueError("Expected HTML but source returned " + ctype)
        return BeautifulSoup(response.content, "html.parser")

    def get_text(self, url, accept=None):
        return self.response(url, accept).text

    def close(self):
        self.session.close()


def load_sources(path):
    path = Path(path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")

    urls = []
    seen = set()
    for line_no, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        url = http_url(value, value)
        if not url:
            LOG.warning("links_external.txt line %s is not a valid URL; skipped", line_no)
            continue
        key = canonical_url(url)
        if key in seen:
            LOG.warning("Duplicate URL on line %s; skipped: %s", line_no, url)
            continue
        seen.add(key)
        urls.append((line_no, url))
    return urls


# ---------------- Pagination ----------------

def _pagination_candidates(soup, current_url, first_url):
    """Return likely pagination URLs on the same host.

    Supports rel=next, Drupal/WordPress/The Events Calendar controls, and numbered
    page links such as ?page=2, ?paged=2, /page/2/, /2/, or ?offset=N.
    """
    host = urlsplit(first_url).netloc.lower()
    candidates = []

    selectors = (
        "a[rel='next'][href], "
        ".pager__item--next a[href], .pager__item a[href], "
        "a.next.page-numbers[href], a.page-numbers[href], "
        ".pagination a[href], nav.pagination a[href], "
        ".tribe-events-c-nav__next a[href], .tribe-events-c-nav a[href], "
        ".tribe-events-nav-next a[href], [class*='pagination'] a[href], "
        "[class*='pager'] a[href]"
    )

    for a in soup.select(selectors):
        href = http_url(current_url, a.get("href"))
        if not href or urlsplit(href).netloc.lower() != host:
            continue
        label = text_of(a).lower()
        path_query = (urlsplit(href).path + "?" + urlsplit(href).query).lower()
        looks_numbered = bool(re.search(
            r"(?:[?&](?:page|paged|p|offset|start)=\d+)|(?:/page/\d+/?$)|(?:/\d+/?$)",
            path_query,
        ))
        looks_control = (
            "next" in label or "older" in label or "more" in label or
            "pager" in " ".join(a.get("class", [])) or
            "pagination" in " ".join(a.get("class", [])) or
            looks_numbered
        )
        if looks_control:
            candidates.append(href)

    # Preserve document order and remove duplicates.
    return list(dict.fromkeys(candidates))


def page_sequence(fetcher, first_url, max_pages=0):
    """Crawl every discoverable pagination page for one listing.

    max_pages=0 means no user-imposed page count limit. A hard safety ceiling of
    250 listing pages protects against malformed pagination loops.
    """
    pending = [first_url]
    visited = set()
    hard_ceiling = 250

    while pending:
        if max_pages and len(visited) >= max_pages:
            LOG.info("Pagination cap %s reached for %s", max_pages, first_url)
            return
        if len(visited) >= hard_ceiling:
            LOG.warning("Safety pagination ceiling %s reached for %s", hard_ceiling, first_url)
            return

        url = pending.pop(0)
        key = canonical_url(url)
        if key in visited:
            continue
        visited.add(key)

        soup = fetcher.get_html(url)
        LOG.info("Pagination: fetched page %s for %s", len(visited), url)
        yield soup, url

        for nxt in _pagination_candidates(soup, url, first_url):
            if canonical_url(nxt) not in visited and nxt not in pending:
                pending.append(nxt)

    LOG.info("Pagination complete for %s: %s page(s)", first_url, len(visited))


# ---------------- Structured event extraction ----------------

def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def is_event_jsonld(obj):
    if not isinstance(obj, dict):
        return False
    kinds = obj.get("@type", [])
    if isinstance(kinds, str):
        kinds = [kinds]
    return any(str(kind).lower().endswith("event") for kind in kinds)


def jsonld_location(value):
    if isinstance(value, list):
        return "; ".join(filter(None, (jsonld_location(x) for x in value)))
    if isinstance(value, str):
        return clean_text(value)
    if not isinstance(value, dict):
        return ""

    name = clean_text(value.get("name"))
    address = value.get("address")
    if isinstance(address, dict):
        address_text = ", ".join(filter(None, [
            clean_text(address.get("streetAddress")),
            clean_text(address.get("addressLocality")),
            clean_text(address.get("addressRegion")),
            clean_text(address.get("postalCode")),
            clean_text(address.get("addressCountry")),
        ]))
    else:
        address_text = clean_text(address)
    return " — ".join(filter(None, [name, address_text]))


def jsonld_image(value, base):
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl") or ""
    return http_url(base, value)


def dt_to_text(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=TORONTO)
        return value.astimezone(TORONTO).strftime("%Y-%m-%d %I:%M %p %Z")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return clean_text(value)


def not_stale(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=TORONTO)
        return value.astimezone(TORONTO) >= datetime.now(TORONTO) - timedelta(days=1)
    if isinstance(value, date):
        return value >= datetime.now(TORONTO).date() - timedelta(days=1)
    return True


def parse_jsonld_events(soup, page_url, source_label):
    rows = []
    seen = set()
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        for obj in walk_json(data):
            if not is_event_jsonld(obj):
                continue
            title = clean_text(obj.get("name"))
            start = clean_text(obj.get("startDate"))
            end = clean_text(obj.get("endDate"))
            description = clean_text(obj.get("description"))
            location = jsonld_location(obj.get("location"))
            event_url = http_url(page_url, obj.get("url"))
            identity = "|".join([title, start, end, location])
            link = event_url or stable_source_link(page_url, identity)
            key = (title.lower(), start, link)
            if not title or key in seen:
                continue
            seen.add(key)

            parts = [f"Source: {source_label}"]
            if start:
                parts.append("Starts: " + start)
            if end:
                parts.append("Ends: " + end)
            if location:
                parts.append("Location: " + location)
            if description:
                parts.append(description)

            row = make_row(
                title,
                "\n\n".join(parts),
                link,
                jsonld_image(obj.get("image"), page_url),
            )
            if row:
                rows.append(row)
    return rows


def parse_city_calendar(soup, page_url):
    """Parse the City of Waterloo calendar format at events.waterloo.ca."""
    rows = []
    for a in soup.find_all("a", href=True):
        link = http_url(page_url, a.get("href"))
        if not link:
            continue
        p = urlsplit(link)
        if p.netloc.lower() != "events.waterloo.ca" or "/detail/" not in p.path.lower():
            continue
        title = text_of(a)
        if not title or len(title) < 3:
            continue

        container = a.find_parent(["article", "li", "div", "tr"])
        context = text_of(container) if container else title
        date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", p.path)
        parts = ["Source: City of Waterloo event calendar"]
        if date_match:
            parts.append("Date: " + date_match.group(1))
        if context and context != title:
            parts.append(context)
        row = make_row(title, "\n\n".join(parts), link)
        if row:
            rows.append(row)
    return rows


def parse_generic_event_cards(soup, page_url, source_label):
    """Conservative fallback for public event-listing HTML."""
    rows = []
    selectors = (
        "article[class*='event'], li[class*='event'], div[class*='event-card'], "
        "div[class*='event_item'], div[class*='event-item'], "
        ".tribe-events-calendar-list__event, .tribe-events-pro-photo__event, "
        ".event, .events-list-item, .event-list-item"
    )
    for block in soup.select(selectors):
        anchor = block.select_one(
            "h1 a[href], h2 a[href], h3 a[href], h4 a[href], "
            "a[class*='title'][href], a[class*='event'][href]"
        )
        if not anchor:
            continue
        title = text_of(anchor)
        link = http_url(page_url, anchor.get("href"))
        if not title or not link:
            continue
        block_text = text_of(block)
        if not any(word in (title + " " + block_text).lower() for word in EVENT_WORDS):
            # Allow explicitly event-classed blocks even if the title lacks an event keyword.
            classes = " ".join(block.get("class", [])).lower()
            if "event" not in classes:
                continue
        date_text = text_of(block.select_one("time, [class*='date'], [class*='time']"))
        location = text_of(block.select_one("[class*='location'], [class*='venue'], address"))
        body = text_of(block.select_one("[class*='description'], [class*='excerpt'], p"))
        img = block.select_one("img[src]")
        parts = [f"Source: {source_label}"]
        if date_text:
            parts.append("Date/time: " + date_text)
        if location:
            parts.append("Location: " + location)
        if body:
            parts.append(body)
        row = make_row(
            title,
            "\n\n".join(parts),
            link,
            http_url(page_url, img.get("src")) if img else "",
        )
        if row:
            rows.append(row)
    return rows


# ---------------- iCalendar ----------------

def unfold_ics(text):
    return re.sub(r"\r?\n[ \t]", "", text)


def calendar_ids_from_embed_url(url):
    query = parse_qs(urlsplit(url).query)
    return [value for value in query.get("src", []) if value]


def google_ics_url(calendar_id):
    return "https://calendar.google.com/calendar/ical/" + quote(calendar_id, safe="") + "/public/basic.ics"


def parse_icalendar(text, source_url, source_label):
    try:
        from icalendar import Calendar
    except ImportError as exc:
        raise RuntimeError("Install calendar support with: py -m pip install icalendar") from exc

    cal = Calendar.from_ical(unfold_ics(text))
    rows = []
    for event in cal.walk("VEVENT"):
        title = clean_text(event.get("SUMMARY"))
        uid = clean_text(event.get("UID"))
        start_prop = event.get("DTSTART")
        end_prop = event.get("DTEND")
        start = start_prop.dt if start_prop else None
        end = end_prop.dt if end_prop else None
        if not_stale(end or start) is False:
            continue
        description = clean_text(event.get("DESCRIPTION"))
        location = clean_text(event.get("LOCATION"))
        public_url = clean_text(event.get("URL"))
        link = http_url(source_url, public_url) if public_url else stable_source_link(
            source_url, uid or (title + dt_to_text(start))
        )
        parts = [f"Source: {source_label}"]
        if start:
            parts.append("Starts: " + dt_to_text(start))
        if end:
            parts.append("Ends: " + dt_to_text(end))
        if location:
            parts.append("Location: " + location)
        if description:
            parts.append(description)
        row = make_row(title, "\n\n".join(parts), link)
        if row:
            rows.append(row)
    return rows


def discover_ical_rows(fetcher, soup, page_url, source_label):
    rows = []
    seen_urls = set()

    # Public Google Calendar embeds.
    for iframe in soup.select("iframe[src*='calendar.google.com']"):
        src = http_url(page_url, iframe.get("src"))
        for calendar_id in calendar_ids_from_embed_url(src):
            ics_url = google_ics_url(calendar_id)
            if ics_url in seen_urls:
                continue
            seen_urls.add(ics_url)
            try:
                text = fetcher.get_text(ics_url, "text/calendar,*/*;q=0.5")
                rows.extend(parse_icalendar(text, page_url, source_label))
            except Exception as exc:
                LOG.warning("Google Calendar feed failed for %s (%s)", page_url, type(exc).__name__)

    # Ordinary public .ics links.
    for a in soup.select("a[href]"):
        href = http_url(page_url, a.get("href"))
        if not href or href in seen_urls:
            continue
        low = href.lower()
        if not (low.endswith(".ics") or "ical" in low or "ics=" in low):
            continue
        seen_urls.add(href)
        try:
            text = fetcher.get_text(href, "text/calendar,*/*;q=0.5")
            if "BEGIN:VCALENDAR" in text.upper():
                rows.extend(parse_icalendar(text, page_url, source_label))
        except Exception as exc:
            LOG.debug("Calendar link unavailable %s (%s)", href, type(exc).__name__)

    return rows


# ---------------- Waterloo location filtering ----------------

def _contains_target_city(text):
    """Return True when text gives evidence for Waterloo OR Kitchener."""
    text = clean_text(text).lower()
    if not text:
        return False
    patterns = (
        r"\bwaterloo\s*,\s*(?:on|ontario|canada)\b",
        r"\bwaterloo\s+ontario\b",
        r"\bwaterloo\s+on\b",
        r"\buptown\s+waterloo\b",
        r"\bwaterloo\s+public\s+square\b",
        r"\bwaterloo\s+memorial\s+recreation\s+complex\b",
        r"\brim\s+park\b",
        r"\bmoses\s+springer\b",
        r"\bwaterloo\s+city\s+centre\b",
        # Kitchener is part of the accepted target area. A simple city-name match is
        # intentional because regional event listings commonly publish addresses as
        # "Kitchener, ON" or just a venue followed by "Kitchener".
        r"\bkitchener\b",
        r"\bkitchener[–-]waterloo\b",
    )
    return any(re.search(p, text, re.I) for p in patterns)


# Compatibility helper retained because older code/tests may call this name.
def _contains_waterloo_city(text):
    return _contains_target_city(text)


def is_waterloo_city_event(row, source_url):
    """Keep Waterloo/Kitchener events and reject obvious other-city records."""
    host = urlsplit(source_url).netloc.lower()
    combined = " ".join([
        row.get("text", ""),
        row.get("description", ""),
        row.get("link_to_external", ""),
    ]).lower()

    # A clearly outside municipality still wins over broad source branding. If a
    # description mentions multiple municipalities, keep it only when it also has
    # explicit Waterloo/Kitchener evidence.
    if any(word in combined for word in OUTSIDE_WATERLOO_WORDS):
        return _contains_target_city(combined)

    if host in WATERLOO_SCOPED_HOSTS:
        return True

    # Regional/general sources must identify Waterloo or Kitchener at event level.
    return _contains_target_city(combined)


def filter_waterloo_rows(rows, source_url):
    kept = []
    rejected = 0
    for row in rows:
        if is_waterloo_city_event(row, source_url):
            kept.append(row)
        else:
            rejected += 1
    if rejected:
        LOG.info("Location filter rejected %s non-Waterloo/Kitchener or uncertain record(s) from %s", rejected, source_url)
    return kept


# ---------------- Source extraction ----------------

def extract_source(fetcher, source_url, max_pages):
    # Transparently repair known moved/retired URLs before making any network call.
    source_url = resolve_source_url(source_url)
    label = urlsplit(source_url).netloc
    rows = []
    healthy = True
    found_any_page = False

    try:
        for soup, page_url in page_sequence(fetcher, source_url, max_pages):
            found_any_page = True
            current = []

            if urlsplit(source_url).netloc.lower() == "events.waterloo.ca":
                current.extend(parse_city_calendar(soup, page_url))

            current.extend(parse_jsonld_events(soup, page_url, label))
            current.extend(parse_generic_event_cards(soup, page_url, label))

            # Public calendar feeds can expose events that the surrounding HTML does not.
            if len(rows) < 500:
                current.extend(discover_ical_rows(fetcher, soup, page_url, label))

            rows.extend(current)
    except Exception as exc:
        LOG.error("Source failed %s (%s): %s", source_url, type(exc).__name__, exc)
        healthy = False

    if not found_any_page:
        return [], False

    rows = dedupe_rows(rows)
    rows = filter_waterloo_rows(rows, source_url)
    return rows, healthy


# ---------------- Deduplication ----------------

def dedupe_rows(rows):
    by_link = {}
    fingerprints = set()

    for row in rows:
        if not row or not row.get("text") or not row.get("link_to_external"):
            continue

        link = canonical_url(row["link_to_external"])
        title_key = re.sub(r"\W+", " ", row["text"].lower()).strip()
        desc = row.get("description", "")
        date_match = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", desc)
        fingerprint = (title_key, date_match.group(0) if date_match else "")

        if link in by_link:
            old = by_link[link]
            if len(row.get("description", "")) > len(old.get("description", "")):
                by_link[link] = row
            continue

        if fingerprint[1] and fingerprint in fingerprints:
            continue

        by_link[link] = row
        if fingerprint[1]:
            fingerprints.add(fingerprint)

    return list(by_link.values())


# ---------------- Supabase ----------------

def save_events(client, rows):
    counts = dict(inserted=0, updated=0, unchanged=0, failed=0)

    for row in rows:
        link = row["link_to_external"]
        try:
            matches = (
                client.table("events")
                .select("id," + ",".join(FIELDS))
                .eq("link_to_external", link)
                .limit(2)
                .execute()
                .data
                or []
            )

            if len(matches) > 1:
                LOG.warning("Existing duplicate URL left untouched: %s", link)
                counts["failed"] += 1
                continue

            if not matches:
                client.table("events").insert(row).execute()
                counts["inserted"] += 1
            else:
                old = matches[0]
                payload = dict(row)
                if not payload["image"] and old.get("image"):
                    payload["image"] = old["image"]
                if all((old.get(k) or "") == (payload.get(k) or "") for k in FIELDS):
                    counts["unchanged"] += 1
                else:
                    client.table("events").update(payload).eq("id", old["id"]).execute()
                    counts["updated"] += 1

        except Exception as exc:
            code = getattr(exc, "code", "unknown")
            LOG.error("Database write failed for %s (%s, code=%s)", link, type(exc).__name__, code)
            counts["failed"] += 1

    LOG.info("Database results: %s", counts)
    return counts


def load_extractor_env(env_file=None):
    script_dir = Path(__file__).resolve().parent
    env_path = Path(env_file).expanduser() if env_file else script_dir / ".env.extractor"
    if not env_path.is_absolute():
        env_path = (Path.cwd() / env_path).resolve()

    if not env_path.exists():
        raise SystemExit(f"Extractor environment file not found: {env_path}")

    loaded = []
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key, "").strip():
            os.environ[key] = value
            loaded.append(key)

    LOG.info(
        "Loaded extractor environment from %s (%s)",
        env_path,
        ", ".join(loaded) if loaded else "no new values",
    )
    return env_path


def build_supabase_client(args):
    if args.dry_run:
        return None

    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = (os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SECRET_KEY") or "").strip()

    if sys.stdin.isatty():
        if not url:
            url = input("Supabase Project URL: ").strip()
        if not key:
            key = getpass.getpass("Supabase SECRET/service_role key (hidden): ").strip()

    if not url or not key or "YOUR_" in url or "YOUR_" in key:
        raise SystemExit("Set SUPABASE_URL and SUPABASE_KEY, or use --dry-run.")
    if not url.startswith("https://"):
        raise SystemExit("Use the HTTPS Project URL from Supabase.")
    if key.startswith("sb_publishable_"):
        raise SystemExit("Use the backend Supabase SECRET/service_role key, not the frontend publishable key.")

    return create_client(url, key)


# ---------------- Job / CLI ----------------

def job(fetcher, client, args):
    sources = load_sources(args.links)
    LOG.info("Loaded %s external source(s) from %s", len(sources), args.links)

    collected = []
    healthy = True

    for line_no, source_url in sources:
        LOG.info("[%s] Extracting %s", line_no, source_url)
        rows, ok = extract_source(fetcher, source_url, args.max_pages)
        healthy = healthy and ok
        LOG.info(
            "[%s] %s Waterloo/Kitchener record(s); %s",
            line_no,
            len(rows),
            "OK" if ok else "PARTIAL/FAILED",
        )
        collected.extend(rows)

    rows = dedupe_rows(collected)
    LOG.info("Collected %s distinct Waterloo/Kitchener event row(s)", len(rows))

    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        LOG.info("Preview only: nothing written to Supabase")
        return bool(rows)

    if not rows:
        LOG.error("No Waterloo/Kitchener events were found. Nothing was changed in Supabase.")
        return False

    db_result = save_events(client, rows)
    return healthy and db_result["failed"] == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--links",
        default="links_external.txt",
        help="External seed URL file beside this script (default: links_external.txt)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print extracted rows once; do not connect to Supabase")
    parser.add_argument("--once", action="store_true", help="Import once, then exit")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Maximum listing pages per source; 0 scans all discoverable pages (default: 0)",
    )
    parser.add_argument("--interval", type=int, default=300, help="Seconds between completed runs (default: 300)")
    parser.add_argument("--env-file", default=None, help="Backend env file (default: .env.extractor beside script)")
    args = parser.parse_args()

    if args.max_pages < 0:
        parser.error("--max-pages cannot be negative")
    if args.interval < 60:
        parser.error("--interval must be at least 60 seconds")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    if not args.dry_run:
        load_extractor_env(args.env_file)
    client = build_supabase_client(args)
    fetcher = Fetcher()

    try:
        while True:
            ok = job(fetcher, client, args)
            if args.once or args.dry_run:
                return 0 if ok else 1
            LOG.info("Next external extraction in %s seconds; Ctrl+C stops it", args.interval)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        LOG.info("External importer stopped")
        return 0
    finally:
        fetcher.close()


if __name__ == "__main__":
    sys.exit(main())
