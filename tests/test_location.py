"""Tests for UK location classification.

The trap this guards against is shared city names: Birmingham, Manchester,
Cambridge, Bristol, Durham and Worcester all exist on both sides of the
Atlantic, so a naive city list quietly lets US roles through.
"""

import pytest

from scraper.location import NON_UK, UK, UNKNOWN, classify_location


@pytest.mark.parametrize(
    "location",
    [
        "London",
        "Greater London",
        "Bristol, UK",
        "London, England, United Kingdom",
        "Leeds, West Yorkshire",
        "Edinburgh, Scotland",
        "Cardiff, Wales",
        "Belfast, Northern Ireland",
        "Milton Keynes",
        "UK - Remote",
        "Remote (United Kingdom)",
        "Swindon, Wiltshire",
    ],
)
def test_uk_locations(location):
    assert classify_location(location) == UK


@pytest.mark.parametrize(
    "location",
    [
        "USA - Remote",
        "United States",
        "Malaysia - Kuala Lumpur",
        "Brazil - São Paulo",
        "BR: Sao Paulo - BTC Technology",
        "US - Rancho Cordova, CA (TDY)",
        "Madrid",
        "Manila",
        "Ames, IA",
        "Sault Ste Marie, ON",
        "Dublin, Ireland",
        "Toronto, Canada",
        "Singapore",
        "Amsterdam, Netherlands",
    ],
)
def test_non_uk_locations(location):
    assert classify_location(location) == NON_UK


@pytest.mark.parametrize(
    "location",
    [
        "Birmingham, AL",
        "Manchester, NH",
        "Cambridge, MA",
        "Boston, MA",
        "Durham, NC",
        "Worcester, MA",
        "Newcastle, Australia",
    ],
)
def test_shared_city_names_resolve_to_non_uk(location):
    """The whole point: an explicit country or state signal must beat the city."""
    assert classify_location(location) == NON_UK


@pytest.mark.parametrize("location", [None, "", "Remote", "2 Locations", "Multiple locations", "EMEA"])
def test_ambiguous_is_unknown_not_dropped(location):
    assert classify_location(location) == UNKNOWN


def test_northern_ireland_beats_ireland():
    assert classify_location("Belfast, Northern Ireland") == UK
    assert classify_location("Dublin, Ireland") == NON_UK


def test_body_used_only_when_location_says_nothing():
    assert classify_location(None, "This role is based in our United Kingdom office.") == UK
    assert classify_location(None, "Our team is based in the United States.") == NON_UK
    # A decisive location field is not overridden by the description.
    assert classify_location("Madrid", "We also have a London office.") == NON_UK


def test_conflicting_signals_are_unknown():
    assert classify_location("UK / United States") == UNKNOWN


def test_body_with_both_countries_is_unknown():
    assert classify_location(None, "Offices in the United Kingdom and the United States.") == UNKNOWN


def test_header_location_beats_deep_boilerplate():
    """Real case from Overstory: a US/Canada-only role whose benefits blurb
    lists ten countries it has entities in, the UK among them. Only the header
    describes where the job actually is."""
    body = (
        "Staff Machine Learning Engineer - Wildfire. Remote: United States | Canada. Apply. "
        + "The climate crisis is the defining challenge of our time. " * 120
        + "We can employ people living and working in one of these: United States, "
        "the Netherlands, United Kingdom, Ireland, Estonia, Portugal, France, Sweden."
    )
    assert classify_location(None, body) == NON_UK
