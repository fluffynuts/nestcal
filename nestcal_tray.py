#!/usr/bin/env python3
"""
nestcal_tray - a system-tray meeting reminder for ICS calendar feeds.

Polls the configured ICS feeds (see nestcal_core / ~/.config/nestcal/config.ini) and,
a configurable lead time before each meeting starts, pops a bespoke window that
stays on top and does NOT auto-dismiss (unlike a system notification). The
window shows the title, the start-end time range, and the meeting link
(Google Meet / Zoom / Teams) with a Join button.

Wayland note: an app's stay-on-top hint is advisory and KWin on Wayland may
ignore it. For guaranteed keep-above there, add a KWin Window Rule matching
window class "nestcal" (or title prefix "Meeting:") -> Keep above: Force, Yes.
On X11 the hint is honoured directly.
"""

import configparser
import os
import sys
import threading
from datetime import datetime, timedelta, timezone

from nestcal_qt import (
    PYQT, QAction, QApplication, QColor, QDesktopServices, QFont, QHBoxLayout, QIcon, QLabel,
    QMenu, QMessageBox, QObject, QPainter, QPixmap, QPushButton, QSystemTrayIcon, QThread,
    QTimer, QUrl, QVBoxLayout, QWidget, Qt, pyqtSignal,
)
import nestcal_core
from nestcal_calendar_dialog import SetupDialog
from nestcal_config_watch import ConfigWatcher
from nestcal_core import (
    Logger, load_config, migrate_legacy_config, read_config, get_feeds, parse_settings, Settings, collect_upcoming,
    is_due_or_running, prune_seen, format_time_range,
    format_countdown, Occurrence,
)
from nestcal_update import (
    RELEASES_URL, fetch_latest_version, is_newer, load_state, parse_version, record_prompt,
    save_state, should_prompt,
)
from nestcal_version import VERSION
from nestcal_window import MainWindow

# Keep notified-keys for events whose start is within the last day; older ones
# can't reappear in the window or still be running, so they're safe to forget.
SEEN_RETENTION_SECONDS = 24 * 60 * 60
UPDATE_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000

# --- Enum compatibility (scoped in PyQt6, flat in PyQt5) ---

if PYQT == 6:
    STAY_ON_TOP = Qt.WindowType.WindowStaysOnTopHint
    TEXT_BROWSER = Qt.TextInteractionFlag.TextBrowserInteraction
    TRAY_CLICKS = (QSystemTrayIcon.ActivationReason.Trigger,
                   QSystemTrayIcon.ActivationReason.DoubleClick)
    WA_DELETE_ON_CLOSE = Qt.WidgetAttribute.WA_DeleteOnClose
    ACCEPT_ROLE = QMessageBox.ButtonRole.AcceptRole
    REJECT_ROLE = QMessageBox.ButtonRole.RejectRole
else:
    STAY_ON_TOP = Qt.WindowStaysOnTopHint
    TEXT_BROWSER = Qt.TextBrowserInteraction
    TRAY_CLICKS = (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
    WA_DELETE_ON_CLOSE = Qt.WA_DeleteOnClose
    ACCEPT_ROLE = QMessageBox.AcceptRole
    REJECT_ROLE = QMessageBox.RejectRole


# --- Tray icon ---

# A flat calendar glyph on a 16x16 grid of units, as (x, y, width, height): three tabs on
# top, the body outline, then a 3x2 grid of day squares plus one. Matches the common
# "appointment-soon" themed icon so the fallback looks at home beside it.
CALENDAR_GLYPH_RECTS = (
    (0, 0, 2, 3), (4, 0, 8, 3), (14, 0, 2, 3),
    (0, 3, 16, 1), (0, 3, 1, 13), (15, 3, 1, 13), (0, 15, 16, 1),
    (3, 5, 2, 2), (7, 5, 2, 2), (11, 5, 2, 2),
    (3, 8, 2, 2), (7, 8, 2, 2), (11, 8, 2, 2),
    (11, 11, 2, 2),
)
# A mid-tone green stays legible on both light and dark menu bars and panels.
CALENDAR_GLYPH_COLOR = "#04896a"


def draw_calendar_glyph(unit: int) -> QPixmap:
    pixmap = QPixmap(16 * unit, 16 * unit)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    for x, y, width, height in CALENDAR_GLYPH_RECTS:
        painter.fillRect(x * unit, y * unit, width * unit, height * unit,
                         QColor(CALENDAR_GLYPH_COLOR))
    painter.end()
    return pixmap


def make_icon() -> QIcon:
    """A themed calendar icon, or a drawn fallback if the theme lacks one."""
    for name in ("appointment-soon", "x-office-calendar", "office-calendar"):
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QIcon(draw_calendar_glyph(8))


# --- Background poller (network off the UI thread) ---

class CalendarPoller(QThread):
    """Fetches and expands all feeds every poll_interval, emitting the full
    current occurrence list. Interruptible via an Event so quit is prompt and
    'Poll now' can wake it early."""

    events_updated = pyqtSignal(list)

    def __init__(self, feeds, window_hours: float, poll_interval: int, logger: Logger):
        super().__init__()
        self.feeds = feeds
        self.window_hours = window_hours
        self.poll_interval = poll_interval
        self.logger = logger
        self._wake = threading.Event()
        self._stopping = False

    def run(self) -> None:
        while True:
            occurrences = collect_upcoming(self.feeds, self.window_hours, self.logger)
            self.events_updated.emit(occurrences)
            self._wake.wait(self.poll_interval)
            self._wake.clear()
            if self._stopping:
                return

    def poll_now(self) -> None:
        self._wake.set()

    def set_timing(self, window_hours: float, poll_interval: int) -> None:
        """Change how far ahead and how often to fetch, and fetch right away so it shows."""
        self.window_hours = window_hours
        self.poll_interval = poll_interval
        self.poll_now()

    def set_feeds(self, feeds) -> None:
        """Swap the calendars watched and poll them right away."""
        self.feeds = feeds  # one reference assignment: run() sees the old list or the new, never a mix
        self.poll_now()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()


# --- Update check ---

class UpdateChecker(QObject):
    """Asks GitHub once, off the UI thread, whether a newer release exists, and
    emits update_available(tag) if so. A daemon thread (rather than a QThread)
    so quitting mid-request can't trip over a still-running Qt thread."""

    update_available = pyqtSignal(str)

    def __init__(self, logger: Logger):
        super().__init__()
        self.logger = logger

    def start(self) -> None:
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self) -> None:
        if parse_version(VERSION) is None:
            self.logger.log(f"update check skipped: running an unstamped '{VERSION}' build")
            return
        latest = fetch_latest_version(self.logger)
        if latest is not None and is_newer(latest, VERSION):
            self.logger.log(f"newer release available: {latest} (running {VERSION})")
            self.update_available.emit(latest)


# --- The bespoke reminder window ---

class ReminderWindow(QWidget):
    """
    Always-on-top, non-auto-dismissing meeting reminder. Shows title, time
    range and meeting link. Buttons: Join (if a link exists), Snooze, Dismiss.
    """

    dismissed = pyqtSignal(object)  # emits the occurrence key when closed

    def __init__(self, occ: Occurrence, snooze_minutes: int, icon: QIcon, logger: Logger):
        super().__init__(None)
        self.occ = occ
        self.snooze_ms = max(1, snooze_minutes) * 60 * 1000
        self.logger = logger

        self.setObjectName("nestcal")  # stable class for a KWin rule on Wayland
        self.setWindowTitle(f"Meeting: {occ.summary}")
        self.setWindowIcon(icon)       # same calendar icon as the tray
        self.setWindowFlag(STAY_ON_TOP, True)
        self.setAttribute(WA_DELETE_ON_CLOSE, True)  # free window + its 1s timer on dismiss
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QLabel(occ.summary)
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setWordWrap(True)
        layout.addWidget(title)

        when_font = QFont()
        when_font.setPointSize(12)
        time_row = QHBoxLayout()
        time_row.setSpacing(8)
        when = QLabel(format_time_range(occ))
        when.setFont(when_font)
        self.countdown = QLabel()
        self.countdown.setFont(when_font)
        time_row.addWidget(when)
        time_row.addWidget(self.countdown)
        time_row.addStretch(1)
        layout.addLayout(time_row)

        if occ.link:
            link_label = QLabel(f'<a href="{occ.link}">{occ.link}</a>')
            link_label.setTextInteractionFlags(TEXT_BROWSER)
            link_label.setOpenExternalLinks(True)
            link_label.setWordWrap(True)
            layout.addWidget(link_label)
        else:
            layout.addWidget(QLabel("No meeting link"))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if occ.link:
            join = QPushButton("Join")
            join.clicked.connect(self._open_link)
            buttons.addWidget(join)
        snooze = QPushButton(f"Snooze {snooze_minutes}m")
        snooze.clicked.connect(self._snooze)
        buttons.addWidget(snooze)
        dismiss = QPushButton("Dismiss")
        dismiss.clicked.connect(self.close)
        buttons.addWidget(dismiss)
        layout.addLayout(buttons)

        # Live "(N minutes)" / "(now)" label, refreshed once a second.
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._countdown_timer.start(1000)
        self._update_countdown()

    def _update_countdown(self) -> None:
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime.now(tz=local_tz)
        self.countdown.setText(f"({format_countdown(self.occ, now)})")

    def present(self) -> None:
        """Show, centre, and pull to the front. Showing is essential; the
        positioning/raising is best-effort, so a failure there can't break the
        reminder and instead gets logged (visible with --debug)."""
        self.show()
        try:
            screen = QApplication.primaryScreen()
            if screen is not None:
                geo = self.frameGeometry()
                geo.moveCenter(screen.availableGeometry().center())
                self.move(geo.topLeft())
            self.raise_()
            self.activateWindow()
        except Exception as e:
            self.logger.log(f"present positioning failed: {e!r}")

    def _open_link(self) -> None:
        if self.occ.link:
            QDesktopServices.openUrl(QUrl(self.occ.link))
        self.close()

    def _snooze(self) -> None:
        self.logger.log(f"snoozing '{self.occ.summary}' for {self.snooze_ms // 60000}m")
        self.hide()
        QTimer.singleShot(self.snooze_ms, self.present)

    def closeEvent(self, event) -> None:
        self.dismissed.emit(self.occ.key)
        super().closeEvent(event)


# --- Application orchestration ---

class TrayApp:
    """Wires the tray icon, the poller thread, and the due-check timer."""

    def __init__(self, app: QApplication, config, logger: Logger):
        self.app = app
        self.logger = logger

        self.settings = parse_settings(config)
        self.feeds = get_feeds(config, logger)

        self.events: list[Occurrence] = []
        self.seen: set = set()        # keys we've already notified for (memory)
        self.windows: dict = {}

        self.icon = make_icon()  # one calendar icon, shared by tray and windows
        self.tray = QSystemTrayIcon(self.icon, app)
        self.tray.setToolTip("nestcal")
        self.main_window = MainWindow(self.icon)
        self.main_window.calendars_tab.set_calendars([(f.label, f.url) for f in self.feeds])
        # macOS shows the menu on any click, so the menu's "Open nestcal" is the way in there.
        self.tray.activated.connect(self._on_tray_activated)
        # Menu is rebuilt each time it's opened so the list of in-progress
        # meetings at the top is always current.
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self._rebuild_menu)
        self._rebuild_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.poller = CalendarPoller(
            self.feeds, self.settings.window_hours, self.settings.poll_interval, logger)
        self.poller.events_updated.connect(self.on_events)
        self.poller.start()

        self.config_watcher = ConfigWatcher(nestcal_core.CONFIG_PATH, logger=logger)
        self.config_watcher.changed.connect(self.on_config_changed)

        self.update_dialog = None
        self.update_checker = UpdateChecker(logger)
        self.update_checker.update_available.connect(self.on_update_available)
        # A long-running app: ask again now and then, not only at startup.
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_checker.start)
        self.clock = lambda: datetime.now(timezone.utc)
        if self.settings.check_for_updates:
            self._start_checking_for_updates()

        self.timer = QTimer()
        self.timer.timeout.connect(self.check_due)
        self.timer.start(self.settings.check_interval * 1000)
        self.main_window.preferences_tab.set_settings(self.settings)
        self.main_window.events_tab.set_window_hours(self.settings.window_hours)

    @property
    def lead(self) -> timedelta:
        return timedelta(minutes=self.settings.lead_minutes)

    @property
    def snooze_minutes(self) -> int:
        return self.settings.snooze_minutes

    def _rebuild_menu(self) -> None:
        """Repopulate the tray menu: meetings in progress OR within their lead
        window at the top (each opens its reminder when clicked, even if
        previously dismissed), then the standard actions. Rebuilt on aboutToShow
        so it's always current — this is the recovery path for a pop-up you
        dismissed early or missed."""
        self.menu.clear()
        open_action = self.menu.addAction("Open nestcal")
        open_action.triggered.connect(self.show_main_window)
        self.menu.addSeparator()
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime.now(tz=local_tz)

        current = [o for o in self.events if is_due_or_running(o, now, self.lead)]
        for occ in current:
            action = self.menu.addAction(f"{occ.summary} {format_time_range(occ)}")
            # default-arg binds this occ (avoids the late-binding loop trap)
            action.triggered.connect(lambda checked=False, o=occ: self.open_event(o))
        if current:
            self.menu.addSeparator()

        poll_action = self.menu.addAction("Poll now")
        poll_action.triggered.connect(lambda: self.poller.poll_now())
        self.menu.addSeparator()
        quit_action = self.menu.addAction("Quit")
        quit_action.triggered.connect(self.quit)

    def on_config_changed(self) -> None:
        """The config file changed on disk, by the UI or by hand. A file that can't be
        read leaves the app on the last good settings, and says so in the window."""
        try:
            config = read_config()
            settings = parse_settings(config)
        except (OSError, configparser.Error, ValueError) as e:
            self.logger.log(f"config not applied: {e}")
            self.main_window.show_config_problem(
                f"The config file couldn't be applied, so nestcal is still using the "
                f"settings from before the change: {e}")
            return
        self.main_window.show_config_problem(None)
        self.apply_settings(settings)
        feeds = get_feeds(config, self.logger)
        if [(f.label, f.url) for f in feeds] != [(f.label, f.url) for f in self.feeds]:
            self.feeds = feeds
            self.poller.set_feeds(feeds)
            self.main_window.calendars_tab.set_calendars([(f.label, f.url) for f in feeds])

    def apply_settings(self, settings: Settings) -> None:
        old = self.settings
        if settings == old:
            return
        self.settings = settings
        if settings.check_interval != old.check_interval:
            self.timer.start(settings.check_interval * 1000)
        if (settings.window_hours, settings.poll_interval) != (old.window_hours, old.poll_interval):
            self.poller.set_timing(settings.window_hours, settings.poll_interval)
        if settings.check_for_updates and not old.check_for_updates:
            self._start_checking_for_updates()
        if old.check_for_updates and not settings.check_for_updates:
            self.update_timer.stop()
            self.main_window.events_tab.show_update(None)
        self.main_window.preferences_tab.set_settings(settings)
        self.main_window.events_tab.set_window_hours(settings.window_hours)

    def _start_checking_for_updates(self) -> None:
        self.update_checker.start()
        self.update_timer.start(UPDATE_CHECK_INTERVAL_MS)

    def on_update_available(self, latest: str) -> None:
        """The link in the window is always there; the pop-up dialog is rationed, because a
        busy user who dismisses it hasn't necessarily decided against updating."""
        self.main_window.events_tab.show_update(latest)
        now = self.clock()
        state = load_state(self.logger)
        if should_prompt(state, latest, now):
            save_state(record_prompt(state, latest, now), self.logger)
            self.show_update_dialog(latest)

    def _on_tray_activated(self, reason) -> None:
        if reason in TRAY_CLICKS:
            self.show_main_window()

    def show_main_window(self) -> None:
        self.main_window.present()

    def on_events(self, occurrences: list) -> None:
        self.events = occurrences
        self.main_window.events_tab.set_events(occurrences)
        self.seen = prune_seen(self.seen, SEEN_RETENTION_SECONDS)  # keep it bounded
        upcoming = [o for o in occurrences if not o.all_day]
        if upcoming:
            nxt = upcoming[0]
            self.tray.setToolTip(
                f"nestcal - next: {nxt.summary} at {format_time_range(nxt)}")
        else:
            self.tray.setToolTip("nestcal - no upcoming events")
        self.logger.log(f"events updated: {len(occurrences)} in window")
        # Fire promptly on fresh data rather than waiting for the next tick;
        # this is also what makes the startup catch-up immediate.
        self.check_due()

    def check_due(self) -> None:
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime.now(tz=local_tz)
        # Fire any meeting in its lead window OR already in progress that we
        # haven't notified for yet. The in-memory seen-set is the "notified
        # before" memory, so restarting mid-meeting re-pops (no persistence).
        for occ in self.events:
            if occ.key in self.seen:
                continue
            if is_due_or_running(occ, now, self.lead):
                self.seen.add(occ.key)   # mark notified BEFORE showing, so a
                self.fire(occ)           # display error can't cause a re-fire loop

    def fire(self, occ: Occurrence) -> None:
        if occ.key in self.windows:
            return
        self.logger.log(f"firing reminder for '{occ.summary}'")
        self._show_window(occ)

    def open_event(self, occ: Occurrence) -> None:
        """Open (or raise) the reminder for an event on demand — e.g. from the
        tray menu — regardless of whether it's already been notified/dismissed."""
        existing = self.windows.get(occ.key)
        if existing is not None:
            existing.present()
            return
        self.logger.log(f"opening reminder for '{occ.summary}' from menu")
        self._show_window(occ)

    def _show_window(self, occ: Occurrence) -> None:
        window = ReminderWindow(occ, self.snooze_minutes, self.icon, self.logger)
        window.dismissed.connect(lambda key: self.windows.pop(key, None))
        self.windows[occ.key] = window
        window.present()

    def show_update_dialog(self, latest: str) -> None:
        dialog = QMessageBox()
        dialog.setWindowTitle("nestcal update available")
        dialog.setWindowIcon(self.icon)
        dialog.setText(f"A newer version of nestcal is available: {latest}\n"
                       f"You are running {VERSION}.")
        open_releases = dialog.addButton("Open releases page", ACCEPT_ROLE)
        dialog.addButton("Dismiss", REJECT_ROLE)
        dialog.setAttribute(WA_DELETE_ON_CLOSE, True)

        def on_clicked(button) -> None:
            if button is open_releases:
                QDesktopServices.openUrl(QUrl(RELEASES_URL))

        dialog.buttonClicked.connect(on_clicked)
        self.update_dialog = dialog  # hold a reference or it's garbage-collected
        dialog.show()

    def quit(self) -> None:
        self.logger.log("shutting down")
        self.main_window.close()
        self.poller.stop()
        self.poller.wait(2000)
        self.app.quit()


def main() -> None:
    logger = Logger("--debug" in sys.argv)
    try:
        migrate_legacy_config(logger)
    except OSError as e:
        print(f"nestcal: can't move your config from {nestcal_core.LEGACY_CONFIG_PATH} to "
              f"{nestcal_core.CONFIG_PATH}: {e}. Move it there by hand and start again.", file=sys.stderr)
        sys.exit(1)
    config = load_config(logger)
    try:
        parse_settings(config)
    except ValueError as e:
        print(f"nestcal: can't start: {e} (in ~/.config/nestcal/config.ini)", file=sys.stderr)
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("nestcal")
    app.setQuitOnLastWindowClosed(False)  # dismissing a reminder must not quit

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("nestcal: no system tray available", file=sys.stderr)

    feeds = get_feeds(config, logger)
    if not feeds and os.environ.get("NO_FIRST_TIME_SETUP") != "1":  # CI has nobody to answer the dialog
        if SetupDialog(make_icon()).exec():
            config = load_config(logger)
            feeds = get_feeds(config, logger)
    if not feeds:
        print(f"nestcal: no feeds configured; add calendars under [calendars] "
              f"in ~/.config/nestcal/config.ini", file=sys.stderr)
        sys.exit(1)

    TrayApp(app, config, logger)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
