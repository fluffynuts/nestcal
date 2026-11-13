"""The Events tab: what's coming up, and whether there's a newer nestcal."""

from datetime import datetime
from html import escape
from typing import Callable

from nestcal_core import Occurrence, format_when, format_when_long
from nestcal_qt import (
    ALIGN_LEFT_TOP, FIELDS_GROW, FIT_CONTENTS, NO_EDITING, PLAIN_TEXT, SELECT_ONE, SELECT_ROWS, STRETCH, QDesktopServices,
    QDialog, QHBoxLayout, QIcon, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTimer,
    QUrl, QVBoxLayout, QWidget, QFormLayout,
)
from nestcal_update import RELEASES_URL

REFRESH_MS = 30_000


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _plain_label(text: str) -> QLabel:
    """Calendar text is someone else's: never let a title like '<b>x</b>' be read as markup."""
    label = QLabel(text)
    label.setTextFormat(PLAIN_TEXT)
    label.setWordWrap(True)
    return label


class EventDialog(QDialog):
    """Everything nestcal knows about one event, including its meeting link."""

    def __init__(self, icon: QIcon, occ: Occurrence):
        super().__init__()
        self.setWindowTitle(occ.summary)
        self.setWindowIcon(icon)
        self.setMinimumWidth(420)

        title = _plain_label(occ.summary)
        font = title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        title.setFont(font)

        self.link_label = QLabel()
        if occ.link:
            self.link_label.setText(f'<a href="{escape(occ.link, quote=True)}">{escape(occ.link)}</a>')
            self.link_label.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        else:
            self.link_label.setText("No meeting link")
        self.link_label.setWordWrap(True)

        details = QFormLayout()
        # Both are set because themes differ: some squeeze the value column to its smallest
        # size (hiding wrapped text) and some right-align the names.
        details.setFieldGrowthPolicy(FIELDS_GROW)
        details.setLabelAlignment(ALIGN_LEFT_TOP)
        details.addRow("When", _plain_label(format_when_long(occ)))
        details.addRow("Calendar", _plain_label(occ.calendar))
        details.addRow("Meeting link", self.link_label)

        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(details)
        layout.addLayout(buttons)


class EventsTab(QWidget):
    """The events still to come (or in progress) within the look-ahead, soonest first. Events
    that have ended drop off on a timer, not only when the next fetch lands, so a finished
    meeting doesn't linger."""

    def __init__(self, icon: QIcon, clock: Callable[[], datetime] = _local_now):
        super().__init__()
        self._icon = icon
        self._clock = clock
        self._occurrences: list[Occurrence] = []
        self._shown: list[Occurrence] = []
        self._window_hours: float = 24

        self.update_label = QLabel()
        self.update_label.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.update_label.hide()

        self.summary_label = QLabel()
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["When", "Event"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(NO_EDITING)
        self.table.setSelectionBehavior(SELECT_ROWS)
        self.table.setSelectionMode(SELECT_ONE)
        self.table.horizontalHeader().setSectionResizeMode(0, FIT_CONTENTS)
        self.table.horizontalHeader().setSectionResizeMode(1, STRETCH)
        self.table.cellDoubleClicked.connect(lambda row, _column: self.open_event(row))

        layout = QVBoxLayout(self)
        layout.addWidget(self.update_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(REFRESH_MS)

    def set_events(self, occurrences: list[Occurrence]) -> None:
        self._occurrences = list(occurrences)
        self._refresh()

    def set_window_hours(self, hours: float) -> None:
        self._window_hours = hours
        self._refresh()

    def show_update(self, tag: str | None) -> None:
        """Offer the releases page for newer release `tag`, or (None) take the offer away."""
        if tag is None:
            self.update_label.hide()
            return
        self.update_label.setText(
            f'A newer version of nestcal is available ({escape(tag)}): '
            f'<a href="{RELEASES_URL}">see the releases page</a>')
        self.update_label.show()

    def open_event(self, row: int) -> None:
        if 0 <= row < len(self._shown):
            EventDialog(self._icon, self._shown[row]).exec()

    def _refresh(self) -> None:
        now = self._clock()
        self._shown = [o for o in self._occurrences if o.end_local > now]
        self._shown.sort(key=lambda o: o.start_local)
        self.table.setRowCount(len(self._shown))
        for row, occ in enumerate(self._shown):
            self.table.setItem(row, 0, QTableWidgetItem(format_when(occ, now)))
            self.table.setItem(row, 1, QTableWidgetItem(occ.summary))
        hours = f"{self._window_hours:g} hour{'' if self._window_hours == 1 else 's'}"
        self.summary_label.setText(
            f"Nothing coming up in the next {hours}." if not self._shown
            else f"Coming up in the next {hours}:")
