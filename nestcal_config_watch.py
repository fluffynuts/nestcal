"""Tells the app when the config file changes, whoever changed it: the UI, or a text editor."""

from pathlib import Path

from nestcal_qt import QFileSystemWatcher, QObject, QTimer, pyqtSignal

SETTLE_MS = 300


class ConfigWatcher(QObject):
    """Editors save by writing in place, or by replacing the file (which ends a watch on
    the old one), so this watches the folder as well and re-adds the file after each change.
    Changes are held for a moment so one save is one `changed`, however many events it caused."""

    changed = pyqtSignal()

    def __init__(self, path: Path, settle_ms: int = SETTLE_MS):
        super().__init__()
        self._path = path.resolve()
        self._watcher = QFileSystemWatcher()
        self._watcher.fileChanged.connect(self._on_event)
        self._watcher.directoryChanged.connect(self._on_event)
        self._settle = QTimer()
        self._settle.setSingleShot(True)
        self._settle.setInterval(settle_ms)
        self._settle.timeout.connect(self.changed)
        self._watch()

    def _watch(self) -> None:
        for candidate in (self._path.parent, self._path):
            if candidate.exists() and str(candidate) not in self._watcher.files() + self._watcher.directories():
                self._watcher.addPath(str(candidate))

    def _on_event(self, _path: str) -> None:
        self._watch()
        self._settle.start()
