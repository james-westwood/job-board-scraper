"""Validate a run's output against the shape the consuming Claude session expects.

Run in CI after every scrape. The consuming side has no way to tell a malformed
file from a bad week, so a schema break must fail loudly here instead.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
JOB_ID = re.compile(r"^scrape:[a-z0-9-]+:[0-9a-f]{12}$")
ARRANGEMENTS = {"remote", "hybrid", "onsite", None}
# "non_uk" must never appear: those are filtered out before output.
REGIONS = {"uk", "unknown"}
CONFIDENCES = {"stated", "inferred", "unknown"}

META_FIELDS = {
    "run_started_utc": str,
    "run_finished_utc": str,
    "scraper_version": str,
    "companies_attempted": int,
    "companies_succeeded": int,
    "total_postings_seen": int,
    "total_postings_matched": int,
    "companies_failed": list,
}

JOB_FIELDS = {
    "company": (str,),
    "title": (str,),
    "location": (str, type(None)),
    "location_region": (str,),
    "work_arrangement": (str, type(None)),
    "work_arrangement_detail": (str, type(None)),
    "work_arrangement_confidence": (str,),
    "salary_raw": (str, type(None)),
    "salary_min_gbp": (int, type(None)),
    "salary_max_gbp": (int, type(None)),
    "url": (str,),
    "job_id": (str,),
    "scraped_at_utc": (str,),
    "matched_keyword": (str,),
}


def validate(path: Path) -> list[str]:
    errors: list[str] = []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"{path}: not valid JSON: {e}"]

    if not isinstance(data, dict):
        return [f"{path}: top level must be an object"]
    for key in ("run_metadata", "jobs"):
        if key not in data:
            errors.append(f"missing top-level key: {key}")
    if errors:
        return errors

    meta = data["run_metadata"]
    for field, typ in META_FIELDS.items():
        if field not in meta:
            errors.append(f"run_metadata missing {field}")
        elif not isinstance(meta[field], typ):
            errors.append(
                f"run_metadata.{field} should be {typ.__name__}, got {type(meta[field]).__name__}"
            )

    for field in ("run_started_utc", "run_finished_utc"):
        if isinstance(meta.get(field), str) and not ISO_UTC.match(meta[field]):
            errors.append(f"run_metadata.{field} is not ISO-8601 UTC: {meta[field]!r}")

    for i, f in enumerate(meta.get("companies_failed") or []):
        if not isinstance(f, dict):
            errors.append(f"companies_failed[{i}] must be an object")
            continue
        for key in ("name", "url", "error"):
            if not isinstance(f.get(key), str) or not f[key]:
                errors.append(f"companies_failed[{i}] missing/blank {key}")

    if isinstance(meta.get("companies_succeeded"), int) and isinstance(
        meta.get("companies_attempted"), int
    ):
        if meta["companies_succeeded"] > meta["companies_attempted"]:
            errors.append("companies_succeeded exceeds companies_attempted")
        expected_failed = meta["companies_attempted"] - meta["companies_succeeded"]
        actual_failed = len(meta.get("companies_failed") or [])
        if expected_failed != actual_failed:
            errors.append(
                f"companies_failed has {actual_failed} entries but "
                f"{expected_failed} companies did not succeed"
            )

    jobs = data["jobs"]
    if not isinstance(jobs, list):
        return errors + ["jobs must be a list"]

    if isinstance(meta.get("total_postings_matched"), int) and meta[
        "total_postings_matched"
    ] != len(jobs):
        errors.append(
            f"total_postings_matched ({meta['total_postings_matched']}) "
            f"does not equal len(jobs) ({len(jobs)})"
        )

    seen_ids: set[str] = set()
    for i, job in enumerate(jobs):
        where = f"jobs[{i}]"
        if not isinstance(job, dict):
            errors.append(f"{where} must be an object")
            continue
        for field, types in JOB_FIELDS.items():
            if field not in job:
                errors.append(f"{where} missing {field}")
            elif not isinstance(job[field], types):
                errors.append(
                    f"{where}.{field} has type {type(job[field]).__name__}, "
                    f"expected {'/'.join(t.__name__ for t in types)}"
                )
        if isinstance(job.get("job_id"), str):
            if not JOB_ID.match(job["job_id"]):
                errors.append(f"{where}.job_id malformed: {job['job_id']!r}")
            if job["job_id"] in seen_ids:
                errors.append(f"{where}.job_id duplicated: {job['job_id']}")
            seen_ids.add(job["job_id"])
        if job.get("location_region") not in REGIONS:
            errors.append(
                f"{where}.location_region invalid: {job.get('location_region')!r} "
                f"(expected one of {sorted(REGIONS)})"
            )
        if job.get("work_arrangement") not in ARRANGEMENTS:
            errors.append(f"{where}.work_arrangement invalid: {job.get('work_arrangement')!r}")
        if job.get("work_arrangement_confidence") not in CONFIDENCES:
            errors.append(
                f"{where}.work_arrangement_confidence invalid: "
                f"{job.get('work_arrangement_confidence')!r}"
            )
        if isinstance(job.get("scraped_at_utc"), str) and not ISO_UTC.match(job["scraped_at_utc"]):
            errors.append(f"{where}.scraped_at_utc is not ISO-8601 UTC")
        lo, hi = job.get("salary_min_gbp"), job.get("salary_max_gbp")
        if isinstance(lo, int) and isinstance(hi, int) and lo > hi:
            errors.append(f"{where} salary_min_gbp {lo} exceeds salary_max_gbp {hi}")
        if (lo is not None or hi is not None) and not job.get("salary_raw"):
            errors.append(f"{where} has a parsed salary but no salary_raw to check it against")
        if not str(job.get("url", "")).startswith("http"):
            errors.append(f"{where}.url is not absolute: {job.get('url')!r}")

    return errors


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "output/latest.json")
    if not path.exists():
        print(f"FAIL: {path} does not exist")
        return 1

    errors = validate(path)
    if errors:
        print(f"FAIL: {path} has {len(errors)} schema problem(s):")
        for e in errors[:50]:
            print(f"  - {e}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    print(
        f"OK: {path} valid -- {len(data['jobs'])} jobs, "
        f"{data['run_metadata']['companies_succeeded']}/"
        f"{data['run_metadata']['companies_attempted']} companies succeeded."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
