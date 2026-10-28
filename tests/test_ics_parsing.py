from datetime import datetime, timedelta, timezone

from nestcal_core import occurrences_from_ics

TZ = timezone(timedelta(hours=2))
WINDOW_START = datetime(2026, 1, 5, 0, 0, tzinfo=TZ)
WINDOW_END = datetime(2026, 1, 8, 0, 0, tzinfo=TZ)


def calendar(*events: str) -> bytes:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//nestcal tests//EN", *events, "END:VCALENDAR"]
    return "\r\n".join(lines).encode()


def event(*lines: str) -> str:
    return "\r\n".join(["BEGIN:VEVENT", *lines, "END:VEVENT"])


def parse(body: bytes, logger, start=WINDOW_START, end=WINDOW_END):
    return occurrences_from_ics(body, "work", start, end, TZ, logger)


def test_single_event_is_converted_to_local_time(logger):
    body = calendar(event("UID:a1", "SUMMARY:Standup",
                          "DTSTART:20260105T080000Z", "DTEND:20260105T083000Z"))
    [occ] = parse(body, logger)
    assert (occ.uid, occ.summary, occ.calendar, occ.all_day) == ("a1", "Standup", "work", False)
    assert occ.start_local == datetime(2026, 1, 5, 10, 0, tzinfo=TZ)
    assert occ.end_local == datetime(2026, 1, 5, 10, 30, tzinfo=TZ)


def test_events_outside_the_window_are_excluded(logger):
    body = calendar(event("UID:a1", "DTSTART:20260201T080000Z", "DTEND:20260201T083000Z"))
    assert parse(body, logger) == []


def test_duration_is_used_when_there_is_no_end(logger):
    body = calendar(event("UID:a1", "DTSTART:20260105T080000Z", "DURATION:PT45M"))
    [occ] = parse(body, logger)
    assert occ.end_local - occ.start_local == timedelta(minutes=45)


def test_no_end_or_duration_gives_a_zero_length_event(logger):
    body = calendar(event("UID:a1", "DTSTART:20260105T080000Z"))
    [occ] = parse(body, logger)
    assert occ.end_local == occ.start_local


def test_all_day_event_is_flagged(logger):
    body = calendar(event("UID:a1", "DTSTART;VALUE=DATE:20260106", "DTEND;VALUE=DATE:20260107"))
    [occ] = parse(body, logger)
    assert occ.all_day
    assert occ.start_local == datetime(2026, 1, 6, 0, 0, tzinfo=TZ)


def test_floating_time_is_taken_as_local(logger):
    body = calendar(event("UID:a1", "DTSTART:20260105T100000", "DTEND:20260105T110000"))
    [occ] = parse(body, logger)
    assert occ.start_local == datetime(2026, 1, 5, 10, 0, tzinfo=TZ)


def test_missing_summary_gets_a_placeholder(logger):
    body = calendar(event("UID:a1", "DTSTART:20260105T080000Z", "DTEND:20260105T083000Z"))
    [occ] = parse(body, logger)
    assert occ.summary == "(no title)"


def test_event_without_dtstart_is_skipped(logger):
    body = calendar(event("UID:a1", "SUMMARY:Broken"))
    assert parse(body, logger) == []


def test_recurring_event_is_expanded_into_each_occurrence_with_distinct_keys(logger):
    body = calendar(event("UID:r1", "SUMMARY:Daily",
                          "DTSTART:20260105T080000Z", "DTEND:20260105T083000Z",
                          "RRULE:FREQ=DAILY;COUNT=5"))
    occurrences = parse(body, logger)
    assert [o.start_local.day for o in occurrences] == [5, 6, 7]
    assert len({o.key for o in occurrences}) == 3


def test_excluded_date_is_not_expanded(logger):
    body = calendar(event("UID:r1", "DTSTART:20260105T080000Z", "DTEND:20260105T083000Z",
                          "RRULE:FREQ=DAILY;COUNT=3", "EXDATE:20260106T080000Z"))
    assert [o.start_local.day for o in parse(body, logger)] == [5, 7]


def test_moved_instance_of_a_recurring_event_replaces_the_original(logger):
    body = calendar(
        event("UID:r1", "SUMMARY:Daily", "DTSTART:20260105T080000Z", "DTEND:20260105T083000Z",
              "RRULE:FREQ=DAILY;COUNT=2"),
        event("UID:r1", "SUMMARY:Daily (moved)", "RECURRENCE-ID:20260106T080000Z",
              "DTSTART:20260106T130000Z", "DTEND:20260106T133000Z"),
    )
    occurrences = parse(body, logger)
    assert [(o.summary, o.start_local.hour) for o in occurrences] == [("Daily", 10), ("Daily (moved)", 15)]


def test_meeting_link_is_extracted(logger):
    body = calendar(event("UID:a1", "DTSTART:20260105T080000Z", "DTEND:20260105T083000Z",
                          "LOCATION:https://meet.google.com/aaa-bbbb-ccc"))
    [occ] = parse(body, logger)
    assert occ.link == "https://meet.google.com/aaa-bbbb-ccc"


def test_unparseable_body_gives_no_events_and_is_logged(logger, capsys):
    assert parse(b"this is not a calendar", logger) == []
    assert "parse failed for 'work'" in capsys.readouterr().err
