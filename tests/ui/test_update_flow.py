from datetime import datetime, timedelta, timezone

import nestcal_tray
import nestcal_update
from nestcal_core import Logger
from nestcal_update import RELEASES_URL

T0 = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)


def start_with_clock(start_app, monkeypatch):
    shown = []
    monkeypatch.setattr(nestcal_tray.TrayApp, "show_update_dialog", lambda self, latest: shown.append(latest))
    app = start_app()
    app.tray_app.clock = lambda: app.now
    app.now = T0
    return app, shown


def test_a_newer_release_shows_the_link_and_prompts_once(start_app, monkeypatch):
    app, shown = start_with_clock(start_app, monkeypatch)

    app.tray_app.on_update_available("v0.9.0")

    assert shown == ["v0.9.0"]
    assert not app.tray_app.main_window.events_tab.update_label.isHidden()


def test_a_second_announcement_within_two_days_shows_the_link_but_not_the_dialog(start_app, monkeypatch):
    app, shown = start_with_clock(start_app, monkeypatch)
    app.tray_app.on_update_available("v0.9.0")

    app.now = T0 + timedelta(days=1)
    app.tray_app.on_update_available("v0.9.0")

    assert shown == ["v0.9.0"]
    assert not app.tray_app.main_window.events_tab.update_label.isHidden()


def test_the_dialog_returns_after_two_days_then_four_then_never(start_app, monkeypatch):
    app, shown = start_with_clock(start_app, monkeypatch)

    for days in (0, 2, 6, 7, 100):
        app.now = T0 + timedelta(days=days)
        app.tray_app.on_update_available("v0.9.0")

    assert shown == ["v0.9.0"] * 3


def test_the_schedule_survives_a_restart(start_app, monkeypatch):
    app, shown = start_with_clock(start_app, monkeypatch)
    app.tray_app.on_update_available("v0.9.0")

    second, shown_second = start_with_clock(start_app, monkeypatch)
    second.now = T0 + timedelta(hours=1)
    second.tray_app.on_update_available("v0.9.0")

    assert shown_second == []
    assert not second.tray_app.main_window.events_tab.update_label.isHidden()


def test_a_still_newer_release_prompts_again(start_app, monkeypatch):
    app, shown = start_with_clock(start_app, monkeypatch)
    app.tray_app.on_update_available("v0.9.0")

    app.now = T0 + timedelta(hours=1)
    app.tray_app.on_update_available("v0.9.1")

    assert shown == ["v0.9.0", "v0.9.1"]


def test_the_dialog_still_opens_the_releases_page(start_app, opened_urls):
    app = start_app()
    app.tray_app.on_update_available("v0.9.0")

    next(b for b in app.tray_app.update_dialog.buttons() if b.text() == "Open releases page").click()

    assert opened_urls == [RELEASES_URL]


def test_checking_repeats_daily_while_enabled(start_app, monkeypatch):
    started = []
    monkeypatch.setattr(nestcal_tray.UpdateChecker, "start", lambda self: started.append(True))

    app = start_app()

    assert app.tray_app.update_timer.isActive()
    assert app.tray_app.update_timer.interval() == 24 * 60 * 60 * 1000
    app.tray_app.update_timer.timeout.emit()
    assert started == [True, True]  # at startup, and the timer


def test_turning_update_checks_off_stops_the_timer_and_hides_the_link(start_app, monkeypatch):
    monkeypatch.setattr(nestcal_tray.UpdateChecker, "start", lambda self: None)
    monkeypatch.setattr(nestcal_tray.TrayApp, "show_update_dialog", lambda self, latest: None)
    app = start_app()
    app.tray_app.on_update_available("v0.9.0")
    tab = app.tray_app.main_window.preferences_tab

    tab.updates_checkbox.setChecked(False)
    tab.save_button.click()

    # Two things can go wrong, and a timeout alone can't say which: the save itself failing,
    # or the saved change never reaching the app. Say which.
    assert tab.error_label.text() == "", f"the save failed: {tab.error_label.text()}"
    assert "check_for_updates = false" in app.config_path.read_text(), "the save wrote nothing"

    def timer_stopped():
        assert not app.tray_app.update_timer.isActive(), (
            "the file was saved but the app did not apply it; "
            f"window banner: {app.tray_app.main_window.problem_label.text()!r}")
    app.wait_until(timer_stopped)
    assert app.tray_app.main_window.events_tab.update_label.isHidden()


def test_with_checks_off_there_is_no_timer(start_app, monkeypatch):
    monkeypatch.setattr(nestcal_tray.UpdateChecker, "start", lambda self: None)

    app = start_app(check_for_updates="false")

    assert not app.tray_app.update_timer.isActive()


def test_a_damaged_state_file_does_not_stop_the_update_prompt(start_app, monkeypatch):
    """An uncaught exception in a Qt slot aborts the real app, so this must not raise."""
    app, shown = start_with_clock(start_app, monkeypatch)
    nestcal_update.STATE_PATH.write_text('{"update_prompts": {"version": "v0.9.0", "count": 1}}')

    app.tray_app.on_update_available("v0.9.0")

    assert shown == ["v0.9.0"]


def test_remembering_an_update_prompt_does_not_make_the_app_reread_its_config(qtbot, start_app, monkeypatch):
    """The state file sits next to the config; writing it used to wake the config watcher."""
    reread = []
    monkeypatch.setattr(nestcal_tray.TrayApp, "on_config_changed", lambda self: reread.append(True))
    app, shown = start_with_clock(start_app, monkeypatch)

    with qtbot.waitSignal(app.tray_app.config_watcher._settle.timeout):
        app.tray_app.on_update_available("v0.9.0")

    assert nestcal_update.STATE_PATH.exists()
    assert reread == []
