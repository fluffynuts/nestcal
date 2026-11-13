import os
import sys

import pytest

import nestcal_core
from nestcal_core import Logger, get_feeds, load_config, read_config, save_calendars

A = "https://example.com/a.ics"
B = "https://example.com/b.ics"
C = "https://example.com/c.ics"


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / ".config" / "nestcal.ini"
    path.parent.mkdir()
    monkeypatch.setattr(nestcal_core, "CONFIG_PATH", path)
    return path


def saved_calendars():
    return [(f.label, f.url) for f in get_feeds(read_config(), Logger(False))]


def test_replaces_the_calendars_and_leaves_everything_else_byte_for_byte(config_path):
    config_path.write_text(
        "# my notes\n[settings]\n# how long\nlead_minutes = 7\n\n"
        "[calendars]\nwork = " + A + "\nhome = " + B + "\n")

    save_calendars([("work", A), ("play", C)])

    assert config_path.read_text() == (
        "# my notes\n[settings]\n# how long\nlead_minutes = 7\n\n"
        "[calendars]\nwork = " + A + "\nplay = " + C + "\n")


def test_comments_and_blank_lines_inside_the_calendars_section_stay_put(config_path):
    config_path.write_text(
        "[calendars]\n# secrets below\nwork = " + A + "\n\n# the other one\nhome = " + B + "\n")

    save_calendars([("work", A), ("home", C)])

    assert config_path.read_text() == (
        "[calendars]\n# secrets below\nwork = " + A + "\nhome = " + C + "\n\n# the other one\n")


def test_a_section_after_calendars_is_not_touched(config_path):
    config_path.write_text("[calendars]\nwork = " + A + "\n\n[other]\nkeep = me\n")

    save_calendars([("home", B)])

    assert config_path.read_text() == "[calendars]\nhome = " + B + "\n\n[other]\nkeep = me\n"


def test_removing_every_calendar_keeps_the_section_and_its_comments(config_path):
    config_path.write_text("[calendars]\n# example = x\nwork = " + A + "\n\n[settings]\n")

    save_calendars([])

    assert config_path.read_text() == "[calendars]\n# example = x\n\n[settings]\n"
    assert saved_calendars() == []


def test_adding_to_a_section_with_only_comments_puts_entries_after_them(config_path):
    config_path.write_text("[calendars]\n# personal = https://example.com/x.ics\n")

    save_calendars([("work", A)])

    assert config_path.read_text() == "[calendars]\n# personal = https://example.com/x.ics\nwork = " + A + "\n"


def test_a_missing_calendars_section_is_appended(config_path):
    config_path.write_text("[settings]\nlead_minutes = 7")

    save_calendars([("work", A)])

    assert config_path.read_text() == "[settings]\nlead_minutes = 7\n\n[calendars]\nwork = " + A + "\n"


def test_a_missing_file_is_created(config_path):
    save_calendars([("work", A)])

    assert saved_calendars() == [("work", A)]


def test_urls_are_normalised_and_names_trimmed(config_path):
    save_calendars([(" work ", "webcal://example.com/a.ics")])

    assert saved_calendars() == [("work", "https://example.com/a.ics")]


def test_an_invalid_calendar_is_refused_and_the_file_is_left_alone(config_path):
    config_path.write_text("[calendars]\nwork = " + A + "\n")

    with pytest.raises(ValueError):
        save_calendars([("work", A), ("bad", "nonsense")])

    assert config_path.read_text() == "[calendars]\nwork = " + A + "\n"


def test_duplicate_names_are_refused_because_the_file_could_not_be_read_back(config_path):
    with pytest.raises(ValueError, match="work"):
        save_calendars([("work", A), ("work", B)])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_the_saved_file_is_private_because_the_urls_are_secrets(config_path):
    save_calendars([("work", A)])

    assert config_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_symlinked_config_stays_a_symlink_and_the_target_is_updated(config_path, tmp_path):
    target = tmp_path / "dotfiles" / "nestcal.ini"
    target.parent.mkdir()
    target.write_text("[calendars]\nwork = " + A + "\n")
    os.symlink(target, config_path)

    save_calendars([("home", B)])

    assert config_path.is_symlink()
    assert target.read_text() == "[calendars]\nhome = " + B + "\n"


class TestReadConfig:
    def test_reads_the_file(self, config_path):
        config_path.write_text("[calendars]\nWork = " + A + "\n")

        assert saved_calendars() == [("Work", A)]

    def test_a_missing_file_is_an_error_rather_than_an_empty_config(self, config_path):
        with pytest.raises(OSError):
            read_config()

    def test_a_malformed_file_is_an_error(self, config_path):
        config_path.write_text("this is not an ini file\n")

        import configparser
        with pytest.raises(configparser.Error):
            read_config()


def test_a_failed_replace_raises_and_leaves_no_temp_file_with_the_urls_in_it(config_path, monkeypatch):
    config_path.write_text("[calendars]\nwork = " + A + "\n")

    def refuse(src, dst):
        raise PermissionError("the file is in use")
    monkeypatch.setattr(nestcal_core.os, "replace", refuse)

    with pytest.raises(PermissionError):
        save_calendars([("work", A), ("home", B)])

    assert sorted(p.name for p in config_path.parent.iterdir()) == ["nestcal.ini"]
    assert config_path.read_text() == "[calendars]\nwork = " + A + "\n"
