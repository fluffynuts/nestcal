"""~/.config/nestcal.ini moved to ~/.config/nestcal/config.ini, so the folder holds only nestcal's files."""
import os
import sys

import pytest

import nestcal_core
from nestcal_core import Logger, migrate_legacy_config

CONTENT = "# mine\n[settings]\nlead_minutes = 7\n\n[calendars]\nwork = https://example.com/a.ics\n"


@pytest.fixture
def paths(tmp_path, monkeypatch):
    home = tmp_path / ".config"
    home.mkdir()
    legacy, new = home / "nestcal.ini", home / "nestcal" / "config.ini"
    monkeypatch.setattr(nestcal_core, "LEGACY_CONFIG_PATH", legacy)
    monkeypatch.setattr(nestcal_core, "CONFIG_PATH", new)
    return legacy, new


def test_the_new_location_is_a_folder_of_nestcals_own():
    assert nestcal_core.CONFIG_PATH.parts[-2:] == ("nestcal", "config.ini")
    assert nestcal_core.LEGACY_CONFIG_PATH.name == "nestcal.ini"
    assert nestcal_core.LEGACY_CONFIG_PATH.parent == nestcal_core.CONFIG_PATH.parent.parent


def test_an_existing_config_is_moved_not_copied_with_its_content_intact(paths):
    legacy, new = paths
    legacy.write_text(CONTENT)

    migrate_legacy_config(Logger(False))

    assert new.read_text() == CONTENT
    assert not legacy.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_the_moved_config_stays_private(paths):
    legacy, new = paths
    legacy.write_text(CONTENT)
    os.chmod(legacy, 0o600)

    migrate_legacy_config(Logger(False))

    assert new.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_symlinked_config_stays_a_symlink_to_the_same_file(paths, tmp_path):
    legacy, new = paths
    target = tmp_path / "dotfiles" / "nestcal.ini"
    target.parent.mkdir()
    target.write_text(CONTENT)
    os.symlink(os.path.relpath(target, legacy.parent), legacy)  # a relative link, as dotfiles often are

    migrate_legacy_config(Logger(False))

    assert new.is_symlink() and new.resolve() == target.resolve()
    assert new.read_text() == CONTENT
    assert not legacy.exists() and not legacy.is_symlink()
    assert target.read_text() == CONTENT


def test_nothing_to_migrate_creates_nothing(paths):
    legacy, new = paths

    migrate_legacy_config(Logger(False))

    assert not new.exists() and not new.parent.exists()


def test_a_config_already_at_the_new_location_is_left_alone(paths):
    legacy, new = paths
    new.parent.mkdir()
    new.write_text(CONTENT)

    migrate_legacy_config(Logger(False))

    assert new.read_text() == CONTENT


def test_with_a_config_in_both_places_neither_is_touched_and_the_old_one_is_flagged(paths, capsys):
    legacy, new = paths
    new.parent.mkdir()
    new.write_text(CONTENT)
    legacy.write_text("[calendars]\nold = https://example.com/old.ics\n")

    migrate_legacy_config(Logger(False))

    assert new.read_text() == CONTENT
    assert legacy.read_text() == "[calendars]\nold = https://example.com/old.ics\n"
    err = capsys.readouterr().err
    assert str(legacy) in err and str(new) in err and "ignor" in err


def test_migrating_twice_is_the_same_as_once(paths):
    legacy, new = paths
    legacy.write_text(CONTENT)

    migrate_legacy_config(Logger(False))
    migrate_legacy_config(Logger(False))

    assert new.read_text() == CONTENT and not legacy.exists()


def test_a_move_that_fails_raises_and_leaves_the_old_config_where_it_was(paths, monkeypatch):
    legacy, new = paths
    legacy.write_text(CONTENT)

    def refuse(src, dst):
        raise PermissionError("read-only folder")
    monkeypatch.setattr(nestcal_core.shutil, "move", refuse)

    with pytest.raises(PermissionError):
        migrate_legacy_config(Logger(False))

    assert legacy.read_text() == CONTENT
