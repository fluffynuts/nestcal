from datetime import datetime, timedelta, timezone

import pytest

import nestcal_events_tab
import nestcal_tray
from nestcal_qt import QLabel
from nestcal_core import Occurrence
from nestcal_events_tab import EventsTab
from nestcal_update import RELEASES_URL

TZ = timezone(timedelta(hours=2))
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=TZ)


def occ(summary, start_hour, minutes=60, calendar="work", link=None, all_day=False, uid=None):
    start = NOW.replace(hour=start_hour, minute=0)
    return Occurrence(uid=uid or summary, summary=summary, calendar=calendar, start_local=start,
                      end_local=start + timedelta(minutes=minutes), all_day=all_day, link=link)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tab(qtbot, clock):
    tab = EventsTab(nestcal_tray.make_icon(), clock=clock)
    qtbot.addWidget(tab)
    tab.show()
    return tab


def rows(tab):
    return [(tab.table.item(r, 0).text(), tab.table.item(r, 1).text()) for r in range(tab.table.rowCount())]


@pytest.fixture
def shown_dialogs(monkeypatch):
    shown = []
    monkeypatch.setattr(nestcal_events_tab.EventDialog, "exec", lambda self: shown.append(self) or 0)
    return shown


def test_the_grid_has_just_when_and_event_columns(tab):
    assert [tab.table.horizontalHeaderItem(i).text() for i in range(2)] == ["When", "Event"]


def test_events_are_listed_soonest_first_with_when_and_title(tab):
    tab.set_events([occ("Later", 16), occ("Sooner", 14)])

    assert rows(tab) == [("Today 14:00 – 15:00", "Sooner"), ("Today 16:00 – 17:00", "Later")]


def test_the_calendar_is_not_a_column_even_with_several_calendars(tab):
    tab.set_events([occ("A", 14, calendar="work"), occ("B", 15, calendar="home")])

    assert tab.table.columnCount() == 2
    assert all(cell not in ("work", "home") for row in rows(tab) for cell in row)


def test_an_event_in_progress_is_listed_and_says_so(tab):
    tab.set_events([occ("Standup", 11, minutes=90)])

    assert rows(tab) == [("Today 11:00 – 12:30 (in progress)", "Standup")]


def test_an_event_that_has_ended_is_not_listed(tab):
    tab.set_events([occ("Over", 9, minutes=60), occ("Coming", 14)])

    assert [title for _, title in rows(tab)] == ["Coming"]


def test_an_event_drops_off_by_itself_once_it_ends(tab, clock):
    tab.set_events([occ("Standup", 12, minutes=30)])
    assert len(rows(tab)) == 1

    clock.now = NOW + timedelta(minutes=31)
    tab._refresh_timer.timeout.emit()

    assert rows(tab) == []


def test_an_all_day_event_is_listed(tab):
    tab.set_events([occ("Holiday", 0, minutes=24 * 60, all_day=True)])

    assert rows(tab) == [("Today (all day)", "Holiday")]


def test_the_summary_says_how_far_ahead_it_looks(tab):
    tab.set_events([occ("A", 14)])
    tab.set_window_hours(24)
    assert tab.summary_label.text() == "Coming up in the next 24 hours:"

    tab.set_window_hours(1)
    assert tab.summary_label.text() == "Coming up in the next 1 hour:"


def test_the_summary_says_so_when_nothing_is_coming_up(tab):
    tab.set_events([])
    tab.set_window_hours(48)

    assert tab.summary_label.text() == "Nothing coming up in the next 48 hours."


def test_double_clicking_a_row_opens_that_events_details(tab, shown_dialogs):
    tab.set_events([occ("Later", 16), occ("Sooner", 14)])

    tab.table.cellDoubleClicked.emit(1, 0)

    assert shown_dialogs[0].windowTitle() == "Later"


def test_double_clicking_nothing_opens_nothing(tab, shown_dialogs):
    tab.set_events([])

    tab.table.cellDoubleClicked.emit(0, 0)

    assert shown_dialogs == []


# --- the details dialog ---

def dialog_for(qtbot, event):
    dialog = nestcal_events_tab.EventDialog(nestcal_tray.make_icon(), event)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def all_text(dialog):
    return " | ".join(label.text() for label in dialog.findChildren(QLabel))


def test_the_dialog_shows_title_calendar_and_when(qtbot):
    dialog = dialog_for(qtbot, occ("Planning", 14, calendar="home"))

    text = all_text(dialog)
    assert "Planning" in text
    assert "home" in text
    assert "Friday 13 November 2026, 14:00 – 15:00" in text


def test_the_meeting_link_is_clickable_and_opens_in_the_browser(qtbot, opened_urls):
    dialog = dialog_for(qtbot, occ("Planning", 14, link="https://meet.google.com/abc-defg-hij"))

    dialog.link_label.linkActivated.emit("https://meet.google.com/abc-defg-hij")

    assert "https://meet.google.com/abc-defg-hij" in dialog.link_label.text()
    assert opened_urls == ["https://meet.google.com/abc-defg-hij"]


def test_an_event_without_a_link_says_so(qtbot):
    dialog = dialog_for(qtbot, occ("Pick up the kids", 14))

    assert dialog.link_label.text() == "No meeting link"


def test_a_title_that_looks_like_markup_is_shown_as_text(qtbot):
    dialog = dialog_for(qtbot, occ("<b>bold</b> & <i>co</i>", 14))

    title = next(l for l in dialog.findChildren(QLabel) if "bold" in l.text())
    assert title.text() == "<b>bold</b> & <i>co</i>"
    assert title.textFormat() == nestcal_events_tab.PLAIN_TEXT


# --- the update link ---

def test_no_update_link_until_there_is_an_update(tab):
    assert tab.update_label.isHidden()


def test_an_update_shows_a_link_to_the_releases_page(tab, opened_urls):
    tab.show_update("v0.9.0")

    assert not tab.update_label.isHidden()
    assert "v0.9.0" in tab.update_label.text()
    tab.update_label.linkActivated.emit(RELEASES_URL)
    assert opened_urls == [RELEASES_URL]
    assert RELEASES_URL in tab.update_label.text()


def test_the_update_link_can_be_taken_away_again(tab):
    tab.show_update("v0.9.0")

    tab.show_update(None)

    assert tab.update_label.isHidden()


def test_the_dialog_shows_the_whole_time_and_link_on_a_style_that_squeezes_forms(qtbot, form_hostile_style):
    """The time was wrapped to its first line and the link to 'https://', and the rest hidden."""
    link = "https://meet.google.com/qsb-cyvq-siz"
    dialog = dialog_for(qtbot, occ("test", 14, link=link))

    when = next(l for l in dialog.findChildren(QLabel) if "November" in l.text())
    for label in (when, dialog.link_label):
        assert label.height() >= label.heightForWidth(label.width()), "wrapped text is cut off"
    assert dialog.link_label.width() > dialog.link_label.fontMetrics().horizontalAdvance("https://meet.")


def test_the_dialogs_field_names_start_at_the_same_left_edge_on_a_style_that_right_aligns_them(
        qtbot, form_hostile_style):
    dialog = dialog_for(qtbot, occ("Planning", 14, link="https://meet.google.com/abc-defg-hij"))

    names = [l for l in dialog.findChildren(QLabel) if l.text() in ("When", "Calendar", "Meeting link")]
    assert len(names) == 3
    assert len({label.x() for label in names}) == 1
