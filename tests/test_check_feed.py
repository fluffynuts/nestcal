import requests

import nestcal_core
from nestcal_core import check_feed

ICS = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:1\r\nDTSTART:20300101T100000Z\r\n"
       b"SUMMARY:One\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:2\r\nDTSTART:20300102T100000Z\r\n"
       b"SUMMARY:Two\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


class Response:
    def __init__(self, status_code=200, content=ICS):
        self.status_code, self.content = status_code, content


def stub_get(monkeypatch, response=None, error=None):
    def get(url, **kwargs):
        if error:
            raise error
        return response
    monkeypatch.setattr(requests, "get", get)


def test_a_good_calendar_is_ok_and_counts_its_events(monkeypatch):
    stub_get(monkeypatch, Response())

    result = check_feed("https://example.com/a.ics")

    assert result.ok
    assert "2 events" in result.message


def test_a_calendar_with_one_event_is_singular(monkeypatch):
    stub_get(monkeypatch, Response(content=ICS.replace(b"BEGIN:VEVENT\r\nUID:2", b"BEGIN:VTODO\r\nUID:2")
                                   .replace(b"SUMMARY:Two\r\nEND:VEVENT", b"SUMMARY:Two\r\nEND:VTODO")))

    assert "1 event " in check_feed("https://example.com/a.ics").message + " "


def test_an_unreachable_server_is_not_ok_and_says_why(monkeypatch):
    stub_get(monkeypatch, error=requests.ConnectionError("no route to host"))

    result = check_feed("https://example.com/a.ics")

    assert not result.ok
    assert "reach" in result.message


def test_an_http_error_status_is_not_ok_and_says_which(monkeypatch):
    stub_get(monkeypatch, Response(status_code=404))

    result = check_feed("https://example.com/a.ics")

    assert not result.ok
    assert "404" in result.message


def test_something_that_is_not_a_calendar_is_not_ok(monkeypatch):
    stub_get(monkeypatch, Response(content=b"<html>sign in</html>"))

    result = check_feed("https://example.com/a.ics")

    assert not result.ok
    assert "calendar" in result.message


def test_webcal_links_are_fetched_as_https(monkeypatch):
    seen = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: seen.append(url) or Response())

    check_feed("webcal://example.com/a.ics")

    assert seen == ["https://example.com/a.ics"]
