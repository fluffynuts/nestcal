"""The Preferences tab: the [settings] of the config file, with Save and Revert."""

from dataclasses import asdict

from nestcal_core import Settings, save_settings
from nestcal_qt import (
    QCheckBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

# key -> (label, unit, lowest, highest, explanation). The ranges are what the screen will let
# you pick; the file itself may hold anything parse_settings accepts.
FIELDS = {
    "lead_minutes": ("Remind me", "minutes before a meeting starts", 0, 120,
                     "How long before a meeting starts its reminder pops up."),
    "snooze_minutes": ("Snooze for", "minutes", 1, 120,
                       "How long Snooze hides a reminder before it pops up again."),
    "poll_interval": ("Fetch calendars every", "seconds", 10, 86400,
                      "How often your calendar links are fetched."),
    "window_hours": ("Look ahead", "hours", 1, 720,
                     "How far ahead events are fetched and shown."),
    "check_interval": ("Check for due meetings every", "seconds", 1, 3600,
                       "How often nestcal looks for a meeting that is due, or already started "
                       "(for example one you were only just added to)."),
}


def _suffix(unit: str, value: int) -> str:
    """' 1 minute', ' 2 minutes': the unit's first word is plural, so singular is without its 's'."""
    word, _, rest = unit.partition(" ")
    return f" {word[:-1] if value == 1 else word}" + (f" {rest}" if rest else "")


class PreferencesTab(QWidget):
    """Shows what's in the file and only writes when you press Save. When the file changes
    underneath (set_settings), fields you haven't touched follow it and fields you have keep
    your edit, so a change made in a text editor never silently eats unsaved work."""

    def __init__(self):
        super().__init__()
        self.spins: dict[str, QSpinBox] = {}
        self._baseline: dict = {}

        form = QFormLayout()
        for key, (label, unit, lowest, highest, explanation) in FIELDS.items():
            spin = QSpinBox()
            spin.setRange(lowest, highest)
            spin.setSuffix(_suffix(unit, spin.value()))
            spin.setToolTip(explanation)
            spin.valueChanged.connect(lambda value, spin=spin, unit=unit: spin.setSuffix(_suffix(unit, value)))
            spin.valueChanged.connect(self._update_buttons)
            self.spins[key] = spin
            form.addRow(label, spin)
        self.updates_checkbox = QCheckBox("Check for new versions of nestcal")
        self.updates_checkbox.setToolTip("Asks GitHub, now and then, whether a newer release exists.")
        self.updates_checkbox.toggled.connect(self._update_buttons)
        form.addRow("", self.updates_checkbox)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setWordWrap(True)
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save)
        self.revert_button = QPushButton("Revert")
        self.revert_button.clicked.connect(self.revert)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.revert_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addStretch(1)
        layout.addLayout(buttons)
        self._update_buttons()

    def _shown(self) -> dict:
        shown = {key: spin.value() for key, spin in self.spins.items()}
        shown["check_for_updates"] = self.updates_checkbox.isChecked()
        return shown

    def _set_field(self, key: str, value) -> None:
        if key == "check_for_updates":
            self.updates_checkbox.setChecked(value)
        else:
            self.spins[key].setValue(value)

    def _holdable(self, key: str, value):
        """`value` as the field can show it: a spin box clamps a number outside its range."""
        if key == "check_for_updates":
            return value
        spin = self.spins[key]
        return max(spin.minimum(), min(spin.maximum(), round(value)))

    def set_settings(self, settings: Settings) -> None:
        """Take what the file now says. Edited fields keep their edit; the rest follow the file."""
        incoming = {key: self._holdable(key, value) for key, value in asdict(settings).items()}
        shown = self._shown()
        for key, value in incoming.items():
            if key not in self._baseline or shown[key] == self._baseline[key]:
                self._set_field(key, value)
        self._baseline = incoming
        self._update_buttons()

    def changed(self) -> dict:
        shown = self._shown()
        return {key: value for key, value in shown.items() if value != self._baseline.get(key)}

    def save(self) -> None:
        changed = self.changed()
        if not changed:
            return
        text = {key: str(value).lower() if isinstance(value, bool) else str(value)
                for key, value in changed.items()}
        try:
            save_settings(text)
        except (OSError, ValueError) as e:
            self.error_label.setText(f"Couldn't save the settings: {e}")
            return
        self.error_label.clear()
        self._baseline = self._shown()
        self._update_buttons()

    def revert(self) -> None:
        for key, value in self._baseline.items():
            self._set_field(key, value)
        self.error_label.clear()

    def _update_buttons(self) -> None:
        dirty = bool(self.changed()) if self._baseline else False
        self.save_button.setEnabled(dirty)
        self.revert_button.setEnabled(dirty)
