"""Finding out whether a newer nestcal release exists on GitHub."""

import contextlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from nestcal_core import HTTP_TIMEOUT, USER_AGENT, Logger

# Not in nestcal.ini: that is the user's to edit, and writing here must not look like an edit.
STATE_PATH = Path.home() / ".config" / "nestcal.state.json"
# After the first prompt about a release, wait this many days before the next, and so on;
# after the last it is not prompted about again. Busy is not the same as uninterested,
# so one dismissal isn't the end of it, but nobody is nagged for ever.
PROMPT_BACKOFF_DAYS = (2, 4)

RELEASES_URL = "https://github.com/fluffynuts/nestcal/releases"
LATEST_RELEASE_API_URL = "https://api.github.com/repos/fluffynuts/nestcal/releases/latest"


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v0.1.42' or '0.1.42' -> (0, 1, 42); None for anything else, e.g. 'dev'.
    A suffix such as '-beta' is accepted and ignored: a branch build is compared
    by its number, so it's told about any release numbered above it."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)(?:-[0-9A-Za-z.-]+)?", text.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    """True only when both parse and latest is strictly greater, compared
    numerically per component (so 0.1.10 is newer than 0.1.9)."""
    latest_version, current_version = parse_version(latest), parse_version(current)
    if latest_version is None or current_version is None:
        return False
    return latest_version > current_version


def fetch_latest_version(logger: Logger) -> str | None:
    """The tag of the latest published release, or None (logged) if it can't be determined."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    try:
        resp = requests.get(LATEST_RELEASE_API_URL, headers=headers, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        logger.log(f"update check: fetch error: {e}")
        return None
    if resp.status_code != 200:
        logger.log(f"update check: unexpected status {resp.status_code}")
        return None
    try:
        tag = resp.json().get("tag_name")
    except (ValueError, AttributeError) as e:
        logger.log(f"update check: unreadable response: {e!r}")
        return None
    if not isinstance(tag, str):
        logger.log("update check: response has no tag_name")
        return None
    return tag


def load_state(logger: Logger) -> dict:
    """What nestcal remembers between runs; empty if there is nothing (usable) yet."""
    try:
        state = json.loads(STATE_PATH.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.log(f"state file unreadable, starting afresh: {e}")
        return {}
    if not isinstance(state, dict):
        logger.log("state file has an unexpected shape, starting afresh")
        return {}
    return state


def save_state(state: dict, logger: Logger) -> None:
    """Losing this only means being asked about an update again sooner, so a failure is logged, not raised."""
    temp = STATE_PATH.with_name(STATE_PATH.name + ".tmp")
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(state))
        os.replace(temp, STATE_PATH)
    except OSError as e:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)
        logger.log(f"could not save the state file: {e}")


def _prompt_record(state: dict, latest: str) -> tuple[int, datetime | None]:
    """(how many times prompted about `latest`, when last): (0, None) when there's no record
    for it or the record can't be understood. This file is edited by hand and read inside a Qt
    slot, where an exception aborts the whole app, so nothing in it may raise."""
    prompts = state.get("update_prompts")
    if not isinstance(prompts, dict) or prompts.get("version") != latest:
        return 0, None
    count = prompts.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        return 0, None
    try:
        last = datetime.fromisoformat(prompts["last"])
    except (KeyError, TypeError, ValueError):
        # Past the last back-off the date no longer matters: it is forgotten either way.
        return (count, None) if count > len(PROMPT_BACKOFF_DAYS) else (0, None)
    return count, last if last.tzinfo else last.replace(tzinfo=timezone.utc)


def should_prompt(state: dict, latest: str, now: datetime) -> bool:
    """Whether to pop up the update dialog for release `latest` now."""
    count, last = _prompt_record(state, latest)
    if count == 0:
        return True
    if count > len(PROMPT_BACKOFF_DAYS):
        return False
    return now >= last + timedelta(days=PROMPT_BACKOFF_DAYS[count - 1])


def record_prompt(state: dict, latest: str, now: datetime) -> dict:
    """The state after having prompted about `latest` at `now`."""
    count, _ = _prompt_record(state, latest)
    return {**state, "update_prompts": {"version": latest, "count": count + 1, "last": now.isoformat()}}
