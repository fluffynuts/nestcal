"""On Windows, replacing a file that something else has open (antivirus scanning what was just
written, an indexer) fails with 'Access is denied' for a moment. CI showed it: a save from the
Preferences tab, milliseconds after the file was written, failed with WinError 5 on os.replace."""
import os

import pytest

import nestcal_core
from nestcal_core import replace_file


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(nestcal_core.time, "sleep", recorded.append)
    return recorded


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(nestcal_core, "RETRY_DENIED_REPLACE", True)


def files(tmp_path):
    source, target = tmp_path / "new", tmp_path / "old"
    source.write_text("new")
    target.write_text("old")
    return source, target


def denied_times(monkeypatch, times):
    real, calls = os.replace, []

    def replace(src, dst):
        calls.append(1)
        if len(calls) <= times:
            raise PermissionError(13, "Access is denied")
        real(src, dst)
    monkeypatch.setattr(nestcal_core.os, "replace", replace)
    return calls


def test_a_replace_that_is_denied_for_a_moment_succeeds_when_retried(tmp_path, monkeypatch, sleeps, on_windows):
    source, target = files(tmp_path)
    calls = denied_times(monkeypatch, 3)

    replace_file(source, target)

    assert target.read_text() == "new" and not source.exists()
    assert len(calls) == 4
    assert sleeps == list(nestcal_core.REPLACE_RETRY_DELAYS[:3])


def test_a_replace_that_stays_denied_gives_up_after_the_last_delay_and_raises(tmp_path, monkeypatch, sleeps, on_windows):
    source, target = files(tmp_path)
    calls = denied_times(monkeypatch, 1000)

    with pytest.raises(PermissionError):
        replace_file(source, target)

    assert len(calls) == len(nestcal_core.REPLACE_RETRY_DELAYS) + 1
    assert sleeps == list(nestcal_core.REPLACE_RETRY_DELAYS)
    assert target.read_text() == "old"


def test_the_whole_wait_is_short_enough_not_to_freeze_the_window():
    assert sum(nestcal_core.REPLACE_RETRY_DELAYS) < 1.5


def test_other_errors_are_not_retried(tmp_path, monkeypatch, sleeps, on_windows):
    source, target = files(tmp_path)
    calls = []

    def replace(src, dst):
        calls.append(1)
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(nestcal_core.os, "replace", replace)

    with pytest.raises(OSError, match="No space"):
        replace_file(source, target)

    assert len(calls) == 1 and sleeps == []


def test_off_windows_a_denied_replace_is_a_real_permissions_problem_and_is_not_retried(
        tmp_path, monkeypatch, sleeps):
    monkeypatch.setattr(nestcal_core, "RETRY_DENIED_REPLACE", False)
    source, target = files(tmp_path)
    calls = denied_times(monkeypatch, 1000)

    with pytest.raises(PermissionError):
        replace_file(source, target)

    assert len(calls) == 1 and sleeps == []


def test_saving_the_config_survives_a_replace_denied_for_a_moment(tmp_path, monkeypatch, sleeps, on_windows):
    config = tmp_path / "config.ini"
    config.write_text("[calendars]\nwork = https://example.com/a.ics\n")
    monkeypatch.setattr(nestcal_core, "CONFIG_PATH", config)
    denied_times(monkeypatch, 2)

    nestcal_core.save_settings({"lead_minutes": "5"})

    assert "lead_minutes = 5" in config.read_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.ini"]


def test_saving_the_state_survives_a_replace_denied_for_a_moment(tmp_path, monkeypatch, sleeps, on_windows):
    import nestcal_update
    path = tmp_path / "state.json"
    monkeypatch.setattr(nestcal_update, "STATE_PATH", path)
    denied_times(monkeypatch, 2)

    nestcal_update.save_state({"x": 1}, nestcal_core.Logger(False))

    assert path.read_text() == '{"x": 1}'
