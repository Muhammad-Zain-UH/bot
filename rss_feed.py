"""Real-time RSS news fetcher — zero API cost, updates within minutes.

Pulls gold/macro headlines from multiple free feeds simultaneously.
These feeds update within 2–5 minutes of breaking news.

Install dependency: pip install feedparser
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from utils import log_debug

try:
    import feedparser
    _FEEDPARSER_OK = True
except ImportError:
    _FEEDPARSER_OK = False
    log_debug("feedparser not installed — run: pip install feedparser")

# ---------------------------------------------------------------------------
# Feed sources — ordered by relevance and stability
# Tested 2026-04-06: Core 3 feeds consistently working, 14-17 headlines per run
# ---------------------------------------------------------------------------
RSS_FEEDS = [
    {"url": "https://www.forexlive.com/feed/news",
     "name": "ForexLive",         "weight": 1.5},
    {"url": "https://www.fxstreet.com/rss/news",
     "name": "FXStreet",          "weight": 1.3},
    {"url": "https://www.investing.com/rss/news_25.rss",
     "name": "Investing Gold",    "weight": 1.4},
    {"url": "https://feeds.marketwatch.com/marketwatch/topstories/",
     "name": "MarketWatch",       "weight": 1.0},
    {"url": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
     "name": "MarketWatch DJ",    "weight": 1.1},
    {"url": "https://www.mining.com/feed/",
     "name": "Mining.com",        "weight": 1.2},
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml",
     "name": "Federal Reserve",   "weight": 1.4},
    {"url": "https://feeds.feedburner.com/zerohedge/feed",
     "name": "ZeroHedge",         "weight": 1.1},
    {"url": "https://goldprice.org/apps/gold_news_feed.xml",
     "name": "GoldPrice",         "weight": 1.3},
]

_FEED_CACHE:   dict[str, dict[str, Any]] = {}
_CACHE_TTL     = 300     # seconds — refresh every 5 min
_MAX_AGE_HOURS = 6       # ignore articles older than 6 hours
_MAX_PER_FEED  = 8       # articles per feed
_VALIDATED_FEEDS: list[dict[str, Any]] | None = None

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_feed_time(entry: Any) -> datetime | None:
    """Extract publication time from an RSS entry."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        raw = getattr(entry, field, None)
        if raw:
            try:
                ts = time.mktime(raw)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass
    return None


def _entry_to_headline(entry: Any, feed_name: str) -> dict[str, Any] | None:
    """Convert a feedparser entry into a clean headline dict."""
    title = getattr(entry, "title", "") or ""
    title = title.strip()
    if not title or len(title) < 10:
        return None

    summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    # Strip HTML tags simply
    import re
    summary = re.sub(r"<[^>]+>", " ", summary).strip()
    summary = " ".join(summary.split())[:200]

    pub_time = _parse_feed_time(entry)
    age_hours = None
    if pub_time:
        age_hours = (datetime.now(timezone.utc) - pub_time).total_seconds() / 3600
        if age_hours > _MAX_AGE_HOURS:
            return None

    return {
        "headline": title,
        "summary":  summary,
        "source":   feed_name,
        "time":     pub_time,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "full_text": f"{title}. {summary}" if summary else title,
    }


def _download_feed(url: str) -> Any:
    """Fetch and parse a feed URL with a browser-like header set."""
    resp = requests.get(url, headers=_REQUEST_HEADERS, timeout=10)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def validate_rss_feeds(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Validate feeds on first run and keep only sources with a recent article."""
    global _VALIDATED_FEEDS

    if not _FEEDPARSER_OK:
        log_debug("feedparser unavailable â€” cannot validate RSS feeds.")
        _VALIDATED_FEEDS = []
        return []

    if _VALIDATED_FEEDS is not None and not force_refresh:
        return list(_VALIDATED_FEEDS)

    validated: list[dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc)

    for feed_cfg in RSS_FEEDS:
        name = feed_cfg["name"]
        url = feed_cfg["url"]
        try:
            feed = _download_feed(url)
            recent_found = False
            for entry in feed.entries[:_MAX_PER_FEED]:
                pub_time = _parse_feed_time(entry)
                if pub_time and (now_utc - pub_time) <= timedelta(hours=24):
                    recent_found = True
                    break
            if recent_found:
                validated.append(feed_cfg)
                log_debug(f"RSS validation OK: {name} - recent article found.")
            else:
                log_debug(f"RSS validation skipped: {name} - no article in last 24h.")
        except Exception as exc:
            log_debug(f"RSS validation failed for {name}: {exc}")

    _VALIDATED_FEEDS = validated
    log_debug(f"RSS validation complete: {len(validated)}/{len(RSS_FEEDS)} feeds active.")
    return list(_VALIDATED_FEEDS)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def fetch_rss_headlines(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Fetch and deduplicate headlines from all RSS feeds.

    Returns list of dicts sorted by recency, each with:
        headline, summary, source, time, age_hours, full_text
    """
    if not _FEEDPARSER_OK:
        log_debug("feedparser unavailable — no RSS headlines.")
        return []

    now = time.time()
    all_items: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    active_feeds = validate_rss_feeds()

    for feed_cfg in active_feeds:
        url  = feed_cfg["url"]
        name = feed_cfg["name"]
        cached = _FEED_CACHE.get(url, {})

        # Use cache if fresh
        if not force_refresh and cached.get("fetched_at", 0) + _CACHE_TTL > now:
            items = cached.get("items", [])
            log_debug(f"RSS cache hit: {name} ({len(items)} items)")
        else:
            try:
                feed = _download_feed(url)
                items = []
                for entry in feed.entries[:_MAX_PER_FEED]:
                    item = _entry_to_headline(entry, name)
                    if item:
                        items.append(item)
                _FEED_CACHE[url] = {"fetched_at": now, "items": items}
                log_debug(f"RSS fetched: {name} → {len(items)} usable articles")
            except Exception as exc:
                log_debug(f"RSS fetch failed for {name}: {exc}")
                items = cached.get("items", [])

        # Deduplicate by normalized title
        for item in items:
            key = item["headline"].lower()[:60]
            if key not in seen_titles:
                seen_titles.add(key)
                all_items.append(item)

    # Sort by recency (None times go last)
    all_items.sort(
        key=lambda x: x["time"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    log_debug(f"RSS total unique headlines: {len(all_items)}")
    return all_items


def get_headline_strings(limit: int = 20) -> list[str]:
    """Return plain headline strings for AI prompt injection.
    
    Filters to only gold-relevant headlines using the filter in news_handler.py.
    """
    from news_handler import is_gold_relevant
    
    items = fetch_rss_headlines()
    
    # Filter to gold-relevant headlines only
    relevant_items = [
        item for item in items
        if is_gold_relevant(item.get("headline", "") + " " + item.get("summary", ""))
    ]
    
    # Log what was filtered
    filtered_count = len(items) - len(relevant_items)
    if filtered_count > 0:
        log_debug(
            f"News filter: {len(items)} total headlines → "
            f"{len(relevant_items)} gold-relevant "
            f"({filtered_count} irrelevant filtered out)"
        )
    
    return [
        f"[{item['source']} | {item['age_hours']}h ago] {item['full_text']}"
        for item in relevant_items[:limit]
    ]
