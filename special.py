from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LOG = logging.getLogger("wat2do")

# Current Waterloo-specific site. The old .ca site currently points users to
# the new Wat2Do platform, so it is only a legacy fallback.
PRIMARY_HOME = "https://uwaterloo.wat2do.io/"
GENERIC_HOME = "https://wat2do.io/"
LEGACY_HOME = "https://wat2do.ca/"

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
ACCESS_CONTROL_STATUS = {401, 403}

EVENT_HREF_RE = re.compile(r"""(?:https?://[^"'<> ]+)?/events/\d+(?:[/?#][^"'<> ]*)?""", re.I)
MONTH_RE = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?"
)
DATE_RE = re.compile(
    rf"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday,\s*)?"
    rf"(?P<month>{MONTH_RE})\.?\s+(?P<day>\d{{1,2}})"
    rf"(?:,\s*(?P<year>20\d{{2}}))?\b",
    re.I,
)
TIME_RE = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:AM|PM)"
    r"(?:\s*(?:to|-|–|—)\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))?\b",
    re.I,
)

BAD_LOCATION_TEXT = {
    "registration",
    "going",
    "share",
    "report",
    "email address",
    "all events",
    "about event",
    "hosted by",
}

CATEGORY_RULES = [
    ("Key Deadlines", ["deadline", "due date", "application closes", "apply by"]),
    ("Design Teams", ["design team", "formula electric", "rocketry", "baja", "robotics"]),
    ("Competitions", ["hackathon", "competition", "tournament", "tryout", "pitch"]),
    ("Residence Events", ["residence", "village 1", "ron eydt", "mkv", "uwp", "cmh"]),
    (
        "Academic Events",
        [
            "seminar",
            "lecture",
            "workshop",
            "tutorial",
            "resume",
            "career",
            "information session",
            "networking",
            "conference",
        ],
    ),
    ("Clubs", ["club", "society", "association", "wusa", "mathsoc", "engsoc"]),
    (
        "Social Events",
        [
            "party",
            "gala",
            "mixer",
            "social",
            "bbq",
            "karaoke",
            "concert",
            "festival",
            "game night",
            "welcome",
        ],
    ),
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split())


def text_of(node) -> str:
    return clean_text(node.get_text(" ", strip=True)) if node else ""


def canonical_http_url(base: str, value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(urljoin(base, value.strip()))
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def classify_event(title: str, description: str, host: str = "") -> str:
    combined = f"{title} {description} {host}".lower()
    for category, words in CATEGORY_RULES:
        if any(word in combined for word in words):
            return category
    return "General"


def _truthy_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class Wat2DoFetcher:
    """Small HTTP client with transient-error retry and polite pacing."""

    def __init__(self, delay: float = 0.35):
        self.delay = max(0.0, delay)
        self.last_request = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                # Browser-like but truthful generic UA. This is not intended to
                # evade access controls; it avoids servers rejecting Python's
                # default requests user agent.
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/152.0 Safari/537.36 UniEvent-Wat2Do/1.0"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-CA,en;q=0.9",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        )
        retry = Retry(
            total=4,
            connect=3,
            read=3,
            status=4,
            backoff_factor=1.0,
            status_forcelist=sorted(RETRYABLE_STATUS),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _pace(self):
        remaining = self.delay - (time.monotonic() - self.last_request)
        if remaining > 0:
            time.sleep(remaining)

    def get_html(self, url: str) -> tuple[str, str]:
        self._pace()
        self.last_request = time.monotonic()

        response = self.session.get(
            url,
            timeout=(12, 35),
            allow_redirects=True,
        )

        if response.status_code in ACCESS_CONTROL_STATUS:
            raise PermissionError(
                f"Wat2Do returned HTTP {response.status_code}. "
                "The adapter will not attempt to defeat an access-control page."
            )

        if response.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {response.status_code} while reading {response.url}",
                response=response,
            )

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "<html" not in response.text[:1000].lower():
            raise ValueError(
                f"Expected HTML from {response.url}, got {content_type or 'unknown content type'}"
            )

        return response.text, response.url

    def close(self):
        self.session.close()


def _render_with_playwright(url: str, scrolls: int = 8) -> tuple[str, str]:
    """
    Normal browser-rendering fallback for client-side JavaScript.

    This does not solve CAPTCHAs or bypass authentication/access controls.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright fallback requested but Playwright is not installed. "
            "Run: py -m pip install playwright && py -m playwright install chromium"
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1000},
            locale="en-CA",
        )
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if response and response.status in ACCESS_CONTROL_STATUS:
            browser.close()
            raise PermissionError(
                f"Browser received HTTP {response.status}; refusing to bypass access controls."
            )

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Wat2Do may lazy-load more events as the page scrolls.
        last_height = 0
        for _ in range(max(1, scrolls)):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(900)
            try:
                height = page.evaluate("document.body.scrollHeight")
            except Exception:
                break
            if height == last_height:
                break
            last_height = height

        rendered = page.content()
        final_url = page.url
        browser.close()
        return rendered, final_url


def _candidate_home_pages() -> list[str]:
    override = os.getenv("WAT2DO_URL", "").strip()
    candidates = []
    if override:
        candidates.append(override)

    # Current address first. Generic and legacy addresses are fallback routes,
    # mainly useful if Wat2Do changes its redirect setup.
    candidates.extend([PRIMARY_HOME, GENERIC_HOME, LEGACY_HOME])

    seen = set()
    result = []
    for item in candidates:
        item = canonical_http_url(PRIMARY_HOME, item)
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _looks_like_waterloo_home(html_text: str, final_url: str) -> bool:
    text = BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True).lower()
    host = urlsplit(final_url).hostname or ""
    return (
        "university of waterloo" in text
        or "uwaterloo" in host.lower()
        or "waterloo events" in text
    )


def discover_event_urls(
    fetcher: Wat2DoFetcher,
    allow_browser_fallback: bool = False,
) -> tuple[list[str], str, bool]:
    """
    Find Wat2Do event detail URLs.

    Returns (event_urls, working_home_url, used_browser_fallback).
    """
    last_error: Exception | None = None

    for home in _candidate_home_pages():
        try:
            html_text, final_url = fetcher.get_html(home)
        except Exception as exc:
            last_error = exc
            LOG.warning("Wat2Do home failed at %s: %s", home, exc)
            continue

        # The old .ca page says it is moving. If it redirects or links to the
        # new site, do not treat "0 Upcoming events" as authoritative.
        soup = BeautifulSoup(html_text, "html.parser")
        page_text = text_of(soup)
        if (
            "moving to a new home" in page_text.lower()
            and "wat2do.io" in page_text.lower()
        ):
            LOG.info("Legacy Wat2Do page detected; trying the new .io site")
            continue

        event_urls = extract_event_urls_from_html(html_text, final_url)
        if event_urls:
            return event_urls, final_url, False

        if allow_browser_fallback and _looks_like_waterloo_home(html_text, final_url):
            try:
                rendered, rendered_url = _render_with_playwright(final_url)
                event_urls = extract_event_urls_from_html(rendered, rendered_url)
                if event_urls:
                    return event_urls, rendered_url, True
            except Exception as exc:
                last_error = exc
                LOG.warning("Playwright rendering failed for %s: %s", final_url, exc)

        last_error = RuntimeError(
            f"Wat2Do loaded at {final_url}, but no /events/<id> links were found."
        )

    if last_error:
        raise last_error
    raise RuntimeError("No Wat2Do candidate URL could be read.")


def extract_event_urls_from_html(html_text: str, base_url: str) -> list[str]:
    """Collect unique Wat2Do /events/<number> detail URLs."""
    soup = BeautifulSoup(html_text, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None):
        if not raw:
            return
        url = canonical_http_url(base_url, raw)
        if not url:
            return
        parsed = urlsplit(url)
        if not re.fullmatch(r"/events/\d+/?", parsed.path):
            return
        # Keep Wat2Do event links only.
        if not (parsed.hostname or "").lower().endswith("wat2do.io"):
            return
        clean = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
        if clean not in seen:
            seen.add(clean)
            urls.append(clean)

    for anchor in soup.find_all("a", href=True):
        add(anchor.get("href"))

    # Next.js/React applications sometimes serialize route URLs inside script
    # tags instead of putting every lazy-loaded item in an anchor immediately.
    for match in EVENT_HREF_RE.findall(html_text):
        add(match)

    return urls


def _iter_json_objects(value: Any) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_json_objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_objects(item)


def _jsonld_event(soup: BeautifulSoup) -> dict | None:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for obj in _iter_json_objects(data):
            obj_type = obj.get("@type")
            if isinstance(obj_type, list):
                is_event = any(str(x).lower() == "event" for x in obj_type)
            else:
                is_event = str(obj_type).lower() == "event"
            if is_event:
                return obj
    return None


def _jsonld_location(value: Any) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if not isinstance(value, dict):
        return ""

    pieces = []
    name = clean_text(value.get("name"))
    if name:
        pieces.append(name)

    address = value.get("address")
    if isinstance(address, str):
        pieces.append(clean_text(address))
    elif isinstance(address, dict):
        address_parts = [
            clean_text(address.get("streetAddress")),
            clean_text(address.get("addressLocality")),
            clean_text(address.get("addressRegion")),
            clean_text(address.get("postalCode")),
        ]
        addr = ", ".join(x for x in address_parts if x)
        if addr:
            pieces.append(addr)

    return " — ".join(dict.fromkeys(x for x in pieces if x))


def _iso_date_from_value(value: str | None) -> str:
    if not value:
        return ""
    value = clean_text(value)
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", value)
    return match.group(1) if match else ""


def _visible_date_to_iso(text: str) -> str:
    """
    Convert visible Wat2Do date text such as "Saturday, Sep 19" to YYYY-MM-DD.

    Wat2Do's landing page contains upcoming events. If the visible date omits a
    year, select the nearest plausible upcoming year.
    """
    match = DATE_RE.search(text)
    if not match:
        return ""

    month_token = match.group("month").rstrip(".")
    day = int(match.group("day"))
    explicit_year = match.group("year")

    month_lookup = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    month = month_lookup.get(month_token.lower())
    if not month:
        return ""

    if explicit_year:
        year = int(explicit_year)
    else:
        today = datetime.now().date()
        year = today.year
        try:
            candidate = datetime(year, month, day).date()
        except ValueError:
            return ""
        # If an "upcoming" date would otherwise be far in the past, it is most
        # likely referring to the next calendar year.
        if (today - candidate).days > 45:
            year += 1

    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _meta_content(soup: BeautifulSoup, *keys: str) -> str:
    for key in keys:
        node = soup.find("meta", attrs={"property": key})
        if node and node.get("content"):
            return clean_text(node["content"])
        node = soup.find("meta", attrs={"name": key})
        if node and node.get("content"):
            return clean_text(node["content"])
    return ""


def _source_link(soup: BeautifulSoup, page_url: str) -> str:
    # Prefer an explicit Wat2Do "Source:" link.
    for anchor in soup.find_all("a", href=True):
        label = text_of(anchor).lower()
        href = canonical_http_url(page_url, anchor.get("href"))
        if not href:
            continue
        if label.startswith("source:"):
            return href

    # Wat2Do frequently links the original Instagram/Facebook post without
    # including "Source:" in a clean anchor label.
    for anchor in soup.find_all("a", href=True):
        href = canonical_http_url(page_url, anchor.get("href"))
        host = (urlsplit(href).hostname or "").lower()
        if host in {
            "instagram.com",
            "www.instagram.com",
            "facebook.com",
            "www.facebook.com",
        }:
            return href
    return ""


def _extract_about_text(soup: BeautifulSoup) -> str:
    heading = None
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        if text_of(tag).lower() == "about event":
            heading = tag
            break

    if not heading:
        return ""

    parts = []
    for node in heading.find_all_next():
        if node is heading:
            continue
        if getattr(node, "name", None) and re.fullmatch(r"h[1-6]", node.name or ""):
            break
        # Avoid repeating every nested tag; p/div/li are enough.
        if getattr(node, "name", None) not in {"p", "div", "li"}:
            continue
        text = text_of(node)
        if not text:
            continue
        lower = text.lower()
        if lower.startswith("source:") or lower == "hosted by":
            break
        if text not in parts:
            parts.append(text)
        if len(" ".join(parts)) > 2500:
            break

    # Nested divs can cause near-duplicate text. Prefer the shortest useful
    # collection by removing strings fully contained in a longer previous one.
    cleaned = []
    for item in parts:
        if any(item == old or item in old for old in cleaned):
            continue
        cleaned.append(item)
    return clean_text(" ".join(cleaned))[:3000]


def _extract_host(soup: BeautifulSoup, title: str) -> str:
    # First try "Hosted by" section.
    headings = list(soup.find_all(re.compile(r"^h[1-6]$")))
    for heading in headings:
        if text_of(heading).lower() == "hosted by":
            for node in heading.find_all_next(["a", "div", "p", "span"], limit=8):
                value = text_of(node)
                if (
                    value
                    and value.lower() not in BAD_LOCATION_TEXT
                    and value != title
                    and len(value) <= 160
                ):
                    return value

    # Fallback: in Wat2Do detail pages the organizer is usually rendered just
    # before the H1 title.
    h1 = soup.find("h1")
    if h1:
        previous = h1.find_previous(string=True)
        while previous:
            value = clean_text(previous)
            if value and value != title and value.lower() not in {"all events", "share", "report"}:
                if len(value) <= 160:
                    return value
            previous = previous.find_previous(string=True)
    return ""


def _extract_visible_metadata(
    soup: BeautifulSoup,
    title: str,
) -> tuple[str, str, str]:
    """Return (iso_date, time_text, location) from visible detail-page text."""
    strings = [clean_text(s) for s in soup.stripped_strings if clean_text(s)]

    title_index = -1
    for i, value in enumerate(strings):
        if value == title:
            title_index = i
            break

    if title_index < 0:
        window = strings[:50]
    else:
        # Metadata lives between the title and "About Event".
        end = min(len(strings), title_index + 20)
        for i in range(title_index + 1, min(len(strings), title_index + 30)):
            if strings[i].lower() == "about event":
                end = i
                break
        window = strings[title_index + 1 : end]

    iso_date = ""
    time_text = ""
    location = ""

    date_position = None
    time_position = None

    for i, value in enumerate(window):
        if not iso_date:
            iso_date = _visible_date_to_iso(value)
            if iso_date:
                date_position = i
        if not time_text:
            match = TIME_RE.search(value)
            if match:
                time_text = clean_text(match.group(0))
                time_position = i

    # Usually the location follows the time.
    if time_position is not None:
        candidates = window[time_position + 1 : time_position + 5]
    elif date_position is not None:
        candidates = window[date_position + 1 : date_position + 6]
    else:
        candidates = []

    for value in candidates:
        lower = value.lower()
        if lower in BAD_LOCATION_TEXT:
            continue
        if "@" in value and "." in value:
            continue
        if TIME_RE.search(value) or DATE_RE.search(value):
            continue
        if re.fullmatch(r"\$?\d+(?:\.\d{2})?", value):
            continue
        if len(value) > 180:
            continue
        location = value
        break

    return iso_date, time_text, location


def parse_event_detail(html_text: str, page_url: str) -> dict | None:
    soup = BeautifulSoup(html_text, "html.parser")
    json_event = _jsonld_event(soup)

    title = ""
    about = ""
    image = ""
    host = ""
    location = ""
    iso_date = ""
    time_text = ""
    original_source = ""

    if json_event:
        title = clean_text(json_event.get("name"))
        about = clean_text(json_event.get("description"))
        iso_date = _iso_date_from_value(clean_text(json_event.get("startDate")))
        location = _jsonld_location(json_event.get("location"))

        raw_image = json_event.get("image")
        if isinstance(raw_image, list) and raw_image:
            raw_image = raw_image[0]
        if isinstance(raw_image, dict):
            raw_image = raw_image.get("url")
        image = canonical_http_url(page_url, clean_text(raw_image))

        organizer = json_event.get("organizer")
        if isinstance(organizer, dict):
            host = clean_text(organizer.get("name"))
        elif isinstance(organizer, str):
            host = clean_text(organizer)

    if not title:
        title = text_of(soup.find("h1"))
    if not title:
        og_title = _meta_content(soup, "og:title", "twitter:title")
        title = re.sub(r"\s+at University of Waterloo\s*\|\s*Wat2Do.*$", "", og_title, flags=re.I)
        title = clean_text(title)

    if not title:
        LOG.warning("Skipping Wat2Do page with no event title: %s", page_url)
        return None

    visible_date, visible_time, visible_location = _extract_visible_metadata(soup, title)
    iso_date = iso_date or visible_date
    time_text = visible_time

    if not about:
        about = _extract_about_text(soup)
    if not host:
        host = _extract_host(soup, title)
    if not location:
        location = visible_location
    if not image:
        image = canonical_http_url(
            page_url,
            _meta_content(soup, "og:image", "twitter:image"),
        )
    original_source = _source_link(soup, page_url)

    parts = ["Source: Wat2Do — University of Waterloo"]
    if iso_date:
        parts.append("Date: " + iso_date)
    if time_text:
        parts.append("Time: " + time_text)
    if location:
        parts.append("Location: " + location)
    if host:
        parts.append("Hosted by: " + host)
    if original_source:
        parts.append("Original source: " + original_source)
    if about:
        parts.append(about)

    return {
        "text": title,
        "description": "\n\n".join(parts),
        "image": image,
        # Keep Wat2Do's stable event page as the row identity. The original
        # Instagram/Facebook URL is preserved in description when available.
        "link_to_external": canonical_http_url(page_url, page_url),
        "category": classify_event(title, about, host),
    }


def extract_wat2do_events(
    max_events: int = 100,
    allow_browser_fallback: bool | None = None,
) -> tuple[list[dict], bool]:
    """
    Extract upcoming Waterloo events from Wat2Do.

    `ok` is False when one or more detail pages fail, but successfully parsed
    events are still returned.
    """
    if max_events < 1:
        return [], False

    if allow_browser_fallback is None:
        allow_browser_fallback = _truthy_env("WAT2DO_BROWSER_FALLBACK", False)

    try:
        delay = float(os.getenv("WAT2DO_DELAY", "0.35"))
    except ValueError:
        delay = 0.35

    fetcher = Wat2DoFetcher(delay=delay)
    healthy = True
    rows: list[dict] = []

    try:
        event_urls, working_home, browser_used = discover_event_urls(
            fetcher,
            allow_browser_fallback=allow_browser_fallback,
        )
        LOG.info(
            "Wat2Do home: %s; discovered %s event URL(s)%s",
            working_home,
            len(event_urls),
            " using browser rendering" if browser_used else "",
        )

        event_urls = event_urls[:max_events]
        for index, event_url in enumerate(event_urls, start=1):
            try:
                html_text, final_url = fetcher.get_html(event_url)
                row = parse_event_detail(html_text, final_url)
                if row:
                    rows.append(row)
                else:
                    healthy = False
            except Exception as exc:
                healthy = False
                LOG.warning(
                    "Wat2Do event %s/%s failed: %s (%s)",
                    index,
                    len(event_urls),
                    event_url,
                    exc,
                )
    except Exception as exc:
        LOG.error("Wat2Do extraction failed: %s", exc)
        return [], False
    finally:
        fetcher.close()

    # Exact URL de-duplication.
    unique = {}
    for row in rows:
        link = row.get("link_to_external", "")
        if link:
            unique[link] = row

    return list(unique.values()), healthy and bool(unique)


def extract_social_events(urls=None):
    """
    Drop-in replacement for the old Instagram/Facebook adapter.

    The input social URLs are intentionally ignored: Wat2Do already aggregates
    Waterloo events and often records the original social post on each event
    detail page.
    """
    del urls

    raw_limit = os.getenv("WAT2DO_MAX_EVENTS", "100").strip()
    try:
        max_events = max(1, int(raw_limit))
    except ValueError:
        LOG.warning("Invalid WAT2DO_MAX_EVENTS=%r; using 100", raw_limit)
        max_events = 100

    return extract_wat2do_events(max_events=max_events)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract University of Waterloo events from Wat2Do.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print extracted event rows as JSON. No database writes are performed.",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=30,
        help="Maximum event detail pages to read (default: 30).",
    )
    parser.add_argument(
        "--browser-fallback",
        action="store_true",
        help="Use Playwright only if normal HTML exposes no event links.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    rows, ok = extract_wat2do_events(
        max_events=args.max_events,
        allow_browser_fallback=args.browser_fallback,
    )

    if args.dry_run or rows:
        print(json.dumps(rows, ensure_ascii=False, indent=2))

    LOG.info("Wat2Do result: %s row(s); %s", len(rows), "OK" if ok else "PARTIAL/FAILED")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
