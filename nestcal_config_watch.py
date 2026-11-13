"""Tells the app when the config file changes, whoever changed it: the UI, or a text editor."""

import hashlib
from pathlib import Path

from nestcal_qt import QFileSystemWatcher, QObject, QTimer, pyqtSignal

SETTLE_MS = 300


class ConfigWatcher(QObject):
    """Editors save by writing in place, or by replacing the file (which ends a watch on
    the old one), so this watches the folder as well and re-adds the file after each change.
    Changes are held for a moment so one save is one `changed`, however many events it caused.

    Watching the folder means hearing about every write to it: other programs' files, nestcal's
    own state file, a save that rewrites identical content. So `changed` is only emitted when
    what's in the config file differs from what was last announced."""

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
        self._settle.timeout.connect(self._announce_if_changed)
        self._seen = self._fingerprint()
        self._watch()

    def _fingerprint(self) -> str:
        """What the file holds, or that it's missing or unreadable (both worth announcing)."""
        try:
            return hashlib.sha256(self._path.read_bytes()).hexdigest()
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unreadable"

    def _announce_if_changed(self) -> None:
        now = self._fingerprint()
        if now != self._seen:
            self._seen = now
            self.changed.emit()

    def _watch(self) -> None:
        for candidate in (self._path.parent, self._path):
            if candidate.exists() and str(candidate) not in self._watcher.files() + self._watcher.directories():
                self._watcher.addPath(str(candidate))

    def _on_event(self, _path: str) -> None:
        self._watch()
        self._settle.start()
