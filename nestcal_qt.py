"""One place for the PyQt6 / PyQt5 differences, for the modules that don't need to care."""

try:
    from PyQt6.QtWidgets import (
        QAbstractItemView, QCheckBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
        QProxyStyle, QPushButton, QSpinBox, QStyle, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
    )
    from PyQt6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer, QUrl, pyqtSignal
    from PyQt6.QtGui import QDesktopServices, QIcon
    PYQT = 6
    PLAIN_TEXT = Qt.TextFormat.PlainText
    ALIGN_LEFT_TOP = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
    FIELDS_GROW = QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
    SELECT_ROWS = QAbstractItemView.SelectionBehavior.SelectRows
    SELECT_ONE = QAbstractItemView.SelectionMode.SingleSelection
    NO_EDITING = QAbstractItemView.EditTrigger.NoEditTriggers
    STRETCH = QHeaderView.ResizeMode.Stretch
    FIT_CONTENTS = QHeaderView.ResizeMode.ResizeToContents
    YES = QMessageBox.StandardButton.Yes
    NO = QMessageBox.StandardButton.No
except ImportError:
    from PyQt5.QtWidgets import (
        QAbstractItemView, QCheckBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
        QProxyStyle, QPushButton, QSpinBox, QStyle, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
    )
    from PyQt5.QtCore import QFileSystemWatcher, QObject, Qt, QTimer, QUrl, pyqtSignal
    from PyQt5.QtGui import QDesktopServices, QIcon
    PYQT = 5
    PLAIN_TEXT = Qt.PlainText
    ALIGN_LEFT_TOP = Qt.AlignLeft | Qt.AlignTop
    FIELDS_GROW = QFormLayout.AllNonFixedFieldsGrow
    SELECT_ROWS = QAbstractItemView.SelectRows
    SELECT_ONE = QAbstractItemView.SingleSelection
    NO_EDITING = QAbstractItemView.NoEditTriggers
    STRETCH = QHeaderView.Stretch
    FIT_CONTENTS = QHeaderView.ResizeToContents
    YES = QMessageBox.Yes
    NO = QMessageBox.No
