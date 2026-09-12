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
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger("unievent")
TORONTO = ZoneInfo("America/Toronto")
FIELDS = ("text", "description", "image", "link_to_external", "category")

SOCIAL_HOSTS = {"instagram.com", "www.instagram.com", "facebook.com", "www.facebook.com"}

FINANCIAL_WORDS = (
    "award", "awards", "bursary", "bursaries", "scholarship", "scholarships",
    "financial aid", "funding", "osap", "student aid", "tuition", "fee deadline",
)

EVENT_WORDS = (
    "event", "workshop", "seminar", "lecture", "conference", "competition",
    "hackathon", "fair", "social", "mixer", "gala", "concert", "festival",
    "reception", "info session", "information session", "meetup", "tournament",
)


def text_of(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return " ".join(BeautifulSoup(html.unescape(str(value)), "html.parser").get_text(" ", strip=True).split())


def http_url(base, value, keep_fragment=False):
    if not value or not str(value).strip():
        return ""
    p = urlsplit(urljoin(base, str(value).strip()))
    if p.scheme not in ("https", "http") or not p.hostname or p.username:
        return ""
    fragment = p.fragment if keep_fragment else ""
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, fragment))


def canonical_source_url(url):
    p = urlsplit(url.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))


def stable_source_link(source_url, identity):
    """Create a stable per-record link when a feed item has no public event URL."""
    digest = hashlib.sha1(identity.encode("utf-8", errors="ignore")).hexdigest()[:16]
    p = urlsplit(source_url)
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, "unievent-" + digest))


def classify_event(title, description):
    combined = (title + " " + description).lower()
    rules = [
        ("Key Deadlines", ["deadline", "due date", "award", "bursary", "scholarship", "funding", "osap"]),
        ("Design Teams", ["design team", "student design centre", "baja", "formula", "rocketry"]),
        ("Competitions", ["hackathon", "competition", "pitch", "tournament", "prize"]),
        ("Residence Events", ["residence", "rev", "mkv", "v1", "uwp", "cmh", "dorm"]),
        ("Academic Events", ["seminar", "lecture", "workshop", "tutorial", "study session", "resume", "career", "employer", "information session"]),
        ("Clubs", ["club", "wusa", "society", "association"]),
        ("Social Events", ["party", "gala", "mixer", "social", "gathering", "food", "drinks", "festival", "concert"]),
    ]
    for category, words in rules:
        if any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", combined) for word in words):
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
        self.session.headers["User-Agent"] = "UniEventImporter/2.0 (public event listings; contact: local student project)"
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
        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and not response.text.lstrip().startswith("<"):
            raise ValueError("Expected HTML but source returned " + content_type)
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
            LOG.warning("links.txt line %s is not a valid HTTP(S) URL; skipped", line_no)
            continue
        key = canonical_source_url(url)
        if key in seen:
            LOG.warning("Duplicate source URL at line %s; skipped: %s", line_no, url)
            continue
        seen.add(key)
        urls.append((line_no, url))
    return urls


def pagination_links(soup, page_url, first_url):
    """Return pagination URLs advertised by a listing page.

    We only inspect links that look like pagination controls (Next/Previous, numbered
    page links, pager/pagination containers, or URLs with page/paged/offset/start
    parameters). This is deliberately *not* a general website crawler: event detail
    links are handled by the parsers, while pagination stays on the seed source host.
    """
    first_host = urlsplit(first_url).netloc.lower()
    found = []
    seen = set()

    selectors = (
        ".pager a[href], .pagination a[href], nav.pagination a[href], "
        "nav[aria-label*='pagination' i] a[href], [class*='pagination'] a[href], "
        "[class*='pager'] a[href], a.page-numbers[href], "
        "a[rel='next'][href], a[rel='prev'][href], "
        "a[aria-label*='next' i][href], a[aria-label*='previous' i][href], "
        "a[title*='next' i][href], a[title*='previous' i][href], "
        ".tribe-events-c-nav a[href], .tribe-events-nav-pagination a[href], "
        ".tribe-events-nav-next a[href], .tribe-events-nav-previous a[href]"
    )

    candidates = list(soup.select(selectors))

    # Some sites do not wrap numeric page links in a recognizable pagination
    # container. Include only anchors whose URL itself clearly encodes pagination.
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        text = text_of(anchor).strip()
        parsed = urlsplit(urljoin(page_url, href))
        query_keys = {key.lower() for key in parse_qs(parsed.query).keys()}
        path_has_page = bool(re.search(r"/(?:page|paged)/?\d+(?:/|$)", parsed.path, re.I))
        query_has_page = bool(query_keys & {"page", "paged", "pageno", "page_num", "offset", "start"})
        if (path_has_page or query_has_page) and (text.isdigit() or re.search(r"next|previous|older|newer|more", text, re.I)):
            candidates.append(anchor)

    for anchor in candidates:
        candidate = http_url(page_url, anchor.get("href"))
        if not candidate:
            continue
        parsed = urlsplit(candidate)
        if parsed.netloc.lower() != first_host:
            continue
        key = canonical_source_url(candidate)
        if key == canonical_source_url(page_url) or key in seen:
            continue
        seen.add(key)
        found.append(candidate)

    return found


def page_sequence(fetcher, first_url, max_pages=0):
    """Visit every discoverable pagination page for one seed source.

    ``max_pages=0`` means unlimited and is the default. A positive value is an
    optional safety/debug cap. Pages are discovered from the site's own pagination
    controls, including numbered links (1, 2, 3, ...) and Next/Previous links.
    """
    queue = [first_url]
    queued = {canonical_source_url(first_url)}
    visited = set()
    fetched = 0

    while queue:
        if max_pages and fetched >= max_pages:
            LOG.info("Page limit %s reached for %s; %s pagination page(s) remain undiscovered/fetched",
                     max_pages, first_url, len(queue))
            return

        url = queue.pop(0)
        key = canonical_source_url(url)
        if key in visited:
            continue
        visited.add(key)

        soup = fetcher.get_html(url)
        fetched += 1
        LOG.info("Pagination: fetched page %s for %s -> %s", fetched, first_url, url)
        yield soup, url

        for candidate in pagination_links(soup, url, first_url):
            candidate_key = canonical_source_url(candidate)
            if candidate_key in visited or candidate_key in queued:
                continue
            queued.add(candidate_key)
            queue.append(candidate)

    if fetched > 1:
        LOG.info("Pagination complete for %s: fetched all %s discoverable pages", first_url, fetched)


# ---------- Structured-data extraction ----------

def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def is_event_jsonld(obj):
    kinds = obj.get("@type", []) if isinstance(obj, dict) else []
    if isinstance(kinds, str):
        kinds = [kinds]
    return any(str(kind).lower().endswith("event") for kind in kinds)


def jsonld_location(value):
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
            key = (title, start, link)
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
            row = make_row(title, "\n\n".join(parts), link, jsonld_image(obj.get("image"), page_url))
            if row:
                rows.append(row)
    return rows


# ---------- University of Waterloo Drupal pages ----------

def parse_uw_event_cards(soup, page_url, source_label):
    rows = []
    cards = soup.select("article.card__teaser--event")
    for card in cards:
        anchor = card.select_one(".card__title a[href]") or card.select_one("h2 a[href], h3 a[href]")
        title = text_of(anchor)
        link = http_url(page_url, anchor.get("href")) if anchor else ""
        if not title or not link:
            continue
        img = card.select_one(".card__image img[src], img[src]")
        body = text_of(card.select_one(".card__content"))
        date_text = text_of(card.select_one(".card__date, time"))
        parts = [f"Source: {source_label}"]
        if date_text:
            parts.append("Date: " + date_text)
        if body:
            parts.append(body)
        row = make_row(title, "\n\n".join(parts), link, http_url(page_url, img.get("src")) if img else "")
        if row:
            rows.append(row)
    return rows


def enrich_uw_detail(fetcher, row):
    try:
        detail = fetcher.get_html(row["link_to_external"])
        article = detail.select_one("article.uw-node__node, main")
        if not article:
            return row
        body_nodes = article.select(".card__body .card__content, .uw-copy, .field--name-body")
        body = " ".join(filter(None, (text_of(node) for node in body_nodes)))
        location = ""
        address = article.select_one(".card__location .card__address, .event-location, [class*='location'] address")
        if address:
            for label in address.select(".uw-label"):
                label.decompose()
            location = text_of(address)
        desc = row["description"]
        if location and "Location:" not in desc:
            desc += "\n\nLocation: " + location
        if body and body not in desc:
            desc += "\n\n" + body
        row["description"] = clean_text(desc)[:12000]
        return row
    except Exception as exc:
        LOG.warning("Detail unavailable for %s (%s)", row["link_to_external"], type(exc).__name__)
        return row


def extract_uw_event_index(fetcher, source_url, max_pages):
    label = "University of Waterloo — " + urlsplit(source_url).path.strip("/").replace("/events", "").replace("-", " ").title()
    rows = []
    healthy = True
    try:
        for soup, page_url in page_sequence(fetcher, source_url, max_pages):
            current = parse_uw_event_cards(soup, page_url, label)
            if not current:
                current = parse_jsonld_events(soup, page_url, label)
            rows.extend(current)
    except Exception as exc:
        LOG.error("UW source failed %s (%s): %s", source_url, type(exc).__name__, exc)
        return rows, False

    # Only spend detail requests on a bounded number of real event rows.
    enriched = []
    for row in rows[:80]:
        enriched.append(enrich_uw_detail(fetcher, row))
    if len(rows) > 80:
        enriched.extend(rows[80:])
    return enriched, healthy


def parse_important_dates(soup, page_url, financial_only=True):
    table = next((t for t in soup.select("table") if all(
        word in text_of(t.select_one("thead")).lower()
        for word in ("title", "description", "academic term", "date")
    )), None)
    if table is None:
        return []
    rows = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) != 4:
            continue
        title_cell, desc_cell, term_cell, date_cell = cells
        anchor = title_cell.find("a", href=True)
        title = text_of(anchor) or text_of(title_cell)
        description = text_of(desc_cell)
        haystack = (title + " " + description).lower()
        if financial_only and not any(word in haystack for word in FINANCIAL_WORDS):
            continue
        link = http_url(page_url, anchor.get("href")) if anchor else stable_source_link(page_url, title + text_of(date_cell))
        parts = [
            "Source: University of Waterloo undergraduate important dates",
            "Date: " + text_of(date_cell),
            "Academic term: " + text_of(term_cell),
            description,
        ]
        row = make_row(title, "\n\n".join(filter(None, parts)), link, category="Key Deadlines")
        if row:
            rows.append(row)
    return rows


def extract_important_dates(fetcher, source_url, max_pages):
    rows = []
    try:
        for soup, page_url in page_sequence(fetcher, source_url, max_pages):
            rows.extend(parse_important_dates(soup, page_url, financial_only=True))
        return rows, True
    except Exception as exc:
        LOG.error("Important dates failed (%s): %s", type(exc).__name__, exc)
        return rows, False


def extract_bursary_deadlines(fetcher, source_url):
    try:
        soup = fetcher.get_html(source_url)
        text = text_of(soup)
        # The page currently publishes term ranges such as:
        # Fall 2026: July 27 to October 16
        pattern = re.compile(r"\b(Fall|Winter|Spring)\s+(20\d{2})\s*:\s*([^|•]+?)(?=\b(?:Fall|Winter|Spring)\s+20\d{2}\s*:|How to apply|$)", re.I)
        rows = []
        for match in pattern.finditer(text):
            term = f"{match.group(1).title()} {match.group(2)}"
            date_text = clean_text(match.group(3))[:250]
            if not date_text:
                continue
            title = f"Student bursary application — {term}"
            link = stable_source_link(source_url, term)
            desc = f"Source: University of Waterloo student bursaries\n\nApplication window/deadline: {date_text}"
            row = make_row(title, desc, link, category="Key Deadlines")
            if row:
                rows.append(row)
        if not rows:
            raise ValueError("No bursary term deadlines recognized")
        return rows, True
    except Exception as exc:
        LOG.error("Bursary deadline source failed (%s): %s", type(exc).__name__, exc)
        return [], False


def extract_ogs_deadlines(fetcher, source_url):
    try:
        soup = fetcher.get_html(source_url)
        main = soup.select_one("main") or soup
        blocks = []
        for heading in main.find_all(["h2", "h3", "h4"]):
            title = text_of(heading)
            if not re.search(r"deadline|important date|timeline|application", title, re.I):
                continue
            pieces = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ("h2", "h3", "h4"):
                    break
                value = text_of(sibling)
                if value:
                    pieces.append(value)
                if sum(map(len, pieces)) > 3500:
                    break
            body = " ".join(pieces)
            if re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b|20\d{2}", body, re.I):
                blocks.append((title, body))
        if not blocks:
            raise ValueError("No dated OGS/QEII application section recognized")
        rows = []
        for idx, (section, body) in enumerate(blocks):
            title = "OGS / QEII-GSST — " + section
            row = make_row(
                title,
                "Source: University of Waterloo OGS/QEII-GSST\n\n" + body,
                stable_source_link(source_url, section + str(idx)),
                category="Key Deadlines",
            )
            if row:
                rows.append(row)
        return rows, True
    except Exception as exc:
        LOG.error("OGS/QEII source failed (%s): %s", type(exc).__name__, exc)
        return [], False


# ---------- iCalendar / Google Calendar ----------

def unfold_ics(text):
    return re.sub(r"\r?\n[ \t]", "", text)


def calendar_ids_from_embed_url(url):
    query = parse_qs(urlsplit(url).query)
    return [value for value in query.get("src", []) if value]


def google_ics_url(calendar_id):
    return "https://calendar.google.com/calendar/ical/" + quote(calendar_id, safe="") + "/public/basic.ics"


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


def not_stale(dt_value):
    if isinstance(dt_value, datetime):
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=TORONTO)
        return dt_value.astimezone(TORONTO) >= datetime.now(TORONTO) - timedelta(days=1)
    if isinstance(dt_value, date):
        return dt_value >= datetime.now(TORONTO).date() - timedelta(days=1)
    return True


def parse_icalendar(text, source_url, source_label):
    try:
        from icalendar import Calendar
    except ImportError as exc:
        raise RuntimeError("Install iCalendar support with: py -m pip install icalendar") from exc

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
        link = http_url(source_url, public_url) if public_url else stable_source_link(source_url, uid or (title + dt_to_text(start)))
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


def extract_google_calendar(fetcher, source_url, source_label="Google Calendar"):
    ids = calendar_ids_from_embed_url(source_url)
    if not ids:
        return [], False
    rows = []
    healthy = True
    for calendar_id in ids:
        try:
            ics = fetcher.get_text(google_ics_url(calendar_id), "text/calendar,*/*;q=0.5")
            rows.extend(parse_icalendar(ics, source_url, source_label))
        except Exception as exc:
            LOG.error("Google Calendar %s failed (%s): %s", calendar_id, type(exc).__name__, exc)
            healthy = False
    return rows, healthy


def extract_embedded_google_calendar(fetcher, source_url, source_label):
    try:
        soup = fetcher.get_html(source_url)
        iframe_urls = []
        for iframe in soup.select("iframe[src*='calendar.google.com']"):
            src = http_url(source_url, iframe.get("src"))
            if src:
                iframe_urls.append(src)
        if not iframe_urls:
            raise ValueError("No public Google Calendar iframe found")
        rows = []
        healthy = True
        for iframe_url in iframe_urls:
            current, ok = extract_google_calendar(fetcher, iframe_url, source_label)
            rows.extend(current)
            healthy = healthy and ok
        return rows, healthy
    except Exception as exc:
        LOG.error("Embedded calendar source failed %s (%s): %s", source_url, type(exc).__name__, exc)
        return [], False


# ---------- Other public event sources ----------

def extract_wusa(fetcher, source_url, max_pages):
    rows = []
    healthy = True
    # WUSA currently runs a conventional event calendar. JSON-LD is the safest
    # primary parser because class names can vary between list/photo views.
    try:
        for soup, page_url in page_sequence(fetcher, source_url, max_pages):
            current = parse_jsonld_events(soup, page_url, "WUSA")
            if not current:
                # Conservative fallback: only elements whose class identifies them as events.
                for block in soup.select("article[class*='event'], div[class*='tribe-events'][class*='event']"):
                    anchor = block.select_one("h2 a[href], h3 a[href], a[class*='event-title'][href]")
                    if not anchor:
                        continue
                    title = text_of(anchor)
                    link = http_url(page_url, anchor.get("href"))
                    date_text = text_of(block.select_one("time, [class*='datetime'], [class*='date']"))
                    body = text_of(block.select_one("[class*='description'], [class*='excerpt']"))
                    row = make_row(title, "\n\n".join(filter(None, ["Source: WUSA", "Date: " + date_text if date_text else "", body])), link)
                    if row:
                        current.append(row)
            rows.extend(current)
    except Exception as exc:
        LOG.error("WUSA extraction failed (%s): %s", type(exc).__name__, exc)
        healthy = False
    return rows, healthy


def extract_csc(fetcher, source_url, max_pages):
    rows = []
    healthy = True
    try:
        for soup, page_url in page_sequence(fetcher, source_url, max_pages):
            current = parse_jsonld_events(soup, page_url, "University of Waterloo Computer Science Club")
            if current:
                rows.extend(current)
                continue

            # CSC's simple page publishes event title + date/location under headings.
            main = soup.select_one("main") or soup
            for heading in main.find_all(["h2", "h3"]):
                anchor = heading.find("a", href=True)
                title = text_of(anchor or heading)
                if not title or title.lower() in {"past events", "events"}:
                    continue
                sibling_text = []
                for sibling in heading.find_next_siblings():
                    if sibling.name in ("h1", "h2", "h3"):
                        break
                    value = text_of(sibling)
                    if value:
                        sibling_text.append(value)
                    if len(sibling_text) >= 3:
                        break
                body = " ".join(sibling_text)
                if not re.search(r"\b20\d{2}\b", body):
                    continue
                link = http_url(page_url, anchor.get("href")) if anchor else stable_source_link(page_url, title + body)
                row = make_row(title, "Source: UW Computer Science Club\n\n" + body, link, category="Clubs")
                if row:
                    rows.append(row)
        return rows, healthy
    except Exception as exc:
        LOG.error("CSC source failed (%s): %s", type(exc).__name__, exc)
        return rows, False


def extract_generic_event_page(fetcher, source_url, max_pages, source_label=None):
    label = source_label or urlsplit(source_url).netloc
    rows = []
    healthy = True
    try:
        for soup, page_url in page_sequence(fetcher, source_url, max_pages):
            current = parse_jsonld_events(soup, page_url, label)
            if not current:
                current = parse_uw_event_cards(soup, page_url, label)
            rows.extend(current)
    except Exception as exc:
        LOG.error("Generic event source failed %s (%s): %s", source_url, type(exc).__name__, exc)
        healthy = False
    return rows, healthy


def extract_imprint_roundups(fetcher, source_url, max_pages):
    """Discover event roundup articles across every paginated Arts & Life page.

    This intentionally returns no database rows until a safe per-event article parser is
    implemented. Matching roundup links are logged instead of treating an article as one event.
    """
    matches = []
    try:
        for soup, page_url in page_sequence(fetcher, source_url, max_pages):
            for anchor in soup.find_all("a", href=True):
                title = text_of(anchor)
                if re.search(r"on-campus events|weekend adventures", title, re.I):
                    matches.append(http_url(page_url, anchor["href"]))
        matches = list(dict.fromkeys(filter(None, matches)))
        if matches:
            LOG.info("Imprint: discovered %s roundup article(s) across all pagination pages; individual-event parser intentionally not guessed", len(matches))
            return [], True
        raise ValueError("No event-roundup article links recognized")
    except Exception as exc:
        LOG.error("Imprint monitoring failed (%s): %s", type(exc).__name__, exc)
        return [], False


def extract_social_adapter(urls):
    try:
        import instagram  # user's separately authorized adapter
    except ImportError:
        LOG.warning("Social sources requested but instagram.py is not beside extraction.py")
        return [], False
    fn = getattr(instagram, "extract_social_events", None)
    if not callable(fn):
        LOG.error("instagram.py must define extract_social_events(urls)")
        return [], False
    try:
        result = fn(urls)
        if isinstance(result, tuple) and len(result) == 2:
            rows, healthy = result
        else:
            rows, healthy = result, True
        clean_rows = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            candidate = {field: clean_text(row.get(field)) if field in ("text", "description", "category") else str(row.get(field) or "") for field in FIELDS}
            if candidate["text"] and candidate["link_to_external"]:
                if not candidate["category"]:
                    candidate["category"] = classify_event(candidate["text"], candidate["description"])
                clean_rows.append(candidate)
        return clean_rows, bool(healthy)
    except Exception as exc:
        LOG.error("Social adapter failed (%s): %s", type(exc).__name__, exc)
        return [], False


# ---------- Routing ----------

def route_source(fetcher, line_no, source_url, max_pages):
    p = urlsplit(source_url)
    host = p.netloc.lower()
    path = p.path.rstrip("/")

    if host in SOCIAL_HOSTS:
        return None  # batched later

    if host == "calendar.google.com":
        return extract_google_calendar(fetcher, source_url, f"links.txt line {line_no} Google Calendar")

    if host == "wusa.ca" and path.startswith("/events"):
        return extract_wusa(fetcher, source_url, max_pages)

    if host == "www.engsoc.uwaterloo.ca" and "/events/calendar" in path:
        return extract_embedded_google_calendar(fetcher, source_url, "Waterloo Engineering Society")

    if host == "uwafsa.com" and path.startswith("/calendar"):
        return extract_embedded_google_calendar(fetcher, source_url, "UW Accounting & Finance Student Association")

    if host == "csclub.uwaterloo.ca" and path.startswith("/events"):
        return extract_csc(fetcher, source_url, max_pages)

    if host.endswith("uwaterloo.ca") and path == "/important-dates/undergraduate":
        return extract_important_dates(fetcher, source_url, max_pages)

    if host.endswith("uwaterloo.ca") and path.endswith("/student-bursaries"):
        return extract_bursary_deadlines(fetcher, source_url)

    if host.endswith("uwaterloo.ca") and "OGS-QEII" in p.path:
        return extract_ogs_deadlines(fetcher, source_url)

    if host.endswith("uwaterloo.ca") and path == "/awards-directory":
        LOG.warning("Awards Directory is a dynamic Quest guest application; landing page is monitored but not scraped as fake award rows")
        try:
            fetcher.get_html(source_url)
            return [], True
        except Exception as exc:
            LOG.error("Awards Directory landing page failed (%s): %s", type(exc).__name__, exc)
            return [], False

    if host.endswith("uwaterloo.ca") and (path.endswith("/events") or path == "/events"):
        return extract_uw_event_index(fetcher, source_url, max_pages)

    if host == "uwimprint.ca" and path.startswith("/arts-life"):
        return extract_imprint_roundups(fetcher, source_url, max_pages)

    # Athletics, Uptown Waterloo, City calendar, MathSoc, and any newly added
    # public source use structured Event JSON-LD / conservative event-card fallback.
    return extract_generic_event_page(fetcher, source_url, max_pages)


def dedupe_rows(rows):
    """Prefer a real event URL; dedupe exact links, then obvious title/date duplicates."""
    by_link = {}
    title_fingerprints = set()
    for row in rows:
        if not row or not row.get("text") or not row.get("link_to_external"):
            continue
        link = row["link_to_external"]
        title_key = re.sub(r"\W+", " ", row["text"].lower()).strip()
        # Pull an ISO date or a Month dd, yyyy-ish token from description when possible.
        desc = row.get("description", "")
        date_match = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", desc)
        fingerprint = (title_key, date_match.group(0) if date_match else "")
        if link in by_link:
            old = by_link[link]
            if len(row.get("description", "")) > len(old.get("description", "")):
                by_link[link] = row
            continue
        if fingerprint[1] and fingerprint in title_fingerprints:
            continue
        by_link[link] = row
        if fingerprint[1]:
            title_fingerprints.add(fingerprint)
    return list(by_link.values())


# ---------- Supabase ----------

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
                if all((old.get(key) or "") == (payload.get(key) or "") for key in FIELDS):
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


def job(fetcher, client, args):
    sources = load_sources(args.links)
    LOG.info("Loaded %s distinct sources from %s", len(sources), args.links)

    collected = []
    healthy = True
    social_urls = []

    for line_no, source_url in sources:
        if urlsplit(source_url).netloc.lower() in SOCIAL_HOSTS:
            social_urls.append(source_url)
            continue
        LOG.info("[%s] Extracting %s", line_no, source_url)
        result = route_source(fetcher, line_no, source_url, args.max_pages)
        if result is None:
            continue
        rows, ok = result
        healthy = healthy and ok
        LOG.info("[%s] %s record(s); %s", line_no, len(rows), "OK" if ok else "PARTIAL/FAILED")
        collected.extend(rows)

    if social_urls:
        if args.include_social:
            social_rows, ok = extract_social_adapter(social_urls)
            healthy = healthy and ok
            collected.extend(social_rows)
            LOG.info("Social adapter: %s record(s); %s", len(social_rows), "OK" if ok else "PARTIAL/FAILED")
        else:
            LOG.info("Skipping %s social source(s); use --include-social after configuring instagram.py", len(social_urls))

    rows = dedupe_rows(collected)
    LOG.info("Collected %s distinct event/deadline rows after cross-source deduplication", len(rows))

    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        LOG.info("Preview only: nothing written to Supabase")
        return healthy and bool(rows)

    if not rows:
        LOG.error("No records to import. Nothing was changed in Supabase.")
        return False

    db_result = save_events(client, rows)
    return healthy and db_result["failed"] == 0


def load_extractor_env(env_file=None):
    """Load backend-only Supabase credentials from an env file.

    Default location is .env.extractor beside extraction.py.  An explicit path may
    be supplied with --env-file.  Empty pre-existing environment variables are
    replaced by values from the file. UTF-8 BOM files are supported.
    """
    script_dir = Path(__file__).resolve().parent
    env_path = Path(env_file).expanduser() if env_file else script_dir / ".env.extractor"
    if not env_path.is_absolute():
        # Interpret relative --env-file paths from the current working directory,
        # which makes `py ../extraction.py --env-file ../.env.extractor` intuitive.
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

    LOG.info("Loaded extractor environment from %s (%s)",
             env_path, ", ".join(loaded) if loaded else "no new values")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--links", default="links.txt", help="Seed URL file beside this script (default: links.txt)")
    parser.add_argument("--dry-run", action="store_true", help="Print extracted rows once; do not connect to Supabase")
    parser.add_argument("--once", action="store_true", help="Import once, then exit")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum listing pages per source; 0 = all discoverable pages (default: 0)")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between completed runs (default: 300)")
    parser.add_argument("--include-social", action="store_true", help="Use optional instagram.py adapter for links.txt social entries")
    parser.add_argument("--env-file", default=None, help="Backend env file (default: .env.extractor beside extraction.py)")
    args = parser.parse_args()

    if args.max_pages < 0:
        parser.error("--max-pages must be 0 (all pages) or a positive integer")
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
            LOG.info("Next run in %s seconds; Ctrl+C stops the importer", args.interval)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        LOG.info("Importer stopped")
        return 0
    finally:
        fetcher.close()


if __name__ == "__main__":
    sys.exit(main())

