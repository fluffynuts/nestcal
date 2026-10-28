from datetime import date, datetime, timedelta, timezone


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def calendar(*events: str) -> bytes:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//nestcal ui tests//EN", *events, "END:VCALENDAR"]
    return "\r\n".join(lines).encode()


def event(uid: str, summary: str, starts_in: timedelta, length: timedelta = timedelta(minutes=30),
          location: str | None = None) -> str:
    """An event starting `starts_in` from now (negative = already started)."""
    start = datetime.now(timezone.utc) + starts_in
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{summary}",
             f"DTSTART:{_utc(start)}", f"DTEND:{_utc(start + length)}"]
    if location:
        lines.append(f"LOCATION:{location}")
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def all_day_event(uid: str, summary: str) -> str:
    today = date.today()
    return "\r\n".join(["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{summary}",
                        f"DTSTART;VALUE=DATE:{today:%Y%m%d}",
                        f"DTEND;VALUE=DATE:{today + timedelta(days=1):%Y%m%d}",
                        "END:VEVENT"])
