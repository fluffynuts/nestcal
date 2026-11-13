import threading

import pytest

import nestcal_calendar_dialog
import nestcal_tray
import nestcal_core
from nestcal_core import FeedCheck, read_config

A = "https://example.com/a.ics"
B = "https://example.com/b.ics"
C = "https://example.com/c.ics"


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "nestcal.ini"
    path.write_text("# keep me\n[settings]\nlead_minutes = 7\n\n[calendars]\nwork = " + A + "\nhome = " + B + "\n")
    monkeypatch.setattr(nestcal_core, "CONFIG_PATH", path)
    return path


@pytest.fixture
def tab(qtbot, config_path):
    from nestcal_calendars_tab import CalendarsTab
    import nestcal_tray
    tab = CalendarsTab(nestcal_tray.make_icon())
    qtbot.addWidget(tab)
    tab.set_calendars([(n, u) for n, u in read_config().items("calendars")])
    tab.show()
    return tab


@pytest.fixture
def answer_dialog(monkeypatch):
    """Lets a test play the user in the add/edit dialog: returns the dialogs that were shown."""
    shown = []

    def install(name=None, url=None, click="save"):
        def fake_exec(self):
            shown.append(self)
            if name is not None:
                self.name_edit.setText(name)
            if url is not None:
                self.url_edit.setText(url)
            if click == "save":
                self.save_button.click()
            else:
                self.reject()
            return self.result()
        monkeypatch.setattr(nestcal_calendar_dialog.CalendarDialog, "exec", fake_exec)
        return shown
    return install


def grid(tab):
    return [(tab.table.item(r, 0).text(), tab.table.item(r, 1).text()) for r in range(tab.table.rowCount())]


def file_calendars():
    return list(read_config().items("calendars"))


def test_the_grid_shows_a_name_and_link_per_calendar(tab):
    assert grid(tab) == [("work", A), ("home", B)]
    assert [tab.table.horizontalHeaderItem(i).text() for i in range(2)] == ["Name", "Link"]


def test_edit_and_remove_need_a_selected_row(tab):
    assert not tab.edit_button.isEnabled()
    assert not tab.remove_button.isEnabled()

    tab.table.selectRow(0)

    assert tab.edit_button.isEnabled()
    assert tab.remove_button.isEnabled()
    assert tab.add_button.isEnabled()


def test_adding_a_calendar_saves_it_to_the_file_and_shows_it(tab, config_path, answer_dialog):
    answer_dialog(name="school", url=C)

    tab.add_button.click()

    assert grid(tab) == [("work", A), ("home", B), ("school", C)]
    assert file_calendars() == grid(tab)
    assert "# keep me" in config_path.read_text()
    assert "lead_minutes = 7" in config_path.read_text()


def test_cancelling_the_add_dialog_changes_nothing(tab, config_path, answer_dialog):
    before = config_path.read_text()
    answer_dialog(name="school", url=C, click="cancel")

    tab.add_button.click()

    assert grid(tab) == [("work", A), ("home", B)]
    assert config_path.read_text() == before


def test_editing_opens_the_dialog_filled_in_and_replaces_the_row_in_place(tab, answer_dialog):
    shown = answer_dialog(name="office", url=C)
    tab.table.selectRow(0)

    tab.edit_button.click()

    assert len(shown) == 1
    assert grid(tab) == [("office", C), ("home", B)]
    assert file_calendars() == grid(tab)


def test_the_edit_dialog_starts_with_the_calendars_current_values(tab, answer_dialog):
    shown = answer_dialog(click="cancel")

    tab.edit_calendar(1)

    assert (shown[0].name_edit.text(), shown[0].url_edit.text()) == ("home", B)


def test_double_clicking_a_row_edits_it(tab, answer_dialog):
    shown = answer_dialog(click="cancel")

    tab.table.cellDoubleClicked.emit(1, 0)

    assert shown[0].name_edit.text() == "home"


def test_a_name_already_in_use_is_refused_but_keeping_your_own_name_is_fine(tab, answer_dialog):
    shown = answer_dialog(name="home", url=C)
    tab.table.selectRow(0)

    tab.edit_button.click()  # renaming "work" to "home" collides with the other row
    assert "already a calendar called 'home'" in shown[0].error_label.text()
    assert grid(tab) == [("work", A), ("home", B)]

    answer_dialog(name="work", url=C)
    tab.edit_calendar(0)  # keeping "work" while changing the link is allowed
    assert grid(tab)[0] == ("work", C)


def test_removing_asks_first_and_then_deletes_the_row_from_the_file(tab, config_path, monkeypatch):
    asked = []
    monkeypatch.setattr(tab, "_confirm_remove", lambda name: asked.append(name) or True)
    tab.table.selectRow(0)

    tab.remove_button.click()

    assert asked == ["work"]
    assert grid(tab) == [("home", B)]
    assert file_calendars() == [("home", B)]
    assert "# keep me" in config_path.read_text()


def test_declining_the_removal_keeps_everything(tab, config_path, monkeypatch):
    before = config_path.read_text()
    monkeypatch.setattr(tab, "_confirm_remove", lambda name: False)
    tab.table.selectRow(0)

    tab.remove_button.click()

    assert grid(tab) == [("work", A), ("home", B)]
    assert config_path.read_text() == before


def test_a_save_that_fails_is_shown_in_the_dialog_and_nothing_changes(tab, answer_dialog, monkeypatch):
    def refuse(calendars):
        raise PermissionError("read-only file system")
    monkeypatch.setattr("nestcal_calendars_tab.save_calendars", refuse)
    shown = answer_dialog(name="school", url=C)

    tab.add_button.click()

    assert "read-only file system" in shown[0].error_label.text()
    assert grid(tab) == [("work", A), ("home", B)]


# --- the dialog's Test button ---

@pytest.fixture
def dialog(qtbot):
    import nestcal_tray
    results = {}

    def make(**kwargs):
        d = nestcal_calendar_dialog.CalendarDialog(
            nestcal_tray.make_icon(), title="t", check=lambda url: results[url], **kwargs)
        qtbot.addWidget(d)
        d.show()
        return d
    make.results = results
    return make


def test_testing_a_good_link_says_so(qtbot, dialog):
    dialog.results[A] = FeedCheck(True, "Looks good: 3 events found")
    d = dialog()
    d.url_edit.setText(A)

    d.test_button.click()

    qtbot.waitUntil(lambda: d.check_label.text() == "Looks good: 3 events found", timeout=5000)
    assert d.test_button.isEnabled()


def test_testing_a_bad_link_shows_why(qtbot, dialog):
    dialog.results[A] = FeedCheck(False, "The server answered 404")
    d = dialog()
    d.url_edit.setText(A)

    d.test_button.click()

    qtbot.waitUntil(lambda: "404" in d.check_label.text(), timeout=5000)


def test_testing_a_malformed_link_complains_without_fetching(dialog):
    d = dialog()
    d.url_edit.setText("nonsense")

    d.test_button.click()

    assert "https://" in d.error_label.text()
    assert d.check_label.text() == ""


def test_a_result_for_a_link_that_has_since_been_edited_is_discarded(qtbot):
    gate = threading.Event()

    def check_held_until_released(url):
        assert gate.wait(10), "the test never released the check"
        return FeedCheck(True, "Looks good: 3 events found")
    d = nestcal_calendar_dialog.CalendarDialog(
        nestcal_tray.make_icon(), title="t", check=check_held_until_released)
    qtbot.addWidget(d)
    d.show()
    d.url_edit.setText(A)
    d.test_button.click()
    d.url_edit.setText(B)  # edited while the check is still running

    with qtbot.waitSignal(d._checked, timeout=10_000):  # the result has now been delivered to the dialog
        gate.set()

    assert d.check_label.text() == ""
    assert d.test_button.isEnabled()


def test_the_result_of_a_check_that_was_not_overtaken_is_shown(qtbot):
    """The control for the test above: the same flow, without the edit, does show the result."""
    gate = threading.Event()
    d = nestcal_calendar_dialog.CalendarDialog(
        nestcal_tray.make_icon(), title="t",
        check=lambda url: gate.wait(10) and FeedCheck(True, "Looks good: 3 events found"))
    qtbot.addWidget(d)
    d.show()
    d.url_edit.setText(A)
    d.test_button.click()

    with qtbot.waitSignal(d._checked, timeout=10_000):
        gate.set()

    assert d.check_label.text() == "Looks good: 3 events found"


def test_testing_against_a_real_feed(qtbot, feed_server):
    """No stub: the real check against a real HTTP server."""
    from ics import calendar, event
    from datetime import timedelta
    import nestcal_tray
    feed_server.body = calendar(event("e1", "Planning", timedelta(hours=3)))
    d = nestcal_calendar_dialog.CalendarDialog(nestcal_tray.make_icon(), title="t")
    qtbot.addWidget(d)
    d.show()
    d.url_edit.setText(feed_server.url)

    d.test_button.click()

    qtbot.waitUntil(lambda: d.check_label.text().startswith("Looks good: 1 event"), timeout=10_000)


# --- the file changing while a dialog or confirmation is open ---

def edit_while(monkeypatch, external, name, url):
    """The user edits in the dialog; before Save, the file is changed elsewhere and the tab is told."""
    def fake_exec(self):
        external()
        self.name_edit.setText(name)
        self.url_edit.setText(url)
        self.save_button.click()
        return self.result()
    monkeypatch.setattr(nestcal_calendar_dialog.CalendarDialog, "exec", fake_exec)


def test_an_edit_changes_the_calendar_that_was_being_edited_even_if_rows_were_removed_meanwhile(
        tab, monkeypatch):
    edit_while(monkeypatch, lambda: tab.set_calendars([("home", B)]), "office", C)  # "work" was deleted

    tab.edit_calendar(1)  # editing "home"

    assert grid(tab) == [("office", C)]
    assert file_calendars() == [("office", C)]


def test_an_edit_changes_the_calendar_that_was_being_edited_even_if_rows_were_added_above(tab, monkeypatch):
    edit_while(monkeypatch, lambda: tab.set_calendars([("new", C), ("work", A), ("home", B)]), "office", C)

    tab.edit_calendar(0)  # editing "work"

    assert grid(tab) == [("new", C), ("office", C), ("home", B)]


def test_an_edit_of_a_calendar_that_was_changed_elsewhere_is_refused_and_nothing_is_overwritten(
        tab, monkeypatch, config_path):
    shown = []

    def fake_exec(self):
        tab.set_calendars([("work", C), ("home", B)])  # "work" now has a different link
        self.name_edit.setText("office")
        self.save_button.click()
        shown.append(self.error_label.text())
        return self.result()
    monkeypatch.setattr(nestcal_calendar_dialog.CalendarDialog, "exec", fake_exec)
    before = config_path.read_text()

    tab.edit_calendar(0)

    assert "changed" in shown[0] and "removed" in shown[0]
    assert grid(tab) == [("work", C), ("home", B)]
    assert config_path.read_text() == before


def test_a_removal_removes_the_calendar_that_was_chosen_even_if_rows_were_added_above(tab, monkeypatch):
    def confirm(name):
        tab.set_calendars([("new", C), ("work", A), ("home", B)])
        return True
    monkeypatch.setattr(tab, "_confirm_remove", confirm)

    tab.remove_calendar(1)  # "home"

    assert grid(tab) == [("new", C), ("work", A)]
    assert file_calendars() == grid(tab)


def test_removing_a_calendar_that_vanished_meanwhile_says_so_and_removes_nothing(tab, monkeypatch):
    errors = []
    monkeypatch.setattr(tab, "_show_error", errors.append)

    def confirm(name):
        tab.set_calendars([("work", A)])  # "home" was deleted in an editor
        return True
    monkeypatch.setattr(tab, "_confirm_remove", confirm)

    tab.remove_calendar(1)

    assert len(errors) == 1 and "home" in errors[0]
    assert grid(tab) == [("work", A)]
