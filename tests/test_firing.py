from datetime import datetime, timedelta, timezone

import pytest

from nestcal_core import is_due, is_due_or_running, is_running

LEAD = timedelta(minutes=2)
START = datetime(2026, 1, 5, 10, 0, tzinfo=timezone(timedelta(hours=2)))
END = START + timedelta(minutes=30)


class TestIsDue:
    def test_true_exactly_at_lead_boundary(self, make_occurrence):
        assert is_due(make_occurrence(START), START - LEAD, LEAD)

    def test_false_just_before_lead_window(self, make_occurrence):
        assert not is_due(make_occurrence(START), START - LEAD - timedelta(seconds=1), LEAD)

    def test_true_just_before_start(self, make_occurrence):
        assert is_due(make_occurrence(START), START - timedelta(seconds=1), LEAD)

    def test_false_at_start(self, make_occurrence):
        assert not is_due(make_occurrence(START), START, LEAD)

    def test_false_once_started_so_missed_meetings_do_not_retro_fire(self, make_occurrence):
        assert not is_due(make_occurrence(START), START + timedelta(minutes=5), LEAD)

    def test_all_day_is_never_due(self, make_occurrence):
        assert not is_due(make_occurrence(START, all_day=True), START - timedelta(minutes=1), LEAD)


class TestIsDueOrRunning:
    def test_true_in_lead_window(self, make_occurrence):
        assert is_due_or_running(make_occurrence(START), START - timedelta(minutes=1), LEAD)

    def test_true_while_in_progress(self, make_occurrence):
        assert is_due_or_running(make_occurrence(START), START + timedelta(minutes=10), LEAD)

    def test_false_at_end(self, make_occurrence):
        assert not is_due_or_running(make_occurrence(START), END, LEAD)

    def test_false_before_lead_window(self, make_occurrence):
        assert not is_due_or_running(make_occurrence(START), START - timedelta(minutes=3), LEAD)

    def test_all_day_is_never_due_or_running(self, make_occurrence):
        assert not is_due_or_running(make_occurrence(START, all_day=True), START, LEAD)


class TestIsRunning:
    @pytest.mark.parametrize("now, expected", [
        (START - timedelta(seconds=1), False),
        (START, True),
        (END - timedelta(seconds=1), True),
        (END, False),
    ])
    def test_start_inclusive_end_exclusive(self, make_occurrence, now, expected):
        assert is_running(make_occurrence(START), now) is expected

    def test_all_day_is_never_running(self, make_occurrence):
        assert not is_running(make_occurrence(START, all_day=True), START)
