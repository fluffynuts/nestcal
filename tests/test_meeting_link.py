import icalendar
import pytest

from nestcal_core import extract_meeting_link


def event(**properties):
    component = icalendar.Event()
    for name, value in properties.items():
        component[name.replace("_", "-")] = value
    return component


def test_google_conference_property_wins_over_everything(logger):
    component = event(X_GOOGLE_CONFERENCE="https://meet.google.com/aaa-bbbb-ccc",
                      LOCATION="https://zoom.us/j/1", URL="https://example.com")
    assert extract_meeting_link(component) == "https://meet.google.com/aaa-bbbb-ccc"


def test_conference_property_is_next(logger):
    component = event(CONFERENCE="https://meet.example.com/room", LOCATION="https://zoom.us/j/1")
    assert extract_meeting_link(component) == "https://meet.example.com/room"


def test_first_of_several_conference_values_is_used():
    component = event(CONFERENCE=["https://one.example.com", "https://two.example.com"])
    assert extract_meeting_link(component) == "https://one.example.com"


def test_conferencing_url_in_location():
    assert extract_meeting_link(event(LOCATION="Room 4 or https://zoom.us/j/123")) == "https://zoom.us/j/123"


def test_conferencing_url_in_description_with_trailing_punctuation_trimmed():
    component = event(DESCRIPTION="Join: https://teams.microsoft.com/l/meetup-join/abc.")
    assert extract_meeting_link(component) == "https://teams.microsoft.com/l/meetup-join/abc"


def test_subdomains_of_conferencing_hosts_match():
    assert extract_meeting_link(event(LOCATION="https://us02web.zoom.us/j/9")) == "https://us02web.zoom.us/j/9"


def test_conferencing_url_in_location_beats_url_property():
    component = event(LOCATION="https://zoom.us/j/1", URL="https://example.com/agenda")
    assert extract_meeting_link(component) == "https://zoom.us/j/1"


def test_url_property_beats_a_non_conferencing_url_in_location():
    component = event(LOCATION="https://maps.example.com/office", URL="https://example.com/agenda")
    assert extract_meeting_link(component) == "https://example.com/agenda"


def test_any_url_in_location_is_the_last_resort():
    assert extract_meeting_link(event(LOCATION="https://maps.example.com/office")) == "https://maps.example.com/office"


@pytest.mark.parametrize("host", ["https://evilzoom.us/j/1", "https://zoom.us.evil.example/j/1"])
def test_lookalike_hosts_are_not_treated_as_conferencing(host):
    assert extract_meeting_link(event(DESCRIPTION=host)) is None


def test_no_link_anywhere():
    assert extract_meeting_link(event(SUMMARY="Lunch", LOCATION="Kitchen")) is None
