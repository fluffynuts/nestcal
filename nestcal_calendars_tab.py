"""The Calendars tab: a grid of name and link, with add, edit and remove."""

from nestcal_calendar_dialog import CalendarDialog
from nestcal_core import save_calendars
from nestcal_qt import (
    FIT_CONTENTS, NO, NO_EDITING, SELECT_ONE, SELECT_ROWS, STRETCH, YES, QHBoxLayout, QIcon,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


class CalendarsTab(QWidget):
    """Every change is written to the config file as soon as it's made; the file is the
    source of truth, and the grid shows whatever set_calendars last said."""

    def __init__(self, icon: QIcon):
        super().__init__()
        self._icon = icon
        self.calendars: list[tuple[str, str]] = []

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Link"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(NO_EDITING)
        self.table.setSelectionBehavior(SELECT_ROWS)
        self.table.setSelectionMode(SELECT_ONE)
        self.table.horizontalHeader().setSectionResizeMode(0, FIT_CONTENTS)
        self.table.horizontalHeader().setSectionResizeMode(1, STRETCH)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.cellDoubleClicked.connect(lambda row, _column: self.edit_calendar(row))

        self.add_button = QPushButton("Add...")
        self.add_button.clicked.connect(self.add_calendar)
        self.edit_button = QPushButton("Edit...")
        self.edit_button.clicked.connect(lambda: self.edit_calendar(self._selected_row()))
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(lambda: self.remove_calendar(self._selected_row()))
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self._update_buttons()

    def set_calendars(self, calendars: list[tuple[str, str]]) -> None:
        selected = self._selected_row()
        self.calendars = list(calendars)
        self.table.setRowCount(len(self.calendars))
        for row, (name, url) in enumerate(self.calendars):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(url))
        if selected is not None and selected < len(self.calendars):
            self.table.selectRow(selected)
        self._update_buttons()

    def add_calendar(self) -> None:
        self._run_dialog("Add calendar", None, lambda name, url: self.calendars + [(name, url)])

    def edit_calendar(self, row: int | None) -> None:
        if row is None or row >= len(self.calendars):
            return

        def replaced(name: str, url: str) -> list[tuple[str, str]]:
            changed = list(self.calendars)
            changed[row] = (name, url)
            return changed
        self._run_dialog("Edit calendar", row, replaced)

    def remove_calendar(self, row: int | None) -> None:
        if row is None or row >= len(self.calendars):
            return
        name = self.calendars[row][0]
        if not self._confirm_remove(name):
            return
        try:
            self._persist(self.calendars[:row] + self.calendars[row + 1:])
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "nestcal", f"Couldn't save the settings: {e}")

    def _confirm_remove(self, name: str) -> bool:
        answer = QMessageBox.question(
            self, "Remove calendar", f"Stop watching '{name}'? Its link is forgotten.",
            YES | NO, NO)
        return answer == YES

    def _run_dialog(self, title: str, row: int | None, apply) -> None:
        name, url = self.calendars[row] if row is not None else ("", "")
        others = [n for i, (n, _) in enumerate(self.calendars) if i != row]
        dialog = CalendarDialog(
            self._icon, title=title, name=name, url=url, other_names=others,
            save=lambda new_name, new_url: self._persist(apply(new_name, new_url)))
        dialog.exec()

    def _persist(self, calendars: list[tuple[str, str]]) -> None:
        save_calendars(calendars)
        self.set_calendars(calendars)

    def _selected_row(self) -> int | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else None

    def _update_buttons(self) -> None:
        has_selection = self._selected_row() is not None
        self.edit_button.setEnabled(has_selection)
        self.remove_button.setEnabled(has_selection)
