import nestcal_tray

Reason = nestcal_tray.QSystemTrayIcon.ActivationReason if nestcal_tray.PYQT == 6 else nestcal_tray.QSystemTrayIcon


def test_the_window_is_not_shown_until_asked_for(feed_server, start_app):
    app = start_app()

    assert not app.tray_app.main_window.isVisible()


def test_window_has_a_tab_each_for_events_preferences_and_calendars(feed_server, start_app):
    app = start_app()

    tabs = app.tray_app.main_window.tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Events", "Preferences", "Calendars"]


def test_open_nestcal_is_the_first_menu_item_and_opens_the_window(feed_server, start_app):
    app = start_app()

    first = app.open_menu()[0]
    assert first.text() == "Open nestcal"
    first.trigger()

    assert app.tray_app.main_window.isVisible()


def test_clicking_the_tray_icon_opens_the_window(feed_server, start_app):
    app = start_app()

    app.tray_app.tray.activated.emit(Reason.Trigger)

    assert app.tray_app.main_window.isVisible()


def test_double_clicking_the_tray_icon_opens_the_window(feed_server, start_app):
    app = start_app()

    app.tray_app.tray.activated.emit(Reason.DoubleClick)

    assert app.tray_app.main_window.isVisible()


def test_other_tray_gestures_do_not_open_the_window(feed_server, start_app):
    app = start_app()

    app.tray_app.tray.activated.emit(Reason.Context)
    app.tray_app.tray.activated.emit(Reason.MiddleClick)

    assert not app.tray_app.main_window.isVisible()


def test_closing_the_window_hides_it_and_the_app_keeps_running(qapp, feed_server, start_app):
    app = start_app()
    app.tray_app.show_main_window()

    app.tray_app.main_window.close()

    assert not app.tray_app.main_window.isVisible()
    assert app.tray_app.poller.isRunning()


def test_the_window_can_be_reopened_after_closing(feed_server, start_app):
    app = start_app()
    app.tray_app.show_main_window()
    app.tray_app.main_window.close()

    app.tray_app.show_main_window()

    assert app.tray_app.main_window.isVisible()
