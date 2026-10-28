import pytest
import requests

import nestcal_update
from nestcal_update import fetch_latest_version, is_newer, parse_version


class TestParseVersion:
    @pytest.mark.parametrize("text, expected", [
        ("0.1.42", (0, 1, 42)),
        ("v0.1.42", (0, 1, 42)),
        (" v1.2 ", (1, 2)),
    ])
    def test_reads_numeric_versions_with_optional_v_prefix(self, text, expected):
        assert parse_version(text) == expected

    @pytest.mark.parametrize("text", ["dev", "", "v", "1.2.x", "v1..2", "latest"])
    def test_anything_else_is_none(self, text):
        assert parse_version(text) is None


class TestIsNewer:
    @pytest.mark.parametrize("latest, current", [
        ("v0.1.43", "0.1.42"),
        ("v0.1.10", "0.1.9"),
        ("v0.2.1", "0.1.99"),
        ("v1.0.0", "0.9.9"),
    ])
    def test_true_when_latest_is_greater_numerically(self, latest, current):
        assert is_newer(latest, current)

    @pytest.mark.parametrize("latest, current", [
        ("v0.1.42", "0.1.42"),
        ("v0.1.41", "0.1.42"),
        ("v0.1.9", "0.1.10"),
    ])
    def test_false_when_same_or_older(self, latest, current):
        assert not is_newer(latest, current)

    def test_a_dev_build_is_never_told_to_update(self):
        assert not is_newer("v0.1.43", "dev")

    def test_an_unreadable_latest_tag_is_ignored(self):
        assert not is_newer("nightly", "0.1.42")


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


@pytest.fixture
def requests_get(monkeypatch):
    calls = []

    def install(response=None, error=None):
        def fake_get(url, headers, timeout):
            calls.append({"url": url, "headers": headers, "timeout": timeout})
            if error:
                raise error
            return response
        monkeypatch.setattr(nestcal_update.requests, "get", fake_get)
        return calls
    return install


class TestFetchLatestVersion:
    def test_returns_the_latest_release_tag(self, requests_get, logger):
        calls = requests_get(FakeResponse(payload={"tag_name": "v0.1.43"}))
        assert fetch_latest_version(logger) == "v0.1.43"
        assert calls[0]["url"] == nestcal_update.LATEST_RELEASE_API_URL

    def test_network_error_gives_none_and_is_logged(self, requests_get, logger, capsys):
        requests_get(error=requests.ConnectionError("boom"))
        assert fetch_latest_version(logger) is None
        assert "update check: fetch error" in capsys.readouterr().err

    @pytest.mark.parametrize("status", [403, 404, 500])
    def test_non_200_gives_none_and_is_logged(self, requests_get, logger, capsys, status):
        requests_get(FakeResponse(status_code=status))
        assert fetch_latest_version(logger) is None
        assert f"unexpected status {status}" in capsys.readouterr().err

    def test_unparseable_body_gives_none_and_is_logged(self, requests_get, logger, capsys):
        requests_get(FakeResponse(json_error=ValueError("not json")))
        assert fetch_latest_version(logger) is None
        assert "unreadable response" in capsys.readouterr().err

    @pytest.mark.parametrize("payload", [{}, {"tag_name": None}, {"tag_name": 5}, ["v0.1.43"]])
    def test_missing_or_malformed_tag_gives_none(self, requests_get, logger, payload):
        requests_get(FakeResponse(payload=payload))
        assert fetch_latest_version(logger) is None
