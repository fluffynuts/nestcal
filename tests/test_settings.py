import configparser

import pytest

import nestcal_core
from nestcal_core import Settings, parse_settings, read_config, save_settings


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "nestcal.ini"
    monkeypatch.setattr(nestcal_core, "CONFIG_PATH", path)
    return path


def config_from(text: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(text)
    return config


class TestParseSettings:
    def test_an_empty_config_gives_the_defaults(self):
        assert parse_settings(config_from("")) == Settings(
            poll_interval=300, lead_minutes=2, window_hours=24, snooze_minutes=1,
            check_interval=5, check_for_updates=True)

    def test_values_in_the_file_win(self):
        settings = parse_settings(config_from(
            "[settings]\npoll_interval = 60\nlead_minutes = 1.5\nwindow_hours = 48\n"
            "snooze_minutes = 3\ncheck_interval = 2\ncheck_for_updates = no\n"))

        assert settings == Settings(60, 1.5, 48, 3, 2, False)

    @pytest.mark.parametrize("key,value,fragment", [
        ("poll_interval", "abc", "poll_interval must be a whole number"),
        ("poll_interval", "1.5", "poll_interval must be a whole number"),
        ("poll_interval", "0", "poll_interval must be at least 1"),
        ("lead_minutes", "soon", "lead_minutes must be a number"),
        ("lead_minutes", "-1", "lead_minutes must be at least 0"),
        ("window_hours", "0", "window_hours must be more than 0"),
        ("snooze_minutes", "0", "snooze_minutes must be at least 1"),
        ("check_interval", "", "check_interval must be a whole number"),
        ("check_for_updates", "maybe", "check_for_updates must be true or false"),
    ])
    def test_a_value_that_makes_no_sense_is_refused_with_a_message_naming_it(self, key, value, fragment):
        with pytest.raises(ValueError, match=fragment):
            parse_settings(config_from(f"[settings]\n{key} = {value}\n"))


class TestSaveSettings:
    def test_changes_only_the_named_values_in_place_keeping_comments(self, config_path):
        config_path.write_text(
            "# top\n[settings]\n# how often\npoll_interval = 300\nlead_minutes = 2\n\n"
            "[calendars]\nwork = https://example.com/a.ics\n")

        save_settings({"lead_minutes": "5"})

        assert config_path.read_text() == (
            "# top\n[settings]\n# how often\npoll_interval = 300\nlead_minutes = 5\n\n"
            "[calendars]\nwork = https://example.com/a.ics\n")

    def test_a_setting_missing_from_the_file_is_added_to_the_section(self, config_path):
        config_path.write_text("[settings]\nlead_minutes = 2\n\n[calendars]\n")

        save_settings({"check_for_updates": "false"})

        assert config_path.read_text() == "[settings]\nlead_minutes = 2\ncheck_for_updates = false\n\n[calendars]\n"
        assert parse_settings(read_config()).check_for_updates is False

    def test_a_missing_settings_section_is_added_and_calendars_are_untouched(self, config_path):
        config_path.write_text("[calendars]\nwork = https://example.com/a.ics\n")

        save_settings({"lead_minutes": "5"})

        assert read_config()["settings"]["lead_minutes"] == "5"
        assert read_config()["calendars"]["work"] == "https://example.com/a.ics"

    def test_a_missing_file_is_created(self, config_path):
        save_settings({"lead_minutes": "5"})

        assert parse_settings(read_config()).lead_minutes == 5

    def test_a_value_that_would_not_read_back_is_refused_and_the_file_left_alone(self, config_path):
        config_path.write_text("[settings]\nlead_minutes = 2\n")

        with pytest.raises(ValueError, match="lead_minutes"):
            save_settings({"lead_minutes": "soon"})

        assert config_path.read_text() == "[settings]\nlead_minutes = 2\n"

    def test_an_unknown_setting_is_refused(self, config_path):
        with pytest.raises(ValueError, match="nonsense"):
            save_settings({"nonsense": "1"})

    def test_a_calendars_entry_with_a_settings_looking_name_is_not_mistaken_for_a_setting(self, config_path):
        config_path.write_text("[calendars]\nlead_minutes = https://example.com/a.ics\n")

        save_settings({"lead_minutes": "5"})

        assert read_config()["calendars"]["lead_minutes"] == "https://example.com/a.ics"
        assert read_config()["settings"]["lead_minutes"] == "5"
