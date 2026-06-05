#!/usr/bin/env python3
"""
nestcal_core - Qt-free calendar logic for nestcal.

Fetches ICS feeds, expands recurring events, and extracts the bits a reminder
needs: title, start/end, and the meeting link. Deliberately has no Qt
dependency so it can be unit-tested headlessly and reused by both the standalone
tray app and an eventual Nestray integration.
"""

import configparser
import os
import re
import stat
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from math import ceil
from pathlib import Path
from urllib.parse import urlsplit

try:
    import requests
    import icalendar
    import recurring_ical_events
except ImportError as e:
    print(
        f"nestcal: missing dependency: {e.name}\n"
        "  pip install requests icalendar recurring-ical-events",
        file=sys.stderr,
    )
    raise


# --- Constants ---

CONFIG_PATH = Path.home() / ".config" / "nestcal.ini"
HTTP_TIMEOUT = 20
USER_AGENT = "nestcal/0.1"

SETTINGS_DEFAULTS = {
    "poll_interval": "300",   # seconds between network fetches
    "lead_minutes": "2",      # how long before start to fire the reminder
    "window_hours": "24",     # lookahead horizon
    "snooze_minutes": "1",    # snooze duration on the reminder window
    "check_interval": "5",    # seconds between due-checks (firing precision)
}


# --- Logger ---

class Logger:
    """Simple debug logger; prints to stderr only when enabled."""

    def __init__(self, debug: bool = False):
        self.debug = debug

    def log(self, msg: str) -> None:
        if self.debug:
            print(f"nestcal: {msg}", file=sys.stderr)


# --- Config ---

def load_config(logger: Logger) -> configparser.ConfigParser:
    """
    Load config, creating a 0600 commented stub if absent (the ICS URLs are
    bearer secrets). Warns if an existing file is group/other-accessible.
    """
    config = configparser.ConfigParser()
    config.optionxform = str  # preserve calendar-label case

    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH)
        if CONFIG_PATH.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            print(f"nestcal: warning: {CONFIG_PATH} is group/other-accessible; "
                  f"it holds secret URLs. chmod 600 {CONFIG_PATH}", file=sys.stderr)
        return config

    logger.log(f"creating config stub at {CONFIG_PATH}")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(
            "# nestcal config\n"
            "# One entry per calendar under [calendars] as: label = ICS_URL\n"
            "# Use the Google Calendar \"Secret address in iCal format\".\n"
            "# These URLs are secrets.\n\n"
            "[settings]\n"
            + "".join(f"{k} = {v}\n" for k, v in SETTINGS_DEFAULTS.items())
            + "\n[calendars]\n"
            "# personal = https://calendar.google.com/calendar/ical/.../basic.ics\n"
        )
    config.read(CONFIG_PATH)
    return config


def get_setting(config: configparser.ConfigParser, key: str) -> str:
    """Read a [settings] value, falling back to the built-in default."""
    return config.get("settings", key, fallback=SETTINGS_DEFAULTS[key])


# --- Feed model ---

@dataclass
class Feed:
    """A configured ICS feed plus conditional-GET validators."""
    label: str
    url: str
    etag: str | None = None
    last_modified: str | None = None


def get_feeds(config: configparser.ConfigParser, logger: Logger) -> list[Feed]:
    feeds: list[Feed] = []
    if config.has_section("calendars"):
        for label, url in config.items("calendars"):
            url = url.strip()
            if url:
                feeds.append(Feed(label=label, url=url))
    logger.log(f"{len(feeds)} feed(s) configured")
    return feeds


# --- HTTP fetch ---

def fetch_feed(feed: Feed, logger: Logger, conditional: bool = True) -> bytes | None:
    """
    GET the feed; returns the ICS body on 200, None on 304/error (logged).

    With conditional=True, sends validators so polite servers can answer 304
    (good for a change-watcher). The polling path uses conditional=False so it
    always receives the full current calendar — otherwise a 304 would silently
    drop that feed's events from the cycle and its reminders would never fire.
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if conditional and feed.etag:
        headers["If-None-Match"] = feed.etag
    if conditional and feed.last_modified:
        headers["If-Modified-Since"] = feed.last_modified

    try:
        resp = requests.get(feed.url, headers=headers, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        logger.log(f"{feed.label}: fetch error: {e}")
        return None

    if resp.status_code == 304:
        logger.log(f"{feed.label}: 304 not modified")
        return None
    if resp.status_code != 200:
        logger.log(f"{feed.label}: unexpected status {resp.status_code}")
        return None

    feed.etag = resp.headers.get("ETag")
    feed.last_modified = resp.headers.get("Last-Modified")
    return resp.content


# --- Meeting-link extraction ---

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_CONF_HOSTS = (
    "meet.google.com", "zoom.us", "teams.microsoft.com", "teams.live.com",
    "webex.com", "whereby.com", "meet.jit.si", "chime.aws", "bluejeans.com",
    "gotomeeting.com",
)


def _urls(text: str) -> list[str]:
    """All http(s) URLs in text, with trailing punctuation trimmed."""
    return [u.rstrip(".,;:)>\"'") for u in _URL_RE.findall(text or "")]


def _conferencing_url(text: str) -> str | None:
    """First URL in text whose host is a known conferencing provider."""
    for u in _urls(text):
        host = (urlsplit(u).hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in _CONF_HOSTS):
            return u
    return None


def extract_meeting_link(component: "icalendar.Event") -> str | None:
    """
    Find the meeting URL, preferring structured properties over scraped text:
    X-GOOGLE-CONFERENCE -> CONFERENCE (RFC 7986) -> conferencing URL in
    LOCATION/DESCRIPTION -> URL property -> any URL in LOCATION.
    """
    xg = component.get("X-GOOGLE-CONFERENCE")
    if xg:
        return str(xg).strip()

    conf = component.get("CONFERENCE")
    if conf:
        val = conf[0] if isinstance(conf, (list, tuple)) else conf
        return str(val).strip()

    for prop in ("LOCATION", "DESCRIPTION"):
        url = _conferencing_url(str(component.get(prop, "")))
        if url:
            return url

    url = component.get("URL")
    if url:
        return str(url).strip()

    loc_urls = _urls(str(component.get("LOCATION", "")))
    return loc_urls[0] if loc_urls else None


# --- Time handling ---

def to_aware_local(value: "date | datetime", local_tz: tzinfo) -> datetime:
    """
    Normalise an ical date/datetime to a tz-aware local datetime.
    datetime is a subclass of date, so the datetime check comes first.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=local_tz)
        return value.astimezone(local_tz)
    return datetime(value.year, value.month, value.day, tzinfo=local_tz)


def raw_end(component: "icalendar.Event", raw_start: "date | datetime") -> "date | datetime":
    """End as DTEND, else DTSTART+DURATION, else the start (zero-length)."""
    dtend = component.get("DTEND")
    if dtend is not None:
        return dtend.dt
    duration = component.get("DURATION")
    if duration is not None:
        return raw_start + duration.dt
    return raw_start


# --- Occurrence ---

@dataclass
class Occurrence:
    """A single concrete event occurrence in the lookahead window."""
    uid: str
    summary: str
    calendar: str
    start_local: datetime
    end_local: datetime
    all_day: bool
    link: str | None = None

    @property
    def key(self) -> tuple[str, int]:
        """Stable identity for de-duplication: (uid, epoch-second of start).
        Keyed on the absolute instant rather than a formatted timestamp, so it
        can't drift across polls from timezone-representation differences. A
        reschedule changes the instant, so it correctly reads as new."""
        return (self.uid, int(self.start_local.timestamp()))


def occurrences_from_ics(
        body: bytes, label: str, start: datetime, end: datetime,
        local_tz: tzinfo, logger: Logger,
) -> list[Occurrence]:
    """Parse an ICS body and expand its events within [start, end]."""
    occurrences: list[Occurrence] = []
    try:
        calendar = icalendar.Calendar.from_ical(body)
    except Exception as e:
        logger.log(f"parse failed for '{label}': {e}")
        return occurrences
    try:
        components = recurring_ical_events.of(calendar).between(start, end)
    except Exception as e:
        logger.log(f"expand failed for '{label}': {e}")
        return occurrences

    for component in components:
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        raw_start = dtstart.dt
        occurrences.append(
            Occurrence(
                uid=str(component.get("UID", "")),
                summary=str(component.get("SUMMARY", "(no title)")),
                calendar=label,
                start_local=to_aware_local(raw_start, local_tz),
                end_local=to_aware_local(raw_end(component, raw_start), local_tz),
                all_day=not isinstance(raw_start, datetime),
                link=extract_meeting_link(component),
            )
        )
    return occurrences


def collect_upcoming(
        feeds: list[Feed], window_hours: float, logger: Logger,
) -> list[Occurrence]:
    """Fetch and expand every feed; return occurrences sorted by start.

    Feeds returning 304/None are skipped this cycle (caller keeps prior data
    if it wants); returns whatever fetched successfully.
    """
    local_tz = datetime.now().astimezone().tzinfo
    now = datetime.now(tz=local_tz)
    end = now + timedelta(hours=window_hours)

    occurrences: list[Occurrence] = []
    for feed in feeds:
        body = fetch_feed(feed, logger, conditional=False)
        if body is None:
            continue
        occurrences.extend(
            occurrences_from_ics(body, feed.label, now, end, local_tz, logger))
    occurrences.sort(key=lambda o: o.start_local)
    return occurrences


# --- Firing logic ---

def is_due(occ: Occurrence, now: datetime, lead: timedelta) -> bool:
    """
    True when now is within the lead window before start: [start-lead, start).
    All-day events are excluded from pop-up reminders. Once start passes
    unfired (e.g. app was down), it won't retro-fire.
    """
    if occ.all_day:
        return False
    return occ.start_local - lead <= now < occ.start_local


def is_due_or_running(occ: Occurrence, now: datetime, lead: timedelta) -> bool:
    """
    Like is_due, but also true while the meeting is in progress (now < end).
    Used once at startup so a meeting already running when the app launches
    still pops, rather than being missed because its lead window elapsed before
    the app existed. All-day events are still excluded.
    """
    if occ.all_day:
        return False
    return occ.start_local - lead <= now < occ.end_local


def prune_seen(seen: set, retention_seconds: float) -> set:
    """
    Bound the notified-keys set: drop keys for events whose start is further in
    the past than retention_seconds, since they can no longer reappear in the
    lookahead window or still be running. Keys are (uid, epoch-second-of-start),
    so this is a pure time comparison against the absolute instant — independent
    of the current events list, so a transient empty/partial poll can't forget a
    still-relevant key and cause a re-fire.
    """
    cutoff = time.time() - retention_seconds
    return {k for k in seen if k[1] >= cutoff}


def format_time_range(occ: Occurrence) -> str:
    """'16:00 – 16:30', or with dates if it spans days, or 'All day'."""
    if occ.all_day:
        return "All day"
    start = occ.start_local.strftime("%H:%M")
    if occ.start_local.date() == occ.end_local.date():
        return f"{start} \u2013 {occ.end_local.strftime('%H:%M')}"
    return (f"{occ.start_local.strftime('%a %d %b %H:%M')} \u2013 "
            f"{occ.end_local.strftime('%a %d %b %H:%M')}")


def format_countdown(occ: Occurrence, now: datetime) -> str:
    """
    Live label for time until the meeting: 'now' once it has started, 'ended'
    once it's over, otherwise whole minutes remaining ('1 minute' / '2 minutes',
    rounded up so it reads '1 minute' right up to the start, then flips to 'now').
    """
    if now >= occ.start_local:
        return "ended" if now >= occ.end_local else "now"
    minutes = ceil((occ.start_local - now).total_seconds() / 60)
    return "1 minute" if minutes == 1 else f"{minutes} minutes"
