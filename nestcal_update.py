"""Finding out whether a newer nestcal release exists on GitHub."""

import re

import requests

from nestcal_core import HTTP_TIMEOUT, USER_AGENT, Logger

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
