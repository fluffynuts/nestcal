from datetime import timedelta

import nestcal_tray
from ics import all_day_event, calendar, event

DUE_SOON = timedelta(minutes=1)    # inside the default 2 minute lead window
NOT_YET = timedelta(hours=3)       # inside the lookahead window, outside the lead window


def buttons(window) -> dict:
    return {b.text(): b for b in window.findChildren(nestcal_tray.QPushButton)}


def labels(window) -> list[str]:
    return [label.text() for label in window.findChildren(nestcal_tray.QLabel)]


def test_meeting_inside_its_lead_window_pops_a_reminder(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Standup", DUE_SOON, location="https://meet.google.com/abc-defg-hij"))
    app = start_app()
    app.wait_for_polls(1)

    [window] = app.windows.values()
    assert window.isVisible()
    assert window.windowTitle() == "Meeting: Standup"
    assert "Standup" in labels(window)
    assert "(1 minute)" in labels(window)
    assert window.windowFlags() & nestcal_tray.STAY_ON_TOP


def test_meeting_further_away_than_the_lead_window_does_not_pop(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Planning", NOT_YET))
    app = start_app()
    app.wait_for_polls(1)

    assert app.windows == {}


def test_meeting_already_running_at_startup_still_pops(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Retro", -timedelta(minutes=5)))
    app = start_app()
    app.wait_for_polls(1)

    [window] = app.windows.values()
    assert "(now)" in labels(window)


def test_all_day_events_never_pop(feed_server, start_app):
    feed_server.body = calendar(all_day_event("e1", "Public holiday"))
    app = start_app()
    app.wait_for_polls(1)

    assert app.windows == {}


def test_reminder_with_a_link_has_a_join_button_that_opens_it_and_closes_the_reminder(
        feed_server, start_app, opened_urls):
    link = "https://meet.google.com/abc-defg-hij"
    feed_server.body = calendar(event("e1", "Standup", DUE_SOON, location=link))
    app = start_app()
    app.wait_for_polls(1)
    [window] = app.windows.values()

    buttons(window)["Join"].click()

    assert opened_urls == [link]
    assert app.windows == {}


def test_reminder_without_a_link_says_so_and_has_no_join_button(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Chat", DUE_SOON, location="Kitchen"))
    app = start_app()
    app.wait_for_polls(1)
    [window] = app.windows.values()

    assert "No meeting link" in labels(window)
    assert "Join" not in buttons(window)


def test_dismissed_reminder_closes_and_does_not_pop_again(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Standup", DUE_SOON))
    app = start_app()
    app.wait_for_polls(1)
    [window] = app.windows.values()

    buttons(window)["Dismiss"].click()
    app.tray_app.check_due()
    app.tray_app.check_due()

    assert app.windows == {}


def test_snoozed_reminder_hides_then_comes_back(qtbot, feed_server, start_app):
    feed_server.body = calendar(event("e1", "Standup", DUE_SOON))
    app = start_app()
    app.wait_for_polls(1)
    [window] = app.windows.values()
    window.snooze_ms = 50  # the real minimum is a minute; the behaviour is the same

    buttons(window)["Snooze 1m"].click()

    assert not window.isVisible()
    qtbot.waitUntil(window.isVisible, timeout=5_000)


def test_each_of_several_due_meetings_gets_its_own_reminder(feed_server, start_app):
    feed_server.body = calendar(event("e1", "First", DUE_SOON), event("e2", "Second", DUE_SOON))
    app = start_app()
    app.wait_for_polls(1)

    assert sorted(w.windowTitle() for w in app.windows.values()) == ["Meeting: First", "Meeting: Second"]


def test_meeting_added_to_the_feed_later_pops_once_discovered(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Planning", NOT_YET))
    app = start_app()
    app.wait_for_polls(1)
    assert app.windows == {}

    feed_server.body = calendar(event("e1", "Planning", NOT_YET), event("e2", "Urgent", DUE_SOON))
    app.tray_app.poller.poll_now()
    app.wait_for_polls(2)

    [window] = app.windows.values()
    assert window.windowTitle() == "Meeting: Urgent"


def test_rescheduled_meeting_pops_again_at_its_new_time(feed_server, start_app):
    feed_server.body = calendar(event("e1", "Standup", DUE_SOON))
    app = start_app()
    app.wait_for_polls(1)
    [window] = app.windows.values()
    buttons(window)["Dismiss"].click()

    feed_server.body = calendar(event("e1", "Standup", DUE_SOON + timedelta(minutes=1)))
    app.tray_app.poller.poll_now()
    app.wait_for_polls(2)

    assert len(app.windows) == 1
