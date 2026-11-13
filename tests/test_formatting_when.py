from datetime import datetime, timedelta, timezone

from nestcal_core import Occurrence, format_when, format_when_long

TZ = timezone(timedelta(hours=2))
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=TZ)  # a Friday


def occ(start, end=None, all_day=False):
    end = end or start + timedelta(minutes=30)
    return Occurrence(uid="u", summary="s", calendar="work", start_local=start, end_local=end, all_day=all_day)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


class TestFormatWhen:
    def test_today_is_called_today(self):
        assert format_when(occ(at(13, 14), at(13, 15)), NOW) == "Today 14:00 – 15:00"

    def test_tomorrow_is_called_tomorrow(self):
        assert format_when(occ(at(14, 9), at(14, 9, 30)), NOW) == "Tomorrow 09:00 – 09:30"

    def test_a_later_day_is_named(self):
        assert format_when(occ(at(16, 9), at(16, 10)), NOW) == "Mon 16 Nov 09:00 – 10:00"

    def test_an_event_spanning_midnight_names_both_ends(self):
        assert format_when(occ(at(13, 22), at(14, 1)), NOW) == "Today 22:00 – Tomorrow 01:00"

    def test_an_event_in_progress_says_so(self):
        assert format_when(occ(at(13, 11, 30), at(13, 12, 30)), NOW) == "Today 11:30 – 12:30 (in progress)"

    def test_an_all_day_event_says_so(self):
        assert format_when(occ(at(13, 0), at(14, 0), all_day=True), NOW) == "Today (all day)"

    def test_a_multi_day_all_day_event_shows_its_last_day_not_the_exclusive_end(self):
        assert format_when(occ(at(13, 0), at(16, 0), all_day=True), NOW) == "Today – Sun 15 Nov (all day)"

    def test_dates_are_judged_in_the_events_own_timezone(self):
        late_utc_now = datetime(2026, 11, 13, 23, 30, tzinfo=timezone.utc)  # already Saturday at +02:00
        assert format_when(occ(at(14, 9), at(14, 10)), late_utc_now) == "Today 09:00 – 10:00"


class TestFormatWhenLong:
    def test_a_one_day_event(self):
        assert format_when_long(occ(at(13, 14), at(13, 15))) == "Friday 13 November 2026, 14:00 – 15:00"

    def test_an_event_spanning_days(self):
        assert format_when_long(occ(at(13, 22), at(14, 1))) == (
            "Friday 13 November 2026, 22:00 – Saturday 14 November 2026, 01:00")

    def test_an_all_day_event(self):
        assert format_when_long(occ(at(13, 0), at(14, 0), all_day=True)) == "Friday 13 November 2026 (all day)"

    def test_a_multi_day_all_day_event(self):
        assert format_when_long(occ(at(13, 0), at(16, 0), all_day=True)) == (
            "Friday 13 November 2026 – Sunday 15 November 2026 (all day)")
