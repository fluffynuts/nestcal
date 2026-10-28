from datetime import datetime, timedelta, timezone

import pytest

from nestcal_core import format_countdown, format_time_range

TZ = timezone(timedelta(hours=2))
START = datetime(2026, 1, 5, 10, 0, tzinfo=TZ)  # a Monday


class TestFormatTimeRange:
    def test_same_day_shows_times_only(self, make_occurrence):
        assert format_time_range(make_occurrence(START)) == "10:00 – 10:30"

    def test_spanning_days_includes_dates(self, make_occurrence):
        occ = make_occurrence(datetime(2026, 1, 5, 22, 0, tzinfo=TZ), length=timedelta(hours=3))
        assert format_time_range(occ) == "Mon 05 Jan 22:00 – Tue 06 Jan 01:00"

    def test_all_day(self, make_occurrence):
        assert format_time_range(make_occurrence(START, all_day=True)) == "All day"


class TestFormatCountdown:
    @pytest.mark.parametrize("seconds_before_start, expected", [
        (600, "10 minutes"),
        (121, "3 minutes"),
        (120, "2 minutes"),
        (61, "2 minutes"),
        (60, "1 minute"),
        (1, "1 minute"),
    ])
    def test_rounds_up_to_whole_minutes(self, make_occurrence, seconds_before_start, expected):
        now = START - timedelta(seconds=seconds_before_start)
        assert format_countdown(make_occurrence(START), now) == expected

    def test_now_from_the_start_instant(self, make_occurrence):
        assert format_countdown(make_occurrence(START), START) == "now"

    def test_now_while_in_progress(self, make_occurrence):
        assert format_countdown(make_occurrence(START), START + timedelta(minutes=29)) == "now"

    def test_ended_from_the_end_instant(self, make_occurrence):
        assert format_countdown(make_occurrence(START), START + timedelta(minutes=30)) == "ended"
