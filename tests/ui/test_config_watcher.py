"""ConfigWatcher against a real folder: it must announce changes to the config file, and only those."""
import os

import pytest

from nestcal_config_watch import ConfigWatcher


class Watched:
    def __init__(self, qtbot, folder):
        self.qtbot = qtbot
        self.folder = folder
        self.ini = folder / "config.ini"
        self.ini.write_text("[settings]\nlead_minutes = 2\n")
        self.watcher = ConfigWatcher(self.ini, settle_ms=20)
        self.announced = []
        self.watcher.changed.connect(lambda: self.announced.append(
            self.ini.read_text() if self.ini.exists() else None))

    def settle_after(self, action):
        """Do something to the folder and wait until the watcher has noticed and settled."""
        with self.qtbot.waitSignal(self.watcher._settle.timeout, timeout=10_000):
            action()


@pytest.fixture
def watched(qtbot, tmp_path):
    return Watched(qtbot, tmp_path)


def test_a_changed_config_is_announced_once(watched):
    watched.settle_after(lambda: watched.ini.write_text("[settings]\nlead_minutes = 5\n"))

    assert watched.announced == ["[settings]\nlead_minutes = 5\n"]


def test_an_unrelated_file_in_the_same_folder_is_not_announced(watched):
    watched.settle_after(lambda: (watched.folder / "state.json").write_text("{}"))

    assert watched.announced == []


def test_saving_identical_content_is_not_announced(watched):
    watched.settle_after(lambda: watched.ini.write_text(watched.ini.read_text()))

    assert watched.announced == []


def test_replacing_the_file_as_an_editor_does_is_announced_and_the_next_replacement_too(watched):
    for lead in ("5", "6"):
        def replace():
            new = watched.folder / "config.ini.new"
            new.write_text(f"[settings]\nlead_minutes = {lead}\n")
            os.replace(new, watched.ini)
        watched.settle_after(replace)

    assert watched.announced == ["[settings]\nlead_minutes = 5\n", "[settings]\nlead_minutes = 6\n"]


def test_replacing_the_file_with_identical_content_is_not_announced(watched):
    def replace():
        new = watched.folder / "config.ini.new"
        new.write_text(watched.ini.read_text())
        os.replace(new, watched.ini)

    watched.settle_after(replace)

    assert watched.announced == []


def test_a_burst_of_writes_is_announced_once_with_the_final_content(watched):
    def burst():
        for lead in ("3", "4", "5"):
            watched.ini.write_text(f"[settings]\nlead_minutes = {lead}\n")

    watched.settle_after(burst)

    assert watched.announced == ["[settings]\nlead_minutes = 5\n"]


def test_a_deleted_file_is_announced_and_so_is_its_return(watched):
    watched.settle_after(lambda: watched.ini.unlink())
    watched.settle_after(lambda: watched.ini.write_text("[settings]\nlead_minutes = 9\n"))

    assert watched.announced == [None, "[settings]\nlead_minutes = 9\n"]
