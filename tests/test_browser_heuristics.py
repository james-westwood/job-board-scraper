"""Tests for the pure link/title heuristics in the browser adapter.

Each case here is a real failure seen against a live site during the build.
"""

import pytest

from scraper.adapters.browser import _best_title, _is_candidate


@pytest.mark.parametrize(
    "href,text",
    [
        # Standard shapes.
        ("https://careers.example.com/jobs/data-engineer", "Data Engineer"),
        ("https://jobs.ashbyhq.com/Lime/0bb8c755-c283", "Senior Data Engineer"),
        # OVO: bare requisition id, no /job/ segment at all.
        ("https://careers.ovo.com/senior-data-engineer/7771748", "Senior Data Engineer"),
        # Thames Water: opaque query-param id on an .aspx page.
        ("https://jobs.thameswater.co.uk/VacancyInformation.aspx?VId=38429", "Data Analyst"),
        # Backstop: URL gives nothing away, but the text is plainly a role.
        ("https://example.com/x7f2", "Machine Learning Engineer"),
    ],
)
def test_accepts_real_postings(href, text):
    assert _is_candidate(href, text) is True


@pytest.mark.parametrize(
    "href,text",
    [
        # Navigation chrome.
        ("https://careers.example.com/jobs", "Jobs"),
        ("https://careers.example.com/jobs", "View all"),
        ("https://example.com/careers/", "Careers"),
        ("https://example.com/apply", "Apply now"),
        # Editorial that happens to contain a keyword. Habitat Energy published
        # exactly this and it was matching as a vacancy.
        (
            "https://habitat.energy/data-science-optimisation-aditi-shenvi/",
            "The data science of optimisation: Q&A with Aditi Shenvi",
        ),
        ("https://example.com/blog/how-we-built-our-data-platform", "How we built our data platform"),
        ("https://example.com/news/2026/01/hiring-a-data-scientist", "Hiring a data scientist"),
        # Team directory entries pair a person's name with their job title, so
        # they look exactly like job cards. Real case from Fathom's site.
        (
            "https://careers.fathom.global/en-GB/people/3413712-alex-marshall",
            "Alex Marshall Senior Machine Learning Engineer",
        ),
        ("https://example.com/team/jane-smith", "Jane Smith Data Scientist"),
        ("https://example.com/about/leadership/head-of-data", "Head of Data Science"),
    ],
)
def test_rejects_non_postings(href, text):
    assert _is_candidate(href, text) is False


def test_irrelevant_jobs_are_still_candidates():
    """A posting we don't want is still a posting -- it must count towards
    postings_seen and get dropped by the title filter, not hidden here."""
    assert _is_candidate("https://example.com/jobs/warehouse-operative", "Warehouse Operative")


def test_editorial_filter_does_not_eat_real_titles():
    assert _is_candidate("https://example.com/jobs/1234", "Data Scientist, Forecasting & Optimisation")
    assert _is_candidate("https://example.com/jobs/1234", "Senior Data Engineer (12 month FTC)")


# --------------------------------------------------------------------------
# Title extraction
# --------------------------------------------------------------------------

def test_prefers_marked_up_heading():
    assert _best_title("Data Engineer", "Data Engineer Engineering Canada Full time") == "Data Engineer"


def test_falls_back_to_cutting_at_separator():
    # Ashby cards render as "Title • Department • Location • Contract".
    assert _best_title(None, "Data Engineer • Engineering • Canada") == "Data Engineer"
    assert _best_title("", "Senior Data Scientist | London | Hybrid") == "Senior Data Scientist"


def test_plain_title_passes_through():
    assert _best_title(None, "Analytics Engineer") == "Analytics Engineer"


def test_absurd_heading_is_ignored():
    long = "x" * 200
    assert _best_title(long, "Data Engineer") == "Data Engineer"
