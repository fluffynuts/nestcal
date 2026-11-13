import os
from datetime import timedelta

import nestcal_core
from ics import calendar, event

SOON = timedelta(hours=3)


def calendars_in_ui(app):
    return app.tray_app.main_window.calendars_tab.calendars


def test_the_calendars_tab_starts_with_the_configured_calendars(feed_server, start_app):
    app = start_app()

    assert calendars_in_ui(app) == [("work", feed_server.url)]


def test_saving_a_calendar_from_the_ui_makes_the_app_poll_it(qtbot, feed_server, start_app):
    feed_server.body = calendar()
    app = start_app()
    app.wait_for_polls(1)
    requests_before = feed_server.requests

    nestcal_core.save_calendars([("work", feed_server.url), ("second", feed_server.url + "?b")])

    qtbot.waitUntil(lambda: feed_server.requests >= requests_before + 2, timeout=10_000)
    assert [f.label for f in app.tray_app.feeds] == ["work", "second"]


def test_editing_the_file_by_hand_updates_the_app_and_the_tab(qtbot, feed_server, start_app):
    feed_server.body = calendar(event("e1", "Planning", SOON))
    app = start_app()
    app.wait_for_polls(1)

    app.config_path.write_text("[calendars]\nrenamed = " + feed_server.url + "\n")

    qtbot.waitUntil(lambda: calendars_in_ui(app) == [("renamed", feed_server.url)], timeout=10_000)
    assert [f.label for f in app.tray_app.feeds] == ["renamed"]


def test_an_editor_that_replaces_the_file_is_still_noticed_every_time(qtbot, feed_server, start_app):
    app = start_app()
    for name in ("first", "second"):
        replacement = app.config_path.with_name("nestcal.ini.new")
        replacement.write_text("[calendars]\n" + name + " = " + feed_server.url + "\n")
        os.replace(replacement, app.config_path)

        qtbot.waitUntil(lambda: calendars_in_ui(app) == [(name, feed_server.url)], timeout=10_000)


def test_removing_the_last_calendar_by_hand_is_applied(qtbot, feed_server, start_app):
    app = start_app()

    app.config_path.write_text("[calendars]\n")

    qtbot.waitUntil(lambda: calendars_in_ui(app) == [], timeout=10_000)
    assert app.tray_app.feeds == []


def test_a_broken_file_keeps_the_last_good_calendars_and_says_so_in_the_window(qtbot, feed_server, start_app):
    app = start_app()
    window = app.tray_app.main_window

    app.config_path.write_text("this is not an ini file\n")

    qtbot.waitUntil(lambda: not window.problem_label.isHidden(), timeout=10_000)
    assert "still using the settings from before" in window.problem_label.text()
    assert calendars_in_ui(app) == [("work", feed_server.url)]
    assert [f.label for f in app.tray_app.feeds] == ["work"]


def test_fixing_a_broken_file_clears_the_message_and_applies_it(qtbot, feed_server, start_app):
    app = start_app()
    window = app.tray_app.main_window
    app.config_path.write_text("this is not an ini file\n")
    qtbot.waitUntil(lambda: not window.problem_label.isHidden(), timeout=10_000)

    app.config_path.write_text("[calendars]\nfixed = " + feed_server.url + "\n")

    qtbot.waitUntil(lambda: window.problem_label.isHidden(), timeout=10_000)
    assert calendars_in_ui(app) == [("fixed", feed_server.url)]


# --- settings apply live ---

def test_the_preferences_tab_starts_with_the_configured_settings(start_app, feed_server):
    app = start_app(lead_minutes=4, snooze_minutes=3)

    tab = app.tray_app.main_window.preferences_tab
    assert tab.spins["lead_minutes"].value() == 4
    assert tab.spins["snooze_minutes"].value() == 3


def test_saving_in_the_preferences_tab_applies_without_a_restart(qtbot, feed_server, start_app):
    app = start_app()
    tab = app.tray_app.main_window.preferences_tab

    tab.spins["lead_minutes"].setValue(9)
    tab.spins["snooze_minutes"].setValue(6)
    tab.spins["check_interval"].setValue(2)
    tab.save_button.click()

    qtbot.waitUntil(lambda: app.tray_app.snooze_minutes == 6, timeout=10_000)
    assert app.tray_app.lead == timedelta(minutes=9)
    assert app.tray_app.timer.interval() == 2000


def test_a_reminder_opened_after_a_change_uses_the_new_snooze(qtbot, feed_server, start_app):
    from ics import calendar, event
    feed_server.body = calendar(event("e1", "Standup", timedelta(minutes=1)))
    app = start_app()
    app.config_path.write_text(app.config_path.read_text().replace("snooze_minutes = 1", "snooze_minutes = 8"))
    qtbot.waitUntil(lambda: app.tray_app.snooze_minutes == 8, timeout=10_000)
    app.wait_for_polls(1)
    app.tray_app.windows.clear()

    app.tray_app.open_event(app.tray_app.events[0])

    [window] = app.windows.values()
    assert window.snooze_ms == 8 * 60 * 1000


def test_hand_editing_a_setting_updates_the_app_and_the_tab(qtbot, feed_server, start_app):
    app = start_app()

    app.config_path.write_text(app.config_path.read_text().replace("lead_minutes = 2", "lead_minutes = 11"))

    qtbot.waitUntil(lambda: app.tray_app.lead == timedelta(minutes=11), timeout=10_000)
    assert app.tray_app.main_window.preferences_tab.spins["lead_minutes"].value() == 11


def test_changing_the_poll_settings_polls_again_straight_away(qtbot, feed_server, start_app):
    feed_server.body = calendar()
    app = start_app()
    app.wait_for_polls(1)
    before = feed_server.requests

    app.config_path.write_text(app.config_path.read_text().replace("window_hours = 24", "window_hours = 48"))

    qtbot.waitUntil(lambda: feed_server.requests > before, timeout=10_000)
    assert app.tray_app.poller.window_hours == 48


def test_a_setting_that_makes_no_sense_keeps_the_old_settings_and_says_so(qtbot, feed_server, start_app):
    app = start_app()
    window = app.tray_app.main_window

    app.config_path.write_text(app.config_path.read_text().replace("lead_minutes = 2", "lead_minutes = soon"))

    qtbot.waitUntil(lambda: not window.problem_label.isHidden(), timeout=10_000)
    assert "lead_minutes must be a number" in window.problem_label.text()
    assert app.tray_app.lead == timedelta(minutes=2)


def test_update_checking_can_be_turned_off(feed_server, start_app, monkeypatch):
    import nestcal_tray
    started = []
    monkeypatch.setattr(nestcal_tray.UpdateChecker, "start", lambda self: started.append(True))

    start_app(check_for_updates="false")

    assert started == []


def test_update_checking_runs_by_default(feed_server, start_app, monkeypatch):
    import nestcal_tray
    started = []
    monkeypatch.setattr(nestcal_tray.UpdateChecker, "start", lambda self: started.append(True))

    start_app()

    assert started == [True]


def test_turning_update_checking_on_checks_straight_away(qtbot, feed_server, start_app, monkeypatch):
    import nestcal_tray
    started = []
    monkeypatch.setattr(nestcal_tray.UpdateChecker, "start", lambda self: started.append(True))
    app = start_app(check_for_updates="false")

    tab = app.tray_app.main_window.preferences_tab
    tab.updates_checkbox.setChecked(True)
    tab.save_button.click()

    qtbot.waitUntil(lambda: started == [True], timeout=10_000)


def test_events_fetched_appear_in_the_events_tab(qtbot, feed_server, start_app):
    feed_server.body = calendar(event("e1", "Planning", SOON))
    app = start_app()
    app.wait_for_polls(1)

    tab = app.tray_app.main_window.events_tab
    assert [tab.table.item(r, 1).text() for r in range(tab.table.rowCount())] == ["Planning"]
