"""Tests for near-miss detection.

Motivated by real listings the strict filter went blind to: NESO advertised
"Lead AI Architect" and "Data Assurance Lead" while the scraper reported zero
matches for NESO that week.
"""

import pytest

from scraper.matching import match_title, near_miss_token


@pytest.mark.parametrize(
    "title,token",
    [
        # The cases that prompted this feature.
        ("Lead AI Architect", "ai"),
        ("Data Assurance Lead", "data"),
        ("Investment Portfolio Data & Reporting Lead", "data"),
        # Other plausible adjacent roles.
        ("Head of Data", "data"),
        ("Data Architect", "data"),
        ("Analytics Manager", "analytics"),
        ("Quantitative Researcher", "quantitative"),
        ("Principal Statistical Modeller", "statistical"),
        ("Business Intelligence Developer", "business intelligence"),
        ("LLM Platform Lead", "llm"),
    ],
)
def test_near_misses_detected(title, token):
    assert match_title(title) is None, "precondition: not a strict match"
    assert near_miss_token(title) == token


@pytest.mark.parametrize(
    "title",
    [
        "Senior Data Engineer",
        "Machine Learning Engineer",
        "Applied Scientist",
        "Data Platform Lead",
    ],
)
def test_strict_matches_are_not_near_misses(title):
    """A real match belongs in jobs[], and must not be double-reported."""
    assert match_title(title) is not None
    assert near_miss_token(title) is None


@pytest.mark.parametrize(
    "title",
    [
        "Data Science Intern",
        "Data Analytics Internship",
        "Sales Engineer - Data Products",
        "Business Development Manager, Data",
    ],
)
def test_exclusions_do_not_return_via_near_misses(title):
    """An intern or sales role must not sneak back in through this door."""
    assert near_miss_token(title) is None


@pytest.mark.parametrize(
    "title",
    [
        "SCADA Systems Analyst",      # "data" must not match inside SCADA
        "Air Quality Officer",        # "ai" must not match inside Air
        "Senior Business Analyst",    # bare "analyst" is deliberately not a token
        "Compliance Analyst",
        "Customer Service Advisor",
        "Solar PV Electrician",
        "Power System Engineer",
        "Legal Counsel",
    ],
)
def test_unrelated_roles_are_not_near_misses(title):
    assert near_miss_token(title) is None


def test_empty_title():
    assert near_miss_token("") is None


def test_us_citizenship_requirement_reads_as_non_uk():
    """Teledyne's "AI Solution Analyst (US Citizenship Required)" listed a
    vague "5 Locations", so only the eligibility wording gives it away."""
    from scraper.location import NON_UK, classify_location

    assert (
        classify_location("5 Locations", "AI Solution Analyst (US Citizenship Required)")
        == NON_UK
    )


def test_privacy_footer_link_is_not_a_near_miss():
    """Teamtailor career sites carry a "Data & privacy" footer link."""
    from scraper.adapters.browser import _is_candidate

    assert _is_candidate("https://careers.fathom.global/data-privacy", "Data & privacy") is False
    assert _is_candidate("https://example.com/privacy", "Data & privacy") is False
    assert _is_candidate("https://example.com/cookie-policy", "Cookie Policy") is False
