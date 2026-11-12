import pytest

import nestcal_core
import nestcal_tray
from nestcal_core import Logger, get_feeds, load_config

URL = "https://example.com/a.ics"


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / ".config" / "nestcal.ini"
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
