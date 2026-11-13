import pytest

import nestcal_core
from nestcal_core import Settings, parse_settings, read_config
from nestcal_preferences_tab import PreferencesTab

FILE = "[settings]\n# how often\npoll_interval = 300\nlead_minutes = 2\nwindow_hours = 24\nsnooze_minutes = 1\ncheck_interval = 5\n\n[calendars]\nwork = https://example.com/a.ics\n"


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "nestcal.ini"
    path.write_text(FILE)
    monkeypatch.setattr(nestcal_core, "CONFIG_PATH", path)
    return path


@pytest.fixture
def tab(qtbot, config_path):
    tab = PreferencesTab()
    qtbot.addWidget(tab)
    tab.set_settings(parse_settings(read_config()))
    tab.show()
    return tab


def test_the_fields_show_what_the_file_says(tab):
    assert {key: spin.value() for key, spin in tab.spins.items()} == {
        "lead_minutes": 2, "snooze_minutes": 1, "poll_interval": 300, "window_hours": 24, "check_interval": 5}
    assert tab.updates_checkbox.isChecked()  # on unless the file says otherwise


def test_update_checking_is_off_when_the_file_says_so(tab):
    tab.set_settings(Settings(300, 2, 24, 1, 5, check_for_updates=False))

    assert not tab.updates_checkbox.isChecked()


def test_save_and_revert_are_disabled_until_something_is_edited(tab):
    assert not tab.save_button.isEnabled()
    assert not tab.revert_button.isEnabled()

    tab.spins["lead_minutes"].setValue(5)

    assert tab.save_button.isEnabled()
    assert tab.revert_button.isEnabled()


def test_editing_a_field_back_to_its_original_value_is_not_an_edit(tab):
    tab.spins["lead_minutes"].setValue(5)
    tab.spins["lead_minutes"].setValue(2)

    assert not tab.save_button.isEnabled()


def test_nothing_is_written_until_save_is_pressed(tab, config_path):
    tab.spins["lead_minutes"].setValue(5)

    assert config_path.read_text() == FILE


def test_save_writes_only_what_changed_and_keeps_the_comments(tab, config_path):
    tab.spins["lead_minutes"].setValue(5)
    tab.updates_checkbox.setChecked(False)

    tab.save_button.click()

    saved = config_path.read_text()
    assert "lead_minutes = 5\n" in saved
    assert "check_for_updates = false\n" in saved
    assert "# how often\npoll_interval = 300\n" in saved
    assert "poll_interval = 300\nlead_minutes = 5\nwindow_hours = 24" in saved
    assert parse_settings(read_config()).check_for_updates is False
    assert not tab.save_button.isEnabled()


def test_revert_puts_the_file_values_back_and_writes_nothing(tab, config_path):
    tab.spins["lead_minutes"].setValue(5)
    tab.spins["snooze_minutes"].setValue(9)
    tab.updates_checkbox.setChecked(False)

    tab.revert_button.click()

    assert tab.spins["lead_minutes"].value() == 2
    assert tab.spins["snooze_minutes"].value() == 1
    assert tab.updates_checkbox.isChecked()
    assert not tab.save_button.isEnabled()
    assert config_path.read_text() == FILE


def test_a_hand_edited_value_the_screen_cant_show_is_left_alone_unless_edited(tab, config_path):
    config_path.write_text(FILE.replace("poll_interval = 300", "poll_interval = 5"))  # below the screen's minimum
    tab.set_settings(parse_settings(read_config()))
    assert not tab.save_button.isEnabled()  # clamped on screen, but not an edit

    tab.spins["lead_minutes"].setValue(4)
    tab.save_button.click()

    assert "poll_interval = 5\n" in config_path.read_text()


def test_a_file_change_updates_untouched_fields_and_keeps_edited_ones(tab):
    tab.spins["lead_minutes"].setValue(7)  # being edited

    tab.set_settings(Settings(poll_interval=600, lead_minutes=3, window_hours=24,
                              snooze_minutes=1, check_interval=5, check_for_updates=True))

    assert tab.spins["poll_interval"].value() == 600   # followed the file
    assert tab.spins["lead_minutes"].value() == 7      # kept the edit
    assert tab.save_button.isEnabled()
    tab.revert_button.click()
    assert tab.spins["lead_minutes"].value() == 3      # revert goes to the file as it is now


def test_a_failed_save_says_so_and_keeps_the_edit(tab, monkeypatch):
    def refuse(values):
        raise PermissionError("read-only file system")
    monkeypatch.setattr("nestcal_preferences_tab.save_settings", refuse)
    tab.spins["lead_minutes"].setValue(5)

    tab.save_button.click()

    assert "read-only file system" in tab.error_label.text()
    assert tab.spins["lead_minutes"].value() == 5
    assert tab.save_button.isEnabled()


def test_units_are_singular_for_one(tab):
    assert tab.spins["snooze_minutes"].suffix() == " minute"
    assert tab.spins["lead_minutes"].suffix() == " minutes before a meeting starts"

    tab.spins["lead_minutes"].setValue(1)
    assert tab.spins["lead_minutes"].suffix() == " minute before a meeting starts"
    tab.spins["snooze_minutes"].setValue(2)
    assert tab.spins["snooze_minutes"].suffix() == " minutes"
