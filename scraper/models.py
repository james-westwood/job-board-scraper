"""Data shapes shared by every adapter."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def company_slug(name: str) -> str:
    """'NESO (National Energy System Operator)' -> 'neso-national-energy-system-operator'."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unknown"


def make_job_id(company: str, url: str) -> str:
    """Stable across runs (same URL -> same id), namespaced so it cannot collide
    with the ATS-derived ids the consuming system already tracks."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"scrape:{company_slug(company)}:{digest}"


@dataclass
class Posting:
    """A job as first seen on a listing page, before enrichment."""

    title: str
    url: str
    location: str | None = None
    # Text already available from the listing (Workday et al. hand us the full
    # description for free); saves a detail fetch when populated.
    description: str | None = None


@dataclass
class Job:
    """A matched posting, in output shape."""

    company: str
    title: str
    location: str | None
    work_arrangement: str | None
    work_arrangement_detail: str | None
    work_arrangement_confidence: str
    salary_raw: str | None
    salary_min_gbp: int | None
    salary_max_gbp: int | None
    url: str
    job_id: str
    scraped_at_utc: str
    matched_keyword: str

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "title": self.title,
            "location": self.location,
            "work_arrangement": self.work_arrangement,
            "work_arrangement_detail": self.work_arrangement_detail,
            "work_arrangement_confidence": self.work_arrangement_confidence,
            "salary_raw": self.salary_raw,
            "salary_min_gbp": self.salary_min_gbp,
            "salary_max_gbp": self.salary_max_gbp,
            "url": self.url,
            "job_id": self.job_id,
            "scraped_at_utc": self.scraped_at_utc,
            "matched_keyword": self.matched_keyword,
        }


@dataclass
class CompanyResult:
    """Outcome of attempting one company."""

    name: str
    url: str
    postings_seen: int = 0
    jobs: list[Job] = field(default_factory=list)
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None
