import pytest

import nestcal_core
import nestcal_tray
from nestcal_core import Logger, get_feeds, load_config

URL = "https://example.com/a.ics"


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / ".config" / "nestcal" / "config.ini"
    monkeypatch.setattr(nestcal_core, "CONFIG_PATH", path)
    return path


@pytest.fixture
def dialog(qtbot, config_path):
    dialog = nestcal_tray.SetupDialog(nestcal_tray.make_icon())
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def test_saving_a_name_and_link_writes_the_calendar_and_accepts(dialog, config_path):
    dialog.name_edit.setText("work")
    dialog.url_edit.setText(URL)

    dialog.save_button.click()

    assert dialog.result() == 1  # QDialog.Accepted
    feeds = get_feeds(load_config(Logger(False)), Logger(False))
    assert [(f.label, f.url) for f in feeds] == [("work", URL)]


@pytest.mark.parametrize("name,url,message", [
    ("", URL, "name"),
    ("work", "", "link"),
    ("work", "nonsense", "https://"),
])
def test_bad_input_shows_a_message_and_keeps_the_dialog_open(dialog, config_path, name, url, message):
    dialog.name_edit.setText(name)
    dialog.url_edit.setText(url)

    dialog.save_button.click()

    assert dialog.isVisible()
    assert message in dialog.error_label.text()
    assert not config_path.exists()


def test_cancel_closes_without_writing_a_calendar(dialog, config_path):
    cancel = next(b for b in dialog.findChildren(nestcal_tray.QPushButton) if b.text() == "Cancel")

    cancel.click()

    assert not dialog.isVisible()
    assert not config_path.exists()


@pytest.fixture
def run_main(qapp, config_path, monkeypatch):
    """Runs the real main() against the existing QApplication; returns its exit code."""
    monkeypatch.setattr(nestcal_tray, "QApplication", lambda argv: qapp)
    monkeypatch.setattr(nestcal_tray.sys, "argv", ["nestcal"])

    def run() -> int:
        with pytest.raises(SystemExit) as exit_info:
            nestcal_tray.main()
        return exit_info.value.code
    return run


def test_first_time_setup_can_be_disabled_for_unattended_runs(run_main, monkeypatch, capsys):
    monkeypatch.setenv("NO_FIRST_TIME_SETUP", "1")
    monkeypatch.setattr(nestcal_tray.SetupDialog, "exec",
                        lambda self: pytest.fail("the setup dialog was shown"))

    assert run_main() == 1
    assert "no feeds configured" in capsys.readouterr().err


def test_without_the_variable_main_offers_the_setup_dialog(run_main, monkeypatch, capsys):
    monkeypatch.delenv("NO_FIRST_TIME_SETUP", raising=False)
    shown = []
    monkeypatch.setattr(nestcal_tray.SetupDialog, "exec", lambda self: shown.append(True) or 0)

    assert run_main() == 1
    assert shown == [True]


def test_main_refuses_to_start_on_an_unusable_setting_and_says_which(run_main, config_path, monkeypatch, capsys):
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[settings]\npoll_interval = lots\n[calendars]\nwork = https://example.com/a.ics\n")
    monkeypatch.setattr(nestcal_tray, "TrayApp", lambda *a: pytest.fail("the app was started"))

    assert run_main() == 1
    assert "poll_interval must be a whole number, not 'lots'" in capsys.readouterr().err


@pytest.fixture
def legacy_config_path(config_path, monkeypatch):
    legacy = config_path.parent.parent / "nestcal.ini"  # ~/.config/nestcal.ini
    monkeypatch.setattr(nestcal_core, "LEGACY_CONFIG_PATH", legacy)
    return legacy


def test_main_moves_an_old_config_before_it_reads_the_config(run_main, config_path, legacy_config_path,
                                                             monkeypatch, capsys):
    monkeypatch.setenv("NO_FIRST_TIME_SETUP", "1")
    legacy_config_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_config_path.write_text("[calendars]\n")

    assert run_main() == 1  # no calendars in it: the point is that it was found, and moved
    assert config_path.read_text() == "[calendars]\n"
    assert not legacy_config_path.exists()


def test_main_refuses_to_start_and_says_so_if_the_old_config_cannot_be_moved(
        run_main, config_path, legacy_config_path, monkeypatch, capsys):
    def refuse(logger):
        raise PermissionError("read-only folder")
    monkeypatch.setattr(nestcal_tray, "migrate_legacy_config", refuse)

    assert run_main() == 1
    err = capsys.readouterr().err
    assert "read-only folder" in err and "nestcal.ini" in err and "config.ini" in err
