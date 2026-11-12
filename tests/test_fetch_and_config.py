import os
import sys

import pytest
import requests

import nestcal_core
from nestcal_core import (
    Feed, add_calendar, fetch_feed, get_feeds, get_setting, load_config, validate_calendar,
)


class FakeResponse:
    def __init__(self, status_code=200, content=b"ICS", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


@pytest.fixture
def requests_get(monkeypatch):
    calls = []

    def install(response=None, error=None):
        def fake_get(url, headers, timeout):
            calls.append({"url": url, "headers": headers, "timeout": timeout})
            if error:
                raise error
            return response
        monkeypatch.setattr(nestcal_core.requests, "get", fake_get)
        return calls
    return install


class TestFetchFeed:
    def test_returns_the_body_and_remembers_the_validators(self, requests_get, logger):
        requests_get(FakeResponse(headers={"ETag": "abc", "Last-Modified": "yesterday"}))
        feed = Feed("work", "https://example.com/a.ics")
        assert fetch_feed(feed, logger) == b"ICS"
        assert (feed.etag, feed.last_modified) == ("abc", "yesterday")

    def test_conditional_request_sends_the_validators(self, requests_get, logger):
        calls = requests_get(FakeResponse())
        feed = Feed("work", "https://example.com/a.ics", etag="abc", last_modified="yesterday")
        fetch_feed(feed, logger, conditional=True)
        assert calls[0]["headers"]["If-None-Match"] == "abc"
        assert calls[0]["headers"]["If-Modified-Since"] == "yesterday"

    def test_unconditional_request_sends_no_validators(self, requests_get, logger):
        calls = requests_get(FakeResponse())
        feed = Feed("work", "https://example.com/a.ics", etag="abc", last_modified="yesterday")
        fetch_feed(feed, logger, conditional=False)
        assert "If-None-Match" not in calls[0]["headers"]
        assert "If-Modified-Since" not in calls[0]["headers"]

    @pytest.mark.parametrize("status", [304, 404, 500])
    def test_non_200_gives_none(self, requests_get, logger, status):
        requests_get(FakeResponse(status_code=status))
        assert fetch_feed(Feed("work", "https://example.com/a.ics"), logger) is None

    def test_network_error_gives_none_and_is_logged(self, requests_get, logger, capsys):
        requests_get(error=requests.ConnectionError("boom"))
        assert fetch_feed(Feed("work", "https://example.com/a.ics"), logger) is None
        assert "work: fetch error" in capsys.readouterr().err


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / ".config" / "nestcal.ini"
    monkeypatch.setattr(nestcal_core, "CONFIG_PATH", path)
    return path


class TestLoadConfig:
    def test_missing_config_creates_a_stub_with_defaults_and_no_feeds(self, config_path, logger):
        config = load_config(logger)
        assert config_path.exists()
        assert get_feeds(config, logger) == []
        assert get_setting(config, "lead_minutes") == "2"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
    def test_created_stub_is_private_because_it_holds_secret_urls(self, config_path, logger):
        load_config(logger)
        assert config_path.stat().st_mode & 0o777 == 0o600

    def test_percent_signs_in_a_hand_written_link_are_read_literally(self, config_path, logger):
        config_path.parent.mkdir(parents=True)
        config_path.write_text("[calendars]\nWork = https://example.com/a%40b/basic.ics\n")
        os.chmod(config_path, 0o600)
        assert get_feeds(load_config(logger), logger)[0].url == "https://example.com/a%40b/basic.ics"

    def test_existing_config_is_read_and_never_overwritten(self, config_path, logger):
        config_path.parent.mkdir(parents=True)
        config_path.write_text("[settings]\nlead_minutes = 7\n\n[calendars]\nWork = https://example.com/a.ics\n")
        os.chmod(config_path, 0o600)
        config = load_config(logger)
        assert get_setting(config, "lead_minutes") == "7"
        assert "Work" in config["calendars"]

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
    def test_group_readable_config_gets_a_warning(self, config_path, logger, capsys):
        config_path.parent.mkdir(parents=True)
        config_path.write_text("[calendars]\n")
        os.chmod(config_path, 0o644)
        load_config(logger)
        assert "group/other-accessible" in capsys.readouterr().err


class TestFeedsAndSettings:
    def test_calendar_labels_keep_their_case_and_blank_urls_are_skipped(self, config_path, logger):
        config_path.parent.mkdir(parents=True)
        config_path.write_text("[calendars]\nWork = https://example.com/a.ics\nHome =\n")
        os.chmod(config_path, 0o600)
        feeds = get_feeds(load_config(logger), logger)
        assert [(f.label, f.url) for f in feeds] == [("Work", "https://example.com/a.ics")]

    def test_unset_settings_fall_back_to_defaults(self, config_path, logger):
        config = load_config(logger)
        assert get_setting(config, "poll_interval") == "300"
        assert get_setting(config, "snooze_minutes") == "1"


class TestAddCalendar:
    URL = "https://calendar.google.com/calendar/ical/x/basic.ics"

    def test_added_calendar_is_read_back_as_a_feed_in_a_fresh_stub(self, config_path, logger):
        load_config(logger)
        add_calendar("work", self.URL)
        feeds = get_feeds(load_config(logger), logger)
        assert [(f.label, f.url) for f in feeds] == [("work", self.URL)]

    def test_the_stub_keeps_its_comments_and_settings(self, config_path, logger):
        load_config(logger)
        before = config_path.read_text()
        add_calendar("work", self.URL)
        after = config_path.read_text()
        assert after.startswith(before.split("[calendars]")[0])
        assert "# personal = " in after

    def test_creates_a_private_file_when_there_is_none(self, config_path, logger):
        add_calendar("work", self.URL)
        assert [f.label for f in get_feeds(load_config(logger), logger)] == ["work"]
        if sys.platform != "win32":
            assert config_path.stat().st_mode & 0o777 == 0o600

    def test_adds_the_section_when_the_file_has_none(self, config_path, logger):
        config_path.parent.mkdir(parents=True)
        config_path.write_text("[settings]\nlead_minutes = 7")
        os.chmod(config_path, 0o600)
        add_calendar("work", self.URL)
        config = load_config(logger)
        assert get_setting(config, "lead_minutes") == "7"
        assert [f.label for f in get_feeds(config, logger)] == ["work"]

    def test_existing_calendars_are_kept(self, config_path, logger):
        config_path.parent.mkdir(parents=True)
        config_path.write_text("[calendars]\nHome = https://example.com/h.ics\n\n[settings]\nlead_minutes = 7\n")
        os.chmod(config_path, 0o600)
        add_calendar("work", self.URL)
        config = load_config(logger)
        assert {f.label for f in get_feeds(config, logger)} == {"Home", "work"}
        assert get_setting(config, "lead_minutes") == "7"

    def test_webcal_links_are_saved_as_https(self, config_path, logger):
        add_calendar("work", "webcal://example.com/a.ics")
        assert get_feeds(load_config(logger), logger)[0].url == "https://example.com/a.ics"

    def test_percent_escapes_in_the_link_survive_a_round_trip(self, config_path, logger):
        url = "https://calendar.google.com/calendar/ical/davyd.mccoll%40codeo.co.za/private-x/basic.ics"
        add_calendar("work", url)
        assert "davyd.mccoll%40codeo.co.za" in config_path.read_text()
        assert get_feeds(load_config(logger), logger)[0].url == url

    def test_invalid_input_raises_and_writes_nothing(self, config_path):
        with pytest.raises(ValueError):
            add_calendar("work", "not a link")
        assert not config_path.exists()


class TestValidateCalendar:
    @pytest.mark.parametrize("label,url", [
        ("", "https://example.com/a.ics"),
        ("   ", "https://example.com/a.ics"),
        ("a=b", "https://example.com/a.ics"),
        ("a:b", "https://example.com/a.ics"),
        ("#work", "https://example.com/a.ics"),
        ("work", ""),
        ("work", "example.com/a.ics"),
        ("work", "ftp://example.com/a.ics"),
        ("work", "https://"),
    ])
    def test_rejects_with_a_message(self, label, url):
        assert validate_calendar(label, url)

    def test_accepts_a_plain_name_and_https_link(self):
        assert validate_calendar("work", " https://example.com/a.ics ") is None
