from datetime import datetime, timedelta, timezone

import pytest

from nestcal_core import Logger, Occurrence

LOCAL_TZ = timezone(timedelta(hours=2))


@pytest.fixture
def local_tz():
    return LOCAL_TZ


@pytest.fixture
def logger():
    return Logger(debug=True)


@pytest.fixture
def make_occurrence():
    def make(start=datetime(2026, 1, 5, 10, 0, tzinfo=LOCAL_TZ),
             length=timedelta(minutes=30), all_day=False, uid="uid-1", summary="Meeting"):
        return Occurrence(uid=uid, summary=summary, calendar="work",
                          start_local=start, end_local=start + length,
                          all_day=all_day)
    return make
