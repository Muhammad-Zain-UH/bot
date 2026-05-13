"""Economic calendar and news handler.

Sources (all free, no paid API required):
  1. Forex Factory calendar  — most accurate high-impact event schedule
  2. Investing.com calendar  — backup
  3. Recurring schedule      — last-resort fallback for known events

The FMP endpoints are kept for compatibility but skipped gracefully when they
return 402/403.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

import config
from utils import log_debug


# ---------------------------------------------------------------------------
# Gold Relevance Filter
# ---------------------------------------------------------------------------

GOLD_RELEVANT_KEYWORDS = [
    # Gold direct
    "gold", "xauusd", "bullion", "precious metal",
    "gold price", "gold rally", "gold drop", "gold falls",
    "gold rises", "gold hits", "gold surges", "gold slumps",

    # Macro drivers of gold
    "federal reserve", "fed rate", "interest rate",
    "rate cut", "rate hike", "rate decision", "fomc",
    "jerome powell", "powell",
    "inflation", "cpi", "pce", "core inflation",
    "dollar index", "dxy", "us dollar", "dollar falls",
    "dollar rises", "dollar strength", "dollar weakness",

    # Safe haven / risk sentiment
    "safe haven", "risk off", "risk-off", "risk aversion",
    "geopolit", "war", "conflict", "sanctions", "ukraine",
    "russia", "middle east", "iran", "israel", "nato",
    "recession", "economic slowdown", "gdp",
    "treasury", "bond yield", "10-year yield",
    "debt ceiling", "banking crisis", "bank collapse",

    # Silver and commodities (correlated)
    "silver", "xagusd", "commodity", "commodities",
    "oil price", "crude oil",

    # Central banks
    "central bank", "ecb", "bank of england", "boe",
    "pboc", "bank of japan", "boj", "gold reserves",
    "gold buying", "central bank gold"
]


def is_gold_relevant(headline_text: str) -> bool:
    """
    Returns True if headline is relevant to gold trading.
    Checks title AND any summary/description text.
    Case insensitive.
    """
    text_lower = headline_text.lower()
    return any(kw in text_lower for kw in GOLD_RELEVANT_KEYWORDS)


# ---------------------------------------------------------------------------
# Retry helper with exponential backoff
# ---------------------------------------------------------------------------

def _retry_request(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = 12,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
) -> requests.Response | None:
    """Fetch URL with exponential backoff retry logic.
    
    Returns Response object on success, None on all failures.
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
            if response.ok or response.status_code in {403, 404, 429}:
                return response
            # Retry on 5xx errors
            if 500 <= response.status_code < 600:
                if attempt < max_retries - 1:
                    wait_time = backoff_factor ** attempt
                    log_debug(f"HTTP {response.status_code} — retry in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                log_debug(f"Timeout — retry in {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
        except requests.exceptions.ConnectionError:
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                log_debug(f"Connection error — retry in {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
        except Exception as exc:
            log_debug(f"Request failed: {exc}")
            continue
        
        return None
    
    return None

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_CACHE: dict[str, Any] = {
    "events":    [],
    "fetched_at": None,
}
_CACHE_TTL_MINUTES = 10


# ---------------------------------------------------------------------------
# Recurring high-impact schedule (weekday 0=Mon, hour UTC, min UTC)
# ---------------------------------------------------------------------------
_RECURRING = [
    (4, 12, 30, "Non-Farm Payrolls",          "USD"),
    (1, 12, 30, "CPI m/m",                    "USD"),
    (2, 18,  0, "FOMC Rate Decision",          "USD"),
    (3, 12, 15, "ECB Rate Decision",           "EUR"),
    (2, 12, 30, "GDP q/q",                     "USD"),
    (3, 12, 30, "PPI m/m",                     "USD"),
    (0, 14,  0, "ISM Manufacturing PMI",       "USD"),
    (4,  8, 30, "UK GDP",                      "GBP"),
    (2, 14,  0, "FOMC Meeting Minutes",        "USD"),
    (4, 13, 30, "Core PCE Price Index",        "USD"),
]

# Weekly schedule fallback when APIs fail
WEEKLY_HIGH_IMPACT_SCHEDULE = {
    "Monday":    ["EU/US PMI releases (check manually)"],
    "Tuesday":   ["CB Consumer Confidence (US, monthly)"],
    "Wednesday": ["US ADP Employment", "EIA Crude Oil Stocks",
                  "FOMC Minutes (biweekly — check dates)"],
    "Thursday":  ["US Initial Jobless Claims",
                  "ECB Rate Decision (monthly — check dates)"],
    "Friday":    ["US Non-Farm Payrolls (first Friday monthly)",
                  "US CPI (monthly — check dates)",
                  "University of Michigan Sentiment"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_cache_fresh() -> bool:
    ts = _CACHE.get("fetched_at")
    if ts is None:
        return False
    return (_now() - ts).total_seconds() < _CACHE_TTL_MINUTES * 60


def _make_event(
    name: str,
    event_time: datetime,
    impact: str,
    currency: str,
    source: str,
    estimated: bool = False,
) -> dict[str, Any]:
    return {
        "event_name": name,
        "time":       event_time,
        "impact":     impact,
        "currency":   currency,
        "source":     source,
        "estimated":  estimated,
        "minutes_away": round((event_time - _now()).total_seconds() / 60, 1),
    }


def _is_estimated_event(event: dict[str, Any]) -> bool:
    """Return True when the event comes from a non-live fallback schedule."""
    return bool(event.get("estimated", False))


# ---------------------------------------------------------------------------
# Forex Factory scraper — best free economic calendar
# ---------------------------------------------------------------------------

def _fetch_forex_factory() -> list[dict[str, Any]]:
    """Scrape Forex Factory calendar for today's high-impact USD events."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.forexfactory.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        
        # Try main URL first with retry
        resp = _retry_request(
            "https://www.forexfactory.com/calendar.php",
            headers=headers,
            timeout=12,
            max_retries=3,
        )
        
        # Fallback to alternative URL if first fails
        if not resp or resp.status_code == 403:
            resp = _retry_request(
                "https://www.forexfactory.com/calendar/",
                headers=headers,
                timeout=12,
                max_retries=3,
            )
        
        if not resp or not resp.ok:
            log_debug(f"Forex Factory HTTP {resp.status_code if resp else 'failed'}")
            return []

        html = resp.text
        events: list[dict[str, Any]] = []
        today = _now().date()

        # Extract high-impact events using regex on the page source
        # FF marks high-impact with "icon--ff-impact-red" class
        row_pattern = re.compile(
            r'class="calendar__row[^"]*"[^>]*data-event-id="(\d+)"(.*?)</tr>',
            re.DOTALL,
        )
        impact_pattern = re.compile(r'icon--ff-impact-(red|orange|yellow|gray)')
        title_pattern  = re.compile(r'class="calendar__event-title"[^>]*>([^<]+)<')
        time_pattern   = re.compile(r'class="calendar__time"[^>]*>([^<]+)<')
        currency_pattern = re.compile(r'class="calendar__currency"[^>]*>([^<]+)<')

        for match in row_pattern.finditer(html):
            row_html = match.group(2)

            impact_m = impact_pattern.search(row_html)
            if not impact_m or impact_m.group(1) not in ("red", "orange"):
                continue

            impact_level = "High" if impact_m.group(1) == "red" else "Medium"
            title_m    = title_pattern.search(row_html)
            time_m     = time_pattern.search(row_html)
            currency_m = currency_pattern.search(row_html)

            event_name = title_m.group(1).strip() if title_m else "Unknown"
            currency   = currency_m.group(1).strip() if currency_m else "USD"
            time_str   = time_m.group(1).strip() if time_m else ""

            # Parse time like "8:30am"
            event_time = None
            if time_str and time_str.lower() not in ("all day", "tentative", ""):
                try:
                    t = datetime.strptime(time_str.strip().lower(), "%I:%M%p")
                    event_time = datetime(
                        today.year, today.month, today.day,
                        t.hour, t.minute, tzinfo=timezone.utc
                    )
                    # FF times are US Eastern — convert to UTC (ET = UTC-4 or UTC-5)
                    # Simple approximation: add 4 hours (EDT)
                    event_time = event_time + timedelta(hours=4)
                except Exception:
                    pass

            if event_time:
                events.append(_make_event(
                    event_name, event_time, impact_level, currency, "ForexFactory"
                ))

        log_debug(f"Forex Factory: {len(events)} events scraped.")
        return events

    except requests.exceptions.Timeout:
        log_debug("Forex Factory scrape timeout — skipping.")
        return []
    except Exception as exc:
        log_debug(f"Forex Factory scrape failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Investing.com backup
# ---------------------------------------------------------------------------

def _fetch_investing_com() -> list[dict[str, Any]]:
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.investing.com/economic-calendar/",
        }
        today = _now().strftime("%Y-%m-%d")
        
        # Retry with exponential backoff for Investing.com
        resp = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
                    headers=headers,
                    data={
                        "country[]": ["5"],
                        "importance[]": ["3"],
                        "dateFrom": today,
                        "dateTo": today,
                        "timeZone": "0",
                        "timeFilter": "timeRemain",
                        "currentTab": "custom",
                        "submitFilters": "1",
                        "limit_from": "0",
                    },
                    timeout=10,
                )
                if resp.ok or resp.status_code in {403, 404}:
                    break
                elif 500 <= resp.status_code < 600 and attempt < 2:
                    wait_time = 2.0 ** attempt
                    log_debug(f"Investing.com HTTP {resp.status_code} — retry in {wait_time:.1f}s...")
                    time.sleep(wait_time)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < 2:
                    wait_time = 2.0 ** attempt
                    log_debug(f"Investing.com connection error — retry in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                else:
                    return []
        
        if not resp or not resp.ok:
            return []

        html = resp.json().get("data", "")
        events: list[dict[str, Any]] = []
        time_pat   = re.compile(r'data-event-datetime="([^"]+)"')
        name_pat   = re.compile(r'class="event"[^>]*>\s*<a[^>]*>([^<]+)</a>')

        times = time_pat.findall(html)
        names = name_pat.findall(html)

        for i, name in enumerate(names):
            raw_time = times[i] if i < len(times) else ""
            try:
                et = datetime.strptime(raw_time, "%Y/%m/%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                events.append(_make_event(name.strip(), et, "High", "USD", "Investing.com"))
            except Exception:
                continue

        log_debug(f"Investing.com: {len(events)} events.")
        return events

    except Exception as exc:
        log_debug(f"Investing.com failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Recurring schedule fallback
# ---------------------------------------------------------------------------

def _recurring_events(lookahead_hours: int = 24) -> list[dict[str, Any]]:
    now   = _now()
    cutoff = now + timedelta(hours=lookahead_hours)
    events: list[dict[str, Any]] = []

    for weekday, hour, minute, name, currency in _RECURRING:
        # Check today and tomorrow
        for day_offset in range(2):
            candidate_date = (now + timedelta(days=day_offset)).date()
            if candidate_date.weekday() != weekday:
                continue
            candidate_time = datetime(
                candidate_date.year, candidate_date.month, candidate_date.day,
                hour, minute, tzinfo=timezone.utc,
            )
            if now <= candidate_time <= cutoff:
                events.append(
                    _make_event(
                        name,
                        candidate_time,
                        "High",
                        currency,
                        "RecurringSchedule",
                        estimated=True,
                    )
                )

    log_debug(f"Recurring schedule: {len(events)} events in next {lookahead_hours}h.")
    return events


def _weekly_schedule_fallback() -> list[dict[str, Any]]:
    """Return today's recurring events from the weekly schedule as fallback."""
    now = _now()
    weekday_name = now.strftime("%A")
    
    events: list[dict[str, Any]] = []
    if weekday_name in WEEKLY_HIGH_IMPACT_SCHEDULE:
        for event_name in WEEKLY_HIGH_IMPACT_SCHEDULE[weekday_name]:
            # Use midday UTC as estimated time
            event_time = now.replace(hour=12, minute=0, second=0, microsecond=0)
            events.append(
                _make_event(
                    f"[EST] {event_name}",
                    event_time,
                    "High",
                    "USD",
                    "WeeklySchedule",
                    estimated=True,
                )
            )
    
    log_debug(f"Weekly schedule fallback: {len(events)} estimated events for {weekday_name}")
    return events


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def fetch_economic_calendar(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Fetch high-impact economic events.
    
    Priority:
    1. Forex Factory (best live data)
    2. Investing.com (backup)
    3. Recurring schedule (24h lookahead)
    4. Weekly schedule fallback (estimated — verify manually)
    """
    if not force_refresh and _is_cache_fresh():
        log_debug("Using cached economic calendar.")
        return list(_CACHE["events"])

    # Attempt 1: Forex Factory
    events = _fetch_forex_factory()

    # Attempt 2: Investing.com
    if not events:
        log_debug("Forex Factory failed — trying Investing.com.")
        events = _fetch_investing_com()

    # Attempt 3: Recurring schedule (24h lookahead)
    if not events:
        log_debug("All calendar APIs failed — using recurring schedule.")
        events = _recurring_events()
    
    # Attempt 4: Weekly schedule fallback
    if not events:
        log_debug("Calendar APIs down — using weekly schedule fallback (verify manually)")
        events = _weekly_schedule_fallback()

    if events and all(_is_estimated_event(event) for event in events):
        log_debug("Economic calendar is running on estimated fallback events only.")

    events.sort(key=lambda e: e.get("time") or datetime.max.replace(tzinfo=timezone.utc))
    _CACHE["events"] = events
    _CACHE["fetched_at"] = _now()
    log_debug(f"Economic calendar ready: {len(events)} events.")
    return list(events)


def check_high_impact_news(within_minutes: int = 30) -> tuple[bool, dict[str, Any] | None]:
    """Return (True, event) if a high-impact event is within ±within_minutes."""
    try:
        events = fetch_economic_calendar()
        now = _now()
        for event in events:
            if _is_estimated_event(event):
                continue
            et = event.get("time")
            if et is None:
                continue
            diff = abs((et - now).total_seconds() / 60)
            if diff <= within_minutes and "high" in str(event.get("impact", "")).lower():
                log_debug(
                    f"High-impact event nearby: {event['event_name']} "
                    f"in {event.get('minutes_away', '?')} min"
                )
                return True, event
        return False, None
    except Exception as exc:
        log_debug(f"High-impact check error: {exc}")
        return False, None


# ---------------------------------------------------------------------------
# Event Classification — Fed vs. Ignored Events
# ---------------------------------------------------------------------------

FED_EVENT_KEYWORDS = [
    "fomc", "rate decision", "rate cut", "rate hike",
    "fed", "federal reserve", "jerome powell", "powell",
    "fed minutes", "fed minutes", "federal reserve minutes",
]

IGNORE_EVENT_KEYWORDS = [
    "cpi", "non-farm payroll", "nfp", "jobs",
    "gdp", "pce", "inflation", "adp", "unemployment",
    "consumer price", "producer price", "ppi",
]


def classify_event(event_name: str) -> str:
    """Classify an economic event.
    
    Args:
        event_name: Name of the economic event (e.g., "FOMC Rate Decision", "CPI m/m")
    
    Returns:
        "FED" → Fed-related event (FOMC, rate decision, Powell, Fed minutes)
        "IGNORE" → Event to ignore completely (CPI, NFP, GDP, PCE, ADP, inflation, etc.)
        "OTHER" → Other high-impact events (ECB, BOE, etc.)
    """
    name_lower = event_name.lower()
    
    # Check Fed keywords first
    for kw in FED_EVENT_KEYWORDS:
        if kw in name_lower:
            return "FED"
    
    # Check ignore keywords
    for kw in IGNORE_EVENT_KEYWORDS:
        if kw in name_lower:
            return "IGNORE"
    
    # Everything else is treated as other events
    return "OTHER"


def get_event_impact_zone(within_minutes: int = 15, post_delay_minutes: int = 10) -> tuple[str, float]:
    """TIER 1: Advanced event detection — PRE-EVENT GAP, LIVE EVENT, POST-EVENT VOLATILITY.
    
    Only applies penalties for FED events. IGNORE events (CPI, NFP, GDP, etc.) are skipped.
    
    Returns:
        (zone_label, confidence_adjustment_pct)
        
    Zone labels:
        "clean" → No FED event within 30 min, normal trading
        "pre_event_gap" → FED event within 10 min before, confidence -30%
        "live_event" → FED event within ±2 min, confidence -50% (AVOID entry)
        "post_event_vol" → FED event just happened, vol spike 10 min, confidence -20%
    """
    try:
        events = fetch_economic_calendar()
        now = _now()
        
        nearest_event = None
        nearest_diff = float('inf')
        
        for event in events:
            if _is_estimated_event(event):
                continue
            
            # SKIP ignored events completely — no penalties
            event_classification = classify_event(event.get("event_name", ""))
            if event_classification == "IGNORE":
                continue
            
            et = event.get("time")
            if et is None:
                continue
            if "high" not in str(event.get("impact", "")).lower():
                continue
                
            diff = (et - now).total_seconds() / 60  # Can be negative (past)
            abs_diff = abs(diff)
            
            if abs_diff < nearest_diff:
                nearest_diff = abs_diff
                nearest_event = (event, diff)
        
        if nearest_event is None:
            return "clean", 0.0
        
        event, minutes_away = nearest_event
        event_class = classify_event(event.get("event_name", ""))
        
        # LIVE EVENT: within ±2 minutes (only apply to FED events)
        if abs(minutes_away) <= 2:
            log_debug(
                f"🔴 LIVE_EVENT ({event_class}): {event['event_name']} happening NOW. "
                f"Extreme volatility risk. Avoid new entries."
            )
            return "live_event", -50.0
        
        # PRE-EVENT GAP: within -15 to -2 minutes (only apply to FED events)
        if -within_minutes <= minutes_away < -2:
            log_debug(
                f"⚠️ PRE_EVENT_GAP ({event_class}): {event['event_name']} in {abs(minutes_away):.0f} min. "
                f"Liquidity hole starting. Reduce confidence 30%."
            )
            return "pre_event_gap", -30.0
        
        # POST-EVENT VOLATILITY: within 0 to +10 minutes (only apply to FED events)
        if 0 < minutes_away <= post_delay_minutes:
            log_debug(
                f"⚠️ POST_EVENT_VOL ({event_class}): {event['event_name']} happened {minutes_away:.0f} min ago. "
                f"Vol spike ongoing. Be cautious."
            )
            return "post_event_vol", -20.0
        
        return "clean", 0.0
        
    except Exception as exc:
        log_debug(f"Event impact zone check failed: {exc}")
        return "clean", 0.0


def format_calendar_for_prompt(events: list[dict[str, Any]], limit: int = 5) -> str:
    """Format calendar events as a concise string for AI prompt injection."""
    if not events:
        return "No high-impact events on calendar today."
    shown = events[:limit]
    lines = []
    if shown and all(_is_estimated_event(e) for e in shown):
        lines.append(
            "Estimated recurring fallback only - live economic calendar data is unavailable."
        )
    elif any(_is_estimated_event(e) for e in shown):
        lines.append(
            "Some calendar items below are estimated fallbacks, not verified live releases."
        )
    for e in shown:
        et   = e.get("time")
        mins = e.get("minutes_away")
        time_str = (
            f"{abs(mins):.0f} min {'ago' if mins < 0 else 'away'}"
            if mins is not None else "unknown time"
        )
        label = "[Estimated] " if _is_estimated_event(e) else ""
        if label:
            lines.append(
                f"* {label}{e['event_name']} [{e['currency']} | {e['impact']}] - {time_str}"
            )
            continue
        lines.append(
            f"• {e['event_name']} [{e['currency']} | {e['impact']}] — {time_str}"
        )
    return "\n".join(lines)


def analyze_post_event_sentiment(headlines: list[str]) -> tuple[str, float]:
    """Analyze news sentiment AFTER a Fed event to determine bullish/bearish outcome.
    
    Used to adjust confidence after Fed events have occurred. Examines headlines
    for keywords indicating whether the Fed action was hawkish or dovish, and
    how that affects gold.
    
    Args:
        headlines: List of recent news headlines/strings
    
    Returns:
        (sentiment_direction, confidence_adjustment_pct)
        
    Direction:
        "bullish" → Gold-positive outcome (rate cut, dovish, dollar falls, gold rallies)
        "bearish" → Gold-negative outcome (rate hike, hawkish, dollar jumps, gold tumbles)
        "neutral" → Unclear or mixed signals
    
    Confidence adjustment:
        -20 to +20 percentage points
    """
    if not headlines:
        log_debug("[POST-EVENT] No headlines to analyze — neutral sentiment")
        return "neutral", 0.0
    
    combined_text = " ".join(headlines).lower()
    
    # Bullish for gold indicators
    bullish_keywords = [
        "rate cut", "dovish", "lower rates", "cut rates",
        "dollar falls", "dollar drops", "dollar weakness",
        "gold rally", "gold rallies", "gold surge", "gold surges",
        "gold up", "rally",
        "risk off", "risk aversion",
        "recession", "slowdown", "concerns",
    ]
    
    # Bearish for gold indicators  
    bearish_keywords = [
        "rate hike", "hawkish", "higher rates", "hike rates",
        "dollar jump", "dollar jumps", "dollar strength", "dollar rally",
        "gold drop", "gold falls", "gold decline", "gold down",
        "sell off", "gold pressure",
        "strong economy", "growth", "inflation surprise",
    ]
    
    bullish_count = sum(1 for kw in bullish_keywords if kw in combined_text)
    bearish_count = sum(1 for kw in bearish_keywords if kw in combined_text)
    
    log_debug(
        f"[POST-EVENT] Sentiment analysis: bullish={bullish_count}, bearish={bearish_count}"
    )
    
    if bullish_count > bearish_count:
        # Bullish outcome detected
        adjustment = +15.0  # Boost confidence by 15% if bullish
        log_debug(
            f"[POST-EVENT] 📈 Bullish outcome detected: rate cut / dovish / dollar weakness / gold rally. "
            f"Confidence +15%"
        )
        return "bullish", adjustment
    elif bearish_count > bullish_count:
        # Bearish outcome detected
        adjustment = -15.0  # Reduce confidence by 15% if bearish
        log_debug(
            f"[POST-EVENT] 📉 Bearish outcome detected: rate hike / hawkish / dollar strength / gold pressure. "
            f"Confidence -15%"
        )
        return "bearish", adjustment
    else:
        # Mixed or neutral
        log_debug(f"[POST-EVENT] 〰️ Mixed/neutral signals detected")
        return "neutral", 0.0
