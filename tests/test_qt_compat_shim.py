"""PyQt6/PyQt5 differences are handled in one place, nestcal_qt.py. A second place invites drift:
a name added to one and not the other only fails on the Qt version nobody is testing."""
import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent
SHIM = ROOT / "nestcal_qt.py"


def python_files():
    return [*ROOT.glob("*.py"), *(ROOT / "tests").rglob("*.py")]


def qt_binding_imports(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] in ("PyQt5", "PyQt6")]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in ("PyQt5", "PyQt6"):
            found.append(node.module)
    return found


def test_only_the_shim_imports_a_qt_binding_directly():
    offenders = {str(p.relative_to(ROOT)): imports
                 for p in python_files() if p != SHIM and (imports := qt_binding_imports(p))}

    assert offenders == {}, "import Qt names from nestcal_qt instead: " + ", ".join(offenders)


def test_the_check_itself_notices_a_direct_import(tmp_path):
    """So the test above can't pass just because the scan finds nothing."""
    sneaky = tmp_path / "sneaky.py"
    sneaky.write_text("from PyQt6.QtWidgets import QWidget\nimport PyQt5.QtCore\n# from PyQt6 import nothing\n")

    assert qt_binding_imports(sneaky) == ["PyQt6.QtWidgets", "PyQt5.QtCore"]


def test_the_scan_covers_the_app_and_its_tests():
    names = {p.name for p in python_files()}

    assert {"nestcal_tray.py", "nestcal_window.py", "conftest.py", "test_tray.py"} <= names
