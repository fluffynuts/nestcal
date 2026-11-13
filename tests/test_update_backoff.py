import json
from datetime import datetime, timedelta, timezone

import pytest

import nestcal_update
from nestcal_core import Logger
from nestcal_update import load_state, record_prompt, save_state, should_prompt

T0 = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)


def after(days: float) -> datetime:
    return T0 + timedelta(days=days)


def test_a_release_never_prompted_about_is_prompted_about_immediately():
    assert should_prompt({}, "v0.2.0", T0)


def test_after_one_prompt_it_waits_two_days():
    state = record_prompt({}, "v0.2.0", T0)

    assert not should_prompt(state, "v0.2.0", after(1.9))
    assert should_prompt(state, "v0.2.0", after(2))


def test_after_a_second_prompt_it_waits_four_days():
    state = record_prompt(record_prompt({}, "v0.2.0", T0), "v0.2.0", after(2))

    assert not should_prompt(state, "v0.2.0", after(2 + 3.9))
    assert should_prompt(state, "v0.2.0", after(2 + 4))


def test_after_a_third_prompt_it_forgets_that_release():
    state = record_prompt(record_prompt(record_prompt({}, "v0.2.0", T0), "v0.2.0", after(2)), "v0.2.0", after(6))

    assert not should_prompt(state, "v0.2.0", after(6 + 365))


def test_a_newer_release_starts_the_schedule_again():
    state = record_prompt(record_prompt(record_prompt({}, "v0.2.0", T0), "v0.2.0", after(2)), "v0.2.0", after(6))

    assert should_prompt(state, "v0.2.1", after(7))
    assert not should_prompt(record_prompt(state, "v0.2.1", after(7)), "v0.2.1", after(8))


def test_recording_does_not_modify_the_state_it_was_given():
    original = {}

    record_prompt(original, "v0.2.0", T0)

    assert original == {}


class TestStateFile:
    @pytest.fixture(autouse=True)
    def state_path(self, tmp_path, monkeypatch):
        path = tmp_path / "nestcal.state.json"
        monkeypatch.setattr(nestcal_update, "STATE_PATH", path)
        return path

    def test_what_is_saved_is_loaded_back(self):
        state = record_prompt({}, "v0.2.0", T0)

        save_state(state, Logger(False))

        assert load_state(Logger(False)) == state
        assert not should_prompt(load_state(Logger(False)), "v0.2.0", after(1))

    def test_no_file_is_an_empty_state(self):
        assert load_state(Logger(False)) == {}

    def test_an_unreadable_file_is_an_empty_state_and_is_logged(self, state_path, capsys):
        state_path.write_text("{not json")

        assert load_state(Logger(True)) == {}
        assert "state" in capsys.readouterr().err

    def test_a_file_of_the_wrong_shape_is_an_empty_state(self, state_path):
        state_path.write_text(json.dumps(["a", "list"]))

        assert load_state(Logger(False)) == {}

    def test_a_state_that_cannot_be_saved_is_logged_not_raised(self, state_path, capsys):
        state_path.mkdir()  # a directory where the file should be

        save_state({"x": 1}, Logger(True))

        assert "could not save" in capsys.readouterr().err


class TestDamagedState:
    """The state file is user-editable and read in a Qt slot, where an exception aborts the
    app. Anything that can't be understood means 'never prompted about this release'."""

    LAST = T0.isoformat()

    @pytest.mark.parametrize("prompts", [
        {"version": "v0.2.0", "count": 1},                                   # no 'last'
        {"version": "v0.2.0", "count": 1, "last": "yesterday"},              # not a date
        {"version": "v0.2.0", "count": 1, "last": 12345},                    # not a string
        {"version": "v0.2.0", "count": 1, "last": None},
        {"version": "v0.2.0", "last": LAST},                                 # no 'count'
        {"version": "v0.2.0", "count": "2", "last": LAST},                   # text count
        {"version": "v0.2.0", "count": 1.5, "last": LAST},
        {"version": "v0.2.0", "count": True, "last": LAST},
        {"version": "v0.2.0", "count": 0, "last": LAST},
        {"version": "v0.2.0", "count": -3, "last": LAST},
        {"version": "v0.2.0", "count": None, "last": LAST},
    ])
    def test_a_record_that_makes_no_sense_means_prompt_again_and_never_raises(self, prompts):
        assert should_prompt({"update_prompts": prompts}, "v0.2.0", after(0.1))

    @pytest.mark.parametrize("prompts", ["a string", 7, ["a", "list"], None])
    def test_a_record_that_is_not_even_a_mapping_means_prompt_again(self, prompts):
        assert should_prompt({"update_prompts": prompts}, "v0.2.0", T0)

    def test_a_date_without_a_timezone_is_read_as_utc(self):
        naive = {"update_prompts": {"version": "v0.2.0", "count": 1, "last": "2026-11-13T09:00:00"}}

        assert not should_prompt(naive, "v0.2.0", after(1.9))
        assert should_prompt(naive, "v0.2.0", after(2))

    def test_a_huge_count_with_a_garbled_date_still_means_forget_that_release(self):
        forgotten = {"update_prompts": {"version": "v0.2.0", "count": 3, "last": "garbled"}}

        assert not should_prompt(forgotten, "v0.2.0", after(365))

    @pytest.mark.parametrize("prompts", [
        {"version": "v0.2.0", "count": "2", "last": LAST},
        {"version": "v0.2.0", "count": None},
        "nonsense",
    ])
    def test_recording_over_a_damaged_record_starts_it_again_at_one(self, prompts):
        recorded = record_prompt({"update_prompts": prompts}, "v0.2.0", after(5))

        assert recorded["update_prompts"] == {"version": "v0.2.0", "count": 1, "last": after(5).isoformat()}


def test_a_failed_replace_when_saving_state_leaves_no_temp_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "nestcal.state.json"
    monkeypatch.setattr(nestcal_update, "STATE_PATH", path)

    def refuse(src, dst):
        raise PermissionError("the file is in use")
    monkeypatch.setattr(nestcal_update.os, "replace", refuse)

    save_state({"x": 1}, Logger(True))

    assert list(tmp_path.iterdir()) == []
    assert "could not save" in capsys.readouterr().err
