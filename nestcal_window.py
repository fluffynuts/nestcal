"""The main nestcal window: upcoming events, preferences and calendars, one tab each."""

from nestcal_calendars_tab import CalendarsTab
from nestcal_events_tab import EventsTab
from nestcal_preferences_tab import PreferencesTab
from nestcal_qt import QIcon, QLabel, QTabWidget, QVBoxLayout, QWidget


class MainWindow(QWidget):
    """Closing it only hides it: the app lives in the tray, and quitting is the tray menu's job."""

    def __init__(self, icon: QIcon):
        super().__init__(None)
        self.setWindowTitle("nestcal")
        self.setWindowIcon(icon)
        self.resize(720, 480)

        self.problem_label = QLabel()
        self.problem_label.setStyleSheet("color: #c0392b;")
        self.problem_label.setWordWrap(True)
        self.problem_label.hide()

        self.events_tab = EventsTab(icon)
        self.preferences_tab = PreferencesTab()
        self.calendars_tab = CalendarsTab(icon)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.events_tab, "Events")
        self.tabs.addTab(self.preferences_tab, "Preferences")
        self.tabs.addTab(self.calendars_tab, "Calendars")
        layout = QVBoxLayout(self)
        layout.addWidget(self.problem_label)
        layout.addWidget(self.tabs)

    def show_config_problem(self, text: str | None) -> None:
        """Say why the config file on disk isn't being applied, or (None) that it is again."""
        self.problem_label.setText(text or "")
        self.problem_label.setVisible(bool(text))

    def present(self) -> None:
        """Show, and pull to the front whether it was hidden, minimised or buried."""
        self.showNormal()
        self.raise_()
        self.activateWindow()
