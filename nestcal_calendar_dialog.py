"""The dialog for naming a calendar and giving its .ics link: first-run setup, add, and edit."""

import threading
from typing import Callable, Iterable

from nestcal_core import FeedCheck, add_calendar, check_feed, normalise_ics_url, validate_calendar
from nestcal_qt import (
    QDialog, QHBoxLayout, QIcon, QLabel, QLineEdit, QPushButton, QVBoxLayout, pyqtSignal,
)

NEW_CALENDAR_INTRO = "Give the calendar a name, and paste its .ics link."


class CalendarDialog(QDialog):
    """Validates, and hands the result to `save`, which persists it. A save that fails
    (OSError) is shown in the dialog, which stays open so nothing typed is lost."""

    _checked = pyqtSignal(int, object)

    def __init__(self, icon: QIcon, *, title: str, intro: str = NEW_CALENDAR_INTRO,
                 name: str = "", url: str = "", other_names: Iterable[str] = (),
                 save: Callable[[str, str], None] = lambda name, url: None,
                 check: Callable[[str], FeedCheck] = check_feed):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowIcon(icon)
        self.setMinimumWidth(480)
        self._other_names = set(other_names)
        self._save = save
        self._check = check
        self._latest_check = 0

        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("for example: work")
        self.url_edit = QLineEdit(url)
        self.url_edit.setPlaceholderText("https://calendar.google.com/calendar/ical/.../basic.ics")
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setWordWrap(True)
        self.check_label = QLabel()
        self.check_label.setWordWrap(True)

        intro_label = QLabel(intro)
        intro_label.setWordWrap(True)
        help_link = QLabel(
            '<a href="https://support.google.com/calendar/answer/37648">'
            'How do I find my calendar\'s .ics link?</a>')
        help_link.setOpenExternalLinks(True)

        self.test_button = QPushButton("Test link")
        self.test_button.clicked.connect(self._start_check)
        self.save_button = QPushButton("Save")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.test_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(intro_label)
        layout.addWidget(QLabel("Calendar name"))
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("Calendar .ics link (keep this private)"))
        layout.addWidget(self.url_edit)
        layout.addWidget(help_link)
        layout.addWidget(self.check_label)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        self._checked.connect(self._show_check)
        self.url_edit.textChanged.connect(self._forget_check)

    def _problem(self) -> str | None:
        problem = validate_calendar(self.name_edit.text(), self.url_edit.text())
        if problem is None and self.name_edit.text().strip() in self._other_names:
            return f"There is already a calendar called '{self.name_edit.text().strip()}'"
        return problem

    def _on_save(self) -> None:
        problem = self._problem()
        if problem:
            self.error_label.setText(problem)
            return
        try:
            self._save(self.name_edit.text().strip(), normalise_ics_url(self.url_edit.text()))
        except (OSError, ValueError) as e:
            self.error_label.setText(f"Couldn't save the settings: {e}")
            return
        self.accept()

    def _start_check(self) -> None:
        problem = validate_calendar("-", self.url_edit.text())  # only the link matters here
        if problem:
            self.error_label.setText(problem)
            return
        self.error_label.clear()
        self._latest_check += 1
        attempt, url = self._latest_check, self.url_edit.text()
        self.check_label.setStyleSheet("")
        self.check_label.setText("Testing...")
        self.test_button.setEnabled(False)
        # A daemon thread: a slow feed must neither freeze the dialog nor block quitting.
        threading.Thread(target=lambda: self._checked.emit(attempt, self._check(url)),
                         daemon=True).start()

    def _show_check(self, attempt: int, result: FeedCheck) -> None:
        if attempt != self._latest_check:
            return  # the link was edited since; this answer is about something else
        self.test_button.setEnabled(True)
        self.check_label.setStyleSheet("color: #04896a;" if result.ok else "color: #c0392b;")
        self.check_label.setText(result.message)

    def _forget_check(self) -> None:
        self._latest_check += 1
        self.test_button.setEnabled(True)
        self.check_label.clear()


class SetupDialog(CalendarDialog):
    """First-run: add the user's first calendar."""

    def __init__(self, icon: QIcon):
        super().__init__(
            icon, title="nestcal setup", save=add_calendar,
            intro="nestcal reminds you before meetings start. To begin, tell it about one "
                  "calendar. You can add more, and change settings, once it's running.")
