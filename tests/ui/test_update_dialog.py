import nestcal_tray
from nestcal_update import RELEASES_URL


def dialog_buttons(dialog) -> dict:
    return {b.text(): b for b in dialog.buttons()}


def test_update_dialog_offers_the_releases_page_and_dismissal(start_app, opened_urls):
    app = start_app()

    app.tray_app.show_update_dialog("v0.1.9")

    dialog = app.tray_app.update_dialog
    assert dialog.isVisible()
    assert "v0.1.9" in dialog.text()
    assert set(dialog_buttons(dialog)) == {"Open releases page", "Dismiss"}


def test_open_releases_page_button_opens_the_releases_page(start_app, opened_urls):
    app = start_app()
    app.tray_app.show_update_dialog("v0.1.9")

    dialog = app.tray_app.update_dialog

    dialog_buttons(dialog)["Open releases page"].click()

    assert opened_urls == [RELEASES_URL]
    assert not dialog.isVisible()


def test_dismiss_button_opens_nothing(start_app, opened_urls):
    app = start_app()
    app.tray_app.show_update_dialog("v0.1.9")

    dialog = app.tray_app.update_dialog

    dialog_buttons(dialog)["Dismiss"].click()

    assert opened_urls == []
    assert not dialog.isVisible()


def checker_results(monkeypatch, running: str, latest: str | None) -> list[str]:
    monkeypatch.setattr(nestcal_tray, "VERSION", running)
    monkeypatch.setattr(nestcal_tray, "fetch_latest_version", lambda logger: latest)
    checker = nestcal_tray.UpdateChecker(nestcal_tray.Logger(False))
    emitted = []
    checker.update_available.connect(emitted.append)
    checker._check()
    return emitted


def test_checker_announces_a_newer_release(qapp, monkeypatch):
    assert checker_results(monkeypatch, "0.1.5", "v0.1.6") == ["v0.1.6"]


def test_checker_announces_a_newer_release_to_a_beta_build(qapp, monkeypatch):
    assert checker_results(monkeypatch, "0.1.5-beta", "v0.1.6") == ["v0.1.6"]


def test_checker_is_quiet_when_up_to_date_or_ahead_or_offline(qapp, monkeypatch):
    assert checker_results(monkeypatch, "0.1.6", "v0.1.6") == []
    assert checker_results(monkeypatch, "0.1.7", "v0.1.6") == []
    assert checker_results(monkeypatch, "0.1.5", None) == []


def test_checker_never_asks_github_when_running_an_unstamped_build(qapp, monkeypatch):
    def fail(logger):
        raise AssertionError("an unstamped build must not contact GitHub")
    monkeypatch.setattr(nestcal_tray, "VERSION", "dev")
    monkeypatch.setattr(nestcal_tray, "fetch_latest_version", fail)
    nestcal_tray.UpdateChecker(nestcal_tray.Logger(False))._check()


def test_checker_delivers_its_result_to_the_ui_thread_when_started(qtbot, monkeypatch):
    monkeypatch.setattr(nestcal_tray, "VERSION", "0.1.5")
    monkeypatch.setattr(nestcal_tray, "fetch_latest_version", lambda logger: "v0.1.6")
    checker = nestcal_tray.UpdateChecker(nestcal_tray.Logger(False))

    with qtbot.waitSignal(checker.update_available, timeout=5_000) as announced:
        checker.start()

    assert announced.args == ["v0.1.6"]
