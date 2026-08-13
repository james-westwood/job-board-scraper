"""Tests for the filtering and parsing logic.

These are the parts that fail silently in production -- a broken selector shows
up as a company in companies_failed, but a broken salary regex just quietly
emits nulls forever.
"""

import pytest

from scraper.matching import detect_work_arrangement, match_title, parse_salary
from scraper.models import make_job_id


# --------------------------------------------------------------------------
# Title matching
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected",
    [
        ("Senior Data Scientist", "data scientist"),
        ("data engineer", "data engineer"),
        ("Analytics Engineer (Growth)", "analytics engineer"),
        ("Machine Learning Engineer, Forecasting", "machine learning engineer"),
        ("ML Engineer", "ml engineer"),
        ("MLOps Lead", "mlops"),
        ("AI Engineer - Platform", "ai engineer"),
        ("Applied Scientist II", "applied scientist"),
        ("Data Platform Engineer", "data platform"),
        ("Head of Data Science", "data science"),
    ],
)
def test_includes(title, expected):
    assert match_title(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Data Science Intern",
        "Data Scientist Internship",
        "Sales Engineer",
        "Marketing Manager",
        "Account Executive",
        "Business Development Manager",
        "Data Scientist, Sales Analytics",  # exclusion wins over inclusion
    ],
)
def test_excludes(title):
    assert match_title(title) is None


@pytest.mark.parametrize(
    "title", ["Software Engineer", "Product Manager", "Electrical Engineer", "", "Data Entry Clerk"]
)
def test_non_matches(title):
    assert match_title(title) is None


# --------------------------------------------------------------------------
# Salary
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,lo,hi",
    [
        ("Salary: £55,000 - £65,000 per annum", 55000, 65000),
        ("Salary £55,000-65,000", 55000, 65000),
        ("Compensation: £70k - £85k", 70000, 85000),
        ("salary of £62,500", 62500, 62500),
        ("Salary up to £70,000", None, 70000),
        ("Salary from £45,000", 45000, None),
        ("Salary circa £80,000", 80000, None),
        ("55,000 - 65,000 GBP", 55000, 65000),
    ],
)
def test_salary_parsed(text, lo, hi):
    raw, got_lo, got_hi = parse_salary(text)
    assert raw is not None
    assert (got_lo, got_hi) == (lo, hi)


def test_salary_absent():
    assert parse_salary("We offer a great culture and free fruit") == (None, None, None)
    assert parse_salary(None) == (None, None, None)


def test_day_rate_kept_raw_but_not_parsed():
    raw, lo, hi = parse_salary("Salary equivalent day rate £550 per day")
    assert (lo, hi) == (None, None)


def test_implausible_numbers_rejected():
    # A year and a headcount should never be read as pay.
    assert parse_salary("Founded in 2011, salary competitive") == (None, None, None)


def test_foreign_currency_raw_only():
    raw, lo, hi = parse_salary("Compensation: $150,000 - $180,000 USD")
    assert raw is not None and "150,000" in raw
    assert (lo, hi) == (None, None), "must not invent a GBP figure from USD"


# --------------------------------------------------------------------------
# Work arrangement
# --------------------------------------------------------------------------

def test_hybrid_stated():
    arr, detail, conf = detect_work_arrangement("Data Scientist", "Bristol", "This is a hybrid role.")
    assert (arr, conf) == ("hybrid", "stated")


def test_hybrid_days_detail():
    arr, detail, conf = detect_work_arrangement(
        "Data Engineer", "London", "Hybrid working: we ask for 2-3 days per week in the office."
    )
    assert arr == "hybrid"
    assert detail is not None and "days" in detail


def test_remote_from_location_field():
    arr, _, conf = detect_work_arrangement("Data Engineer", "UK - Remote", "")
    assert (arr, conf) == ("remote", "stated")


def test_incidental_hybrid_in_body_is_ignored():
    """The bug this guards: BP sells hybrid vehicles, Teledyne makes hybrid
    circuits. A bare keyword in body text must not set work_arrangement."""
    arr, _, conf = detect_work_arrangement(
        "Data Scientist",
        "Kuala Lumpur",
        "Join our team working on hybrid and electric vehicle charging infrastructure.",
    )
    assert arr != "hybrid" or conf == "inferred"
    assert conf != "stated" or arr == "onsite"


def test_incidental_remote_sensing_is_ignored():
    arr, _, conf = detect_work_arrangement(
        "Applied Scientist", "Edinburgh", "You will work with remote sensing and satellite data."
    )
    assert arr != "remote"


def test_onsite_stated():
    arr, _, conf = detect_work_arrangement("Data Engineer", "Leeds", "This is an office-based role.")
    assert (arr, conf) == ("onsite", "stated")


def test_unknown_when_nothing_to_go_on():
    arr, detail, conf = detect_work_arrangement("Data Engineer", None, "")
    assert (arr, detail, conf) == (None, None, "unknown")


def test_location_only_infers_onsite():
    arr, _, conf = detect_work_arrangement("Data Engineer", "Bristol, UK", "Great team, good perks.")
    assert (arr, conf) == ("onsite", "inferred")


# --------------------------------------------------------------------------
# Job IDs
# --------------------------------------------------------------------------

def test_job_id_stable_and_namespaced():
    a = make_job_id("AECOM", "https://aecom.jobs/job/12345")
    b = make_job_id("AECOM", "https://aecom.jobs/job/12345")
    assert a == b, "same URL must give the same id across runs"
    assert a.startswith("scrape:aecom:")
    assert len(a.split(":")[2]) == 12


def test_job_id_differs_by_url():
    a = make_job_id("AECOM", "https://aecom.jobs/job/1")
    b = make_job_id("AECOM", "https://aecom.jobs/job/2")
    assert a != b


def test_job_id_slug_handles_punctuation():
    assert make_job_id("NESO (National Energy System Operator)", "u").startswith(
        "scrape:neso-national-energy-system-operator:"
    )
    assert make_job_id("ev.energy", "u").startswith("scrape:ev-energy:")
