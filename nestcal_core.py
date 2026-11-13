#!/usr/bin/env python3
"""
nestcal_core - Qt-free calendar logic for nestcal.

Fetches ICS feeds, expands recurring events, and extracts the bits a reminder
needs: title, start/end, and the meeting link. Deliberately has no Qt
dependency so it can be unit-tested headlessly and reused by both the standalone
tray app and an eventual Nestray integration.
"""

import configparser
import contextlib
import os
import re
import shutil
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

# A folder of nestcal's own, so that watching it hears only about nestcal's files.
CONFIG_DIR = Path.home() / ".config" / "nestcal"
CONFIG_PATH = CONFIG_DIR / "config.ini"
LEGACY_CONFIG_PATH = Path.home() / ".config" / "nestcal.ini"  # where releases up to 0.1.x kept it
HTTP_TIMEOUT = 20
USER_AGENT = "nestcal/0.1"

SETTINGS_DEFAULTS = {
    "poll_interval": "300",   # seconds between network fetches
    "lead_minutes": "2",      # how long before start to fire the reminder
    "window_hours": "24",     # lookahead horizon
    "snooze_minutes": "1",    # snooze duration on the reminder window
    "check_interval": "5",    # seconds between due-checks (firing precision)
    "check_for_updates": "true",  # ask GitHub whether a newer nestcal exists
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

def _new_parser() -> configparser.ConfigParser:
    config = configparser.ConfigParser(interpolation=None)  # URLs contain literal %
    config.optionxform = str  # preserve calendar-label case
    return config


def read_config() -> configparser.ConfigParser:
    """Read CONFIG_PATH as it is right now. Unlike load_config this never creates the
    file and never hides a problem: a missing file raises OSError, a malformed one
    configparser.Error, so a caller reloading after an edit can keep its last good config."""
    config = _new_parser()
    with open(CONFIG_PATH) as f:
        config.read_file(f)
    return config


def load_config(logger: Logger) -> configparser.ConfigParser:
    """
    Load config, creating a 0600 commented stub if absent (the ICS URLs are
    bearer secrets). Warns if an existing file is group/other-accessible.
    """
    config = _new_parser()

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


def migrate_legacy_config(logger: Logger) -> None:
    """Move ~/.config/nestcal.ini to its new home, once. OSError if it can't be moved, with
    the old file left where it was: starting without the user's calendars would look like losing them."""
    legacy = LEGACY_CONFIG_PATH
    if not (legacy.exists() or legacy.is_symlink()):
        return
    if CONFIG_PATH.exists() or CONFIG_PATH.is_symlink():
        print(f"nestcal: warning: ignoring the old config {legacy}: {CONFIG_PATH} exists and is the "
              f"one in use. Delete the old file once you have what you need from it.", file=sys.stderr)
        return
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if legacy.is_symlink():
        # People keep the file in a dotfiles repo: link to the same file, not to a possibly relative path.
        os.symlink(legacy.resolve(), CONFIG_PATH)
        legacy.unlink()
    else:
        shutil.move(legacy, CONFIG_PATH)
    logger.log(f"moved the config from {legacy} to {CONFIG_PATH}")


def normalise_ics_url(url: str) -> str:
    """Strip whitespace; webcal:// (what Apple/Outlook hand out) is https underneath."""
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    return url


def validate_calendar(label: str, url: str) -> str | None:
    """Return a message for the user if the label/url can't be saved, else None."""
    label, url = label.strip(), normalise_ics_url(url)
    if not label:
        return "Please enter a name for the calendar, for example: work"
    if any(c in label for c in "=:") or label[0] in "#;[":
        return "The name can't contain = or : or start with # ; or ["
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "The link should start with https:// (it usually ends in .ics)"
    return None


def add_calendar(label: str, url: str) -> None:
    """
    Add `label = url` under [calendars] in CONFIG_PATH, leaving the rest of the
    file (comments, settings) untouched. Creates the file if needed.
    """
    problem = validate_calendar(label, url)
    if problem:
        raise ValueError(problem)
    entry = f"{label.strip()} = {normalise_ics_url(url)}\n"

    lines = CONFIG_PATH.read_text().splitlines(keepends=True) if CONFIG_PATH.exists() else []
    header = next((i for i, l in enumerate(lines) if l.strip().lower() == "[calendars]"), None)
    if header is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines += ["\n[calendars]\n", entry]
    else:
        if not lines[header].endswith("\n"):
            lines[header] += "\n"
        lines.insert(header + 1, entry)

    _write_config_lines(lines)


# On Windows, replacing a file that something else has open (antivirus scanning what was just
# written, an indexer) fails with "Access is denied" for a moment; CI showed a save milliseconds
# after the file was written failing that way. Elsewhere a denied replace is a real permissions
# problem, and waiting would only delay the error.
RETRY_DENIED_REPLACE = sys.platform == "win32"
REPLACE_RETRY_DELAYS = (0.02, 0.05, 0.1, 0.2, 0.4)  # seconds: under a second in all


def replace_file(source: Path, target: Path) -> None:
    """os.replace, tried again for a moment on Windows if it's denied; PermissionError if it stays denied."""
    for delay in REPLACE_RETRY_DELAYS if RETRY_DENIED_REPLACE else ():
        try:
            os.replace(source, target)
            return
        except PermissionError:
            time.sleep(delay)
    os.replace(source, target)


def _write_config_lines(lines: list[str]) -> None:
    """Replace the config atomically (a watcher or a crash never sees half a file),
    0600 because the URLs are secrets. Writes through a symlink rather than replacing
    it, since people keep their config in a dotfiles repo."""
    target = CONFIG_PATH.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.writelines(lines)
        replace_file(temp, target)
    except OSError:
        # The temp file holds the calendar URLs, which are secrets: never leave it lying about.
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)
        raise


def _is_calendar_entry(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and stripped[0] not in "#;"


def _section_span(lines: list[str], name: str) -> tuple[int, int] | None:
    """(index of the [name] header, index of the next header or end of file)."""
    header = next((i for i, l in enumerate(lines) if l.strip().lower() == f"[{name}]"), None)
    if header is None:
        return None
    end = next((i for i in range(header + 1, len(lines))
                if lines[i].strip().startswith("[") and lines[i].strip().endswith("]")), len(lines))
    return header, end


def _read_lines() -> list[str]:
    return CONFIG_PATH.read_text().splitlines(keepends=True) if CONFIG_PATH.exists() else []


def _rewrite_section(name: str, rewrite) -> None:
    """Apply `rewrite(body_lines) -> body_lines` to the lines under [name], creating the
    section at the end of the file if it's missing. Everything outside the section is kept as is."""
    lines = _read_lines()
    span = _section_span(lines, name)
    if span is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        _write_config_lines(lines + ([] if not lines else ["\n"]) + [f"[{name}]\n"] + rewrite([]))
        return
    header, end = span
    if not lines[header].endswith("\n"):
        lines[header] += "\n"
    _write_config_lines(lines[:header + 1] + rewrite(lines[header + 1:end]) + lines[end:])


def _after_last_content(body: list[str]) -> int:
    """Where to add new lines to a section: straight after its last non-blank line, so the
    blank line that separates it from the next section stays a separator."""
    return next((i + 1 for i in range(len(body) - 1, -1, -1) if body[i].strip()), 0)


def _with_newline_at(body: list[str], position: int) -> list[str]:
    if position and not body[position - 1].endswith("\n"):
        body = body[:position - 1] + [body[position - 1] + "\n"] + body[position:]
    return body


def save_calendars(calendars: list[tuple[str, str]]) -> None:
    """
    Make the entries under [calendars] exactly `calendars`, in order, leaving every
    other line of the file (comments, settings, blank lines) untouched. Entries
    take the place of the first old entry; comments in the section stay where they were.
    """
    names = [label.strip() for label, _ in calendars]
    for label, url in calendars:
        problem = validate_calendar(label, url)
        if problem:
            raise ValueError(problem)
    for name in set(names):
        if names.count(name) > 1:
            raise ValueError(f"There is more than one calendar called '{name}'")
    entries = [f"{label.strip()} = {normalise_ics_url(url)}\n" for label, url in calendars]

    def rewrite(body: list[str]) -> list[str]:
        first_entry = next((i for i, l in enumerate(body) if _is_calendar_entry(l)), None)
        kept = [l for l in body if not _is_calendar_entry(l)]
        if first_entry is None:
            first_entry = _after_last_content(kept)
        kept = _with_newline_at(kept, first_entry)
        return kept[:first_entry] + entries + kept[first_entry:]
    _rewrite_section("calendars", rewrite)


# --- Settings ---

@dataclass(frozen=True)
class Settings:
    poll_interval: int
    lead_minutes: float
    window_hours: float
    snooze_minutes: int
    check_interval: int
    check_for_updates: bool


def _parse_setting(key: str, text: str):
    """The typed value of a setting, or ValueError saying what's wrong with it."""
    text = text.strip()
    if key == "check_for_updates":
        try:
            return configparser.ConfigParser.BOOLEAN_STATES[text.lower()]
        except KeyError:
            raise ValueError(f"check_for_updates must be true or false, not '{text}'") from None
    whole = key in ("poll_interval", "snooze_minutes", "check_interval")
    try:
        value = int(text) if whole else float(text)
    except ValueError:
        kind = "a whole number" if whole else "a number"
        raise ValueError(f"{key} must be {kind}, not '{text}'") from None
    if key == "window_hours":
        if value <= 0:
            raise ValueError(f"{key} must be more than 0, not '{text}'")
    elif value < (0 if key == "lead_minutes" else 1):
        raise ValueError(f"{key} must be at least {0 if key == 'lead_minutes' else 1}, not '{text}'")
    return value


def parse_settings(config: configparser.ConfigParser) -> Settings:
    """The [settings] of a config, defaults filled in. ValueError (naming the setting) if any is unusable."""
    return Settings(**{key: _parse_setting(key, get_setting(config, key)) for key in SETTINGS_DEFAULTS})


def save_settings(values: dict[str, str]) -> None:
    """
    Write these [settings] values (key -> text) to the config file, changing a key's own
    line where it has one and adding it to the section where it doesn't. Everything else,
    comments included, is left as it is. ValueError, with the file untouched, if a value
    wouldn't read back.
    """
    for key, text in values.items():
        if key not in SETTINGS_DEFAULTS:
            raise ValueError(f"'{key}' is not a setting nestcal has")
        _parse_setting(key, text)

    def rewrite(body: list[str]) -> list[str]:
        for key, text in values.items():
            own_line = re.compile(rf"\s*{re.escape(key)}\s*[=:]")
            index = next((i for i, l in enumerate(body) if own_line.match(l) and _is_calendar_entry(l)), None)
            if index is not None:
                body[index] = f"{key} = {text.strip()}\n"
            else:
                position = _after_last_content(body)
                body = _with_newline_at(body, position)
                body[position:position] = [f"{key} = {text.strip()}\n"]
        return body
    _rewrite_section("settings", rewrite)


@dataclass
class FeedCheck:
    ok: bool
    message: str


def check_feed(url: str) -> FeedCheck:
    """Fetch and parse a calendar link once, so the user learns now, in plain words,
    whether it will work, rather than when a reminder silently never comes."""
    try:
        resp = requests.get(normalise_ics_url(url), headers={"User-Agent": USER_AGENT},
                            timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        return FeedCheck(False, f"Couldn't reach that link: {e}")
    if resp.status_code != 200:
        return FeedCheck(False, f"The server answered {resp.status_code} instead of a calendar. "
                                f"Is the link complete and still valid?")
    try:
        events = list(icalendar.Calendar.from_ical(resp.content).walk("VEVENT"))
    except Exception:
        return FeedCheck(False, "That link works, but it isn't a calendar (.ics) file.")
    return FeedCheck(True, f"Looks good: {len(events)} event{'' if len(events) == 1 else 's'} found")


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


def is_running(occ: Occurrence, now: datetime) -> bool:
    """True while the meeting is in progress: started and not yet ended.
    All-day events are excluded (they're not pop-up reminders)."""
    if occ.all_day:
        return False
    return occ.start_local <= now < occ.end_local


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


def _day_name(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    return day.strftime("%a %d %b")


def format_when(occ: Occurrence, now: datetime) -> str:
    """For a grid: 'Today 14:00 \u2013 15:00', 'Tomorrow (all day)', 'Mon 16 Nov 09:00 \u2013 10:00'."""
    today = now.astimezone(occ.start_local.tzinfo).date()
    first_day = _day_name(occ.start_local.date(), today)
    if occ.all_day:
        last = occ.end_local.date() - timedelta(days=1)  # an all-day event's end is the day after
        span = first_day if last <= occ.start_local.date() else f"{first_day} \u2013 {_day_name(last, today)}"
        return f"{span} (all day)"
    start = occ.start_local.strftime("%H:%M")
    end = occ.end_local.strftime("%H:%M")
    if occ.start_local.date() == occ.end_local.date():
        text = f"{first_day} {start} \u2013 {end}"
    else:
        text = f"{first_day} {start} \u2013 {_day_name(occ.end_local.date(), today)} {end}"
    if occ.start_local <= now < occ.end_local:
        text += " (in progress)"
    return text


def format_when_long(occ: Occurrence) -> str:
    """For a details view: 'Friday 13 November 2026, 14:00 \u2013 15:00'."""
    day = "%A %d %B %Y"
    if occ.all_day:
        last = occ.end_local - timedelta(days=1)
        if last.date() <= occ.start_local.date():
            return f"{occ.start_local.strftime(day)} (all day)"
        return f"{occ.start_local.strftime(day)} \u2013 {last.strftime(day)} (all day)"
    if occ.start_local.date() == occ.end_local.date():
        return f"{occ.start_local.strftime(day)}, {occ.start_local:%H:%M} \u2013 {occ.end_local:%H:%M}"
    return (f"{occ.start_local.strftime(day)}, {occ.start_local:%H:%M} \u2013 "
            f"{occ.end_local.strftime(day)}, {occ.end_local:%H:%M}")


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
