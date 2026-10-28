from datetime import timedelta

import nestcal_tray
from ics import all_day_event, calendar, event

DUE_SOON = timedelta(minutes=1)
NOT_YET = timedelta(hours=3)


def test_tooltip_names_the_next_upcoming_event(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Planning", NOT_YET))
    app = start_app()
    app.wait_for_polls(1)

    assert app.tooltip.startswith("nestcal - next: Planning at ")


def test_tooltip_says_so_when_nothing_is_coming_up(feed_server, start_app):
    feed_server.body = calendar()
    app = start_app()
    app.wait_for_polls(1)

    assert app.tooltip == "nestcal - no upcoming events"


def test_tooltip_ignores_all_day_events(feed_server, start_app):
    feed_server.body = calendar(all_day_event("e1", "Public holiday"))
    app = start_app()
    app.wait_for_polls(1)

    assert app.tooltip == "nestcal - no upcoming events"


def test_menu_without_current_meetings_has_only_the_standard_actions(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Planning", NOT_YET))
    app = start_app()
    app.wait_for_polls(1)

    assert app.menu_texts() == ["Poll now", "---", "Quit"]


def test_menu_lists_current_meetings_above_the_standard_actions(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Standup", DUE_SOON), event("e2", "Planning", NOT_YET))
    app = start_app()
    app.wait_for_polls(1)

    texts = app.menu_texts()
    assert len(texts) == 5
    assert texts[0].startswith("Standup ")
    assert texts[1:] == ["---", "Poll now", "---", "Quit"]


def test_choosing_a_meeting_from_the_menu_reopens_a_dismissed_reminder(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Standup", DUE_SOON))
    app = start_app()
    app.wait_for_polls(1)
    [window] = app.windows.values()
    window.close()
    assert app.windows == {}

    meeting_action = app.open_menu()[0]
    meeting_action.trigger()

    [reopened] = app.windows.values()
    assert reopened.isVisible()
    assert reopened.windowTitle() == "Meeting: Standup"


def test_choosing_a_meeting_whose_reminder_is_open_raises_it_instead_of_opening_a_second(
        qapp, feed_server, start_app):
    feed_server.body = calendar(event("e1", "Standup", DUE_SOON))
    app = start_app()
    app.wait_for_polls(1)
    [original] = app.windows.values()

    app.open_menu()[0].trigger()

    on_screen = [w for w in qapp.topLevelWidgets()
                 if isinstance(w, nestcal_tray.ReminderWindow) and w.isVisible()]
    assert on_screen == [original]


def test_poll_now_fetches_the_feed_again(feed_server, start_app):
    feed_server.body = calendar()
    app = start_app()
    app.wait_for_polls(1)
    requests_before = feed_server.requests

    poll_now = next(a for a in app.open_menu() if a.text() == "Poll now")
    poll_now.trigger()
    app.wait_for_polls(2)

    assert feed_server.requests == requests_before + 1


def test_unreachable_feed_leaves_the_app_running_and_recovers_when_the_feed_returns(feed_server, start_app):
    feed_server.status = 500
    app = start_app()
    app.wait_for_polls(1)
    assert app.tooltip == "nestcal - no upcoming events"
    assert app.windows == {}

    feed_server.status = 200
    feed_server.body = calendar(event("e1", "Standup", DUE_SOON))
    app.tray_app.poller.poll_now()
    app.wait_for_polls(2)

    assert len(app.windows) == 1


def test_tray_has_an_icon_and_the_menu_attached(feed_server, start_app):
    feed_server.body = calendar()
    app = start_app()

    assert not app.tray_app.tray.icon().isNull()
    assert app.tray_app.tray.contextMenu() is app.tray_app.menu
