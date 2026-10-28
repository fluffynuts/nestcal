from datetime import datetime, timedelta, timezone

import nestcal_core
from nestcal_core import prune_seen, to_aware_local

TZ = timezone(timedelta(hours=2))


class TestOccurrenceKey:
    def test_is_uid_and_epoch_second_of_start(self, make_occurrence):
        start = datetime(2026, 1, 5, 10, 0, tzinfo=TZ)
        assert make_occurrence(start, uid="abc").key == ("abc", int(start.timestamp()))

    def test_same_instant_in_another_timezone_has_the_same_key(self, make_occurrence):
        in_utc = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
        in_local = datetime(2026, 1, 5, 10, 0, tzinfo=TZ)
        assert make_occurrence(in_utc).key == make_occurrence(in_local).key

    def test_rescheduling_changes_the_key(self, make_occurrence):
        original = make_occurrence(datetime(2026, 1, 5, 10, 0, tzinfo=TZ))
        moved = make_occurrence(datetime(2026, 1, 5, 11, 0, tzinfo=TZ))
        assert original.key != moved.key


class TestPruneSeen:
    def test_drops_keys_older_than_retention_and_keeps_the_rest(self, monkeypatch):
        monkeypatch.setattr(nestcal_core.time, "time", lambda: 10_000.0)
        seen = {("old", 8_999), ("edge", 9_000), ("recent", 9_500), ("future", 20_000)}
        assert prune_seen(seen, 1_000) == {("edge", 9_000), ("recent", 9_500), ("future", 20_000)}

    def test_empty_set_stays_empty(self):
        assert prune_seen(set(), 1_000) == set()


class TestToAwareLocal:
    def test_naive_datetime_is_taken_as_local(self):
        result = to_aware_local(datetime(2026, 1, 5, 10, 0), TZ)
        assert result == datetime(2026, 1, 5, 10, 0, tzinfo=TZ)

    def test_aware_datetime_is_converted_to_local(self):
        result = to_aware_local(datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc), TZ)
        assert result == datetime(2026, 1, 5, 10, 0, tzinfo=TZ)
        assert result.utcoffset() == timedelta(hours=2)

    def test_date_becomes_local_midnight(self):
        result = to_aware_local(datetime(2026, 1, 5).date(), TZ)
        assert result == datetime(2026, 1, 5, 0, 0, tzinfo=TZ)
