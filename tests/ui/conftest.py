import configparser

import pytest

import nestcal_tray
from feed_server import FeedServer
from nestcal_core import Logger


@pytest.fixture
def feed_server(monkeypatch):
    # requests honours proxy variables from the environment; the fake feed is local.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    server = FeedServer().start()
    yield server
    server.stop()


@pytest.fixture
def opened_urls(monkeypatch):
    """Records what the app asks the OS to open, instead of launching a browser."""
    urls = []
    monkeypatch.setattr(nestcal_tray.QDesktopServices, "openUrl",
                        lambda url: urls.append(url.toString()) or True)
    return urls


class RunningApp:
    def __init__(self, tray_app, polls, qtbot):
        self.tray_app = tray_app
        self._polls = polls
        self._qtbot = qtbot

    def wait_for_polls(self, count: int) -> None:
        """Wait until the app has fully processed `count` feed polls in total."""
        self._qtbot.waitUntil(lambda: len(self._polls) >= count, timeout=10_000)

    @property
    def windows(self) -> dict:
        return self.tray_app.windows

    @property
    def tooltip(self) -> str:
        return self.tray_app.tray.toolTip()

    def open_menu(self):
        """What happens when the user clicks the tray icon."""
        self.tray_app.menu.aboutToShow.emit()
        return self.tray_app.menu.actions()

    def menu_texts(self) -> list[str]:
        return ["---" if a.isSeparator() else a.text() for a in self.open_menu()]


@pytest.fixture
def start_app(qapp, qtbot, feed_server, monkeypatch):
    """Starts the real TrayApp against the fake feed and waits for nothing: tests
    call wait_for_polls themselves. Cleans up the poller thread and windows."""
    monkeypatch.setattr(nestcal_tray, "VERSION", "dev")  # never reach out to GitHub
    polls = []
    original_on_events = nestcal_tray.TrayApp.on_events

    def recording_on_events(self, occurrences):
        original_on_events(self, occurrences)
        polls.append(len(occurrences))

    monkeypatch.setattr(nestcal_tray.TrayApp, "on_events", recording_on_events)
    started = []

    def start(**settings) -> RunningApp:
        config = configparser.ConfigParser()
        config["settings"] = {"poll_interval": "300", "lead_minutes": "2", "window_hours": "24",
                              "snooze_minutes": "1", "check_interval": "1",
                              **{k: str(v) for k, v in settings.items()}}
        config["calendars"] = {"work": feed_server.url}
        tray_app = nestcal_tray.TrayApp(qapp, config, Logger(False))
        started.append(tray_app)
        return RunningApp(tray_app, polls, qtbot)

    yield start

    for tray_app in started:
        tray_app.timer.stop()
        tray_app.poller.stop()
        tray_app.poller.wait(5000)
        # The poller may have queued a final result; deliver it while the app is still
        # alive, or the next test's event loop would deliver it to a torn-down app.
        qapp.processEvents()
        for window in list(tray_app.windows.values()):
            window.close()
        if tray_app.update_dialog is not None:
            try:
                tray_app.update_dialog.close()
            except RuntimeError:
                pass  # a button already closed it, and it deletes itself on close
        tray_app.tray.hide()
        qapp.processEvents()
