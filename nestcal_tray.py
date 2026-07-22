#!/usr/bin/env python3
"""
nestcal_tray - a system-tray meeting reminder for ICS calendar feeds.

Polls the configured ICS feeds (see nestcal_core / ~/.config/nestcal.ini) and,
a configurable lead time before each meeting starts, pops a bespoke window that
stays on top and does NOT auto-dismiss (unlike a system notification). The
window shows the title, the start-end time range, and the meeting link
(Google Meet / Zoom / Teams) with a Join button.

Wayland note: an app's stay-on-top hint is advisory and KWin on Wayland may
ignore it. For guaranteed keep-above there, add a KWin Window Rule matching
window class "nestcal" (or title prefix "Meeting:") -> Keep above: Force, Yes.
On X11 the hint is honoured directly.
"""

import sys
import threading
from datetime import datetime, timedelta

# --- Qt import with PyQt6 -> PyQt5 fallback (mirrors Nestray) ---

try:
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
        QSystemTrayIcon, QMenu,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
    from PyQt6.QtGui import QIcon, QAction, QDesktopServices, QPixmap, QPainter, QColor, QFont
    PYQT = 6
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
        QSystemTrayIcon, QMenu, QAction,
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
    from PyQt5.QtGui import QIcon, QDesktopServices, QPixmap, QPainter, QColor, QFont
    PYQT = 5

from nestcal_core import (
    Logger, load_config, get_feeds, get_setting, collect_upcoming,
    is_due_or_running, prune_seen, format_time_range,
    format_countdown, Occurrence,
)

# Keep notified-keys for events whose start is within the last day; older ones
# can't reappear in the window or still be running, so they're safe to forget.
SEEN_RETENTION_SECONDS = 24 * 60 * 60

# --- Enum compatibility (scoped in PyQt6, flat in PyQt5) ---

if PYQT == 6:
    STAY_ON_TOP = Qt.WindowType.WindowStaysOnTopHint
    ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
    TEXT_BROWSER = Qt.TextInteractionFlag.TextBrowserInteraction
    TRAY_TRIGGER = QSystemTrayIcon.ActivationReason.Trigger
    WA_DELETE_ON_CLOSE = Qt.WidgetAttribute.WA_DeleteOnClose
else:
    STAY_ON_TOP = Qt.WindowStaysOnTopHint
    ALIGN_CENTER = Qt.AlignCenter
    TEXT_BROWSER = Qt.TextBrowserInteraction
    TRAY_TRIGGER = QSystemTrayIcon.Trigger
    WA_DELETE_ON_CLOSE = Qt.WA_DeleteOnClose


# --- Tray icon ---

def make_icon() -> QIcon:
    """A themed calendar icon, or a drawn fallback if the theme lacks one."""
    for name in ("appointment-soon", "x-office-calendar", "office-calendar"):
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setBrush(QColor("#3b82f6"))
    painter.setPen(QColor("#1e3a8a"))
    painter.drawRoundedRect(8, 12, 48, 44, 6, 6)
    painter.setPen(QColor("white"))
    font = QFont()
    font.setBold(True)
    font.setPointSize(20)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), ALIGN_CENTER, "C")
    painter.end()
    return QIcon(pixmap)


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

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()


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

        self.lead = timedelta(minutes=float(get_setting(config, "lead_minutes")))
        self.window_hours = float(get_setting(config, "window_hours"))
        self.snooze_minutes = int(get_setting(config, "snooze_minutes"))
        check_interval = int(get_setting(config, "check_interval"))
        poll_interval = int(get_setting(config, "poll_interval"))
        self.feeds = get_feeds(config, logger)

        self.events: list[Occurrence] = []
        self.seen: set = set()        # keys we've already notified for (memory)
        self.windows: dict = {}

        self.icon = make_icon()  # one calendar icon, shared by tray and windows
        self.tray = QSystemTrayIcon(self.icon, app)
        self.tray.setToolTip("nestcal")
        # Menu is rebuilt each time it's opened so the list of in-progress
        # meetings at the top is always current.
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self._rebuild_menu)
        self._rebuild_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.poller = CalendarPoller(self.feeds, self.window_hours, poll_interval, logger)
        self.poller.events_updated.connect(self.on_events)
        self.poller.start()

        self.timer = QTimer()
        self.timer.timeout.connect(self.check_due)
        self.timer.start(max(1, check_interval) * 1000)

    def _rebuild_menu(self) -> None:
        """Repopulate the tray menu: meetings in progress OR within their lead
        window at the top (each opens its reminder when clicked, even if
        previously dismissed), then the standard actions. Rebuilt on aboutToShow
        so it's always current — this is the recovery path for a pop-up you
        dismissed early or missed."""
        self.menu.clear()
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

    def on_events(self, occurrences: list) -> None:
        self.events = occurrences
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

    def quit(self) -> None:
        self.logger.log("shutting down")
        self.poller.stop()
        self.poller.wait(2000)
        self.app.quit()


def main() -> None:
    logger = Logger("--debug" in sys.argv)
    config = load_config(logger)

    app = QApplication(sys.argv)
    app.setApplicationName("nestcal")
    app.setQuitOnLastWindowClosed(False)  # dismissing a reminder must not quit

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("nestcal: no system tray available", file=sys.stderr)

    feeds = get_feeds(config, logger)
    if not feeds:
        print(f"nestcal: no feeds configured; add calendars under [calendars] "
              f"in ~/.config/nestcal.ini", file=sys.stderr)
        sys.exit(1)

    TrayApp(app, config, logger)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
