"""Render the last run as Markdown for the GitHub Actions job summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "output/latest.json")
    if not path.exists():
        print("No output produced -- the scrape step did not complete.")
        return 0

    data = json.loads(path.read_text(encoding="utf-8"))
    m, jobs = data["run_metadata"], data["jobs"]

    print("## Job scrape\n")
    print(f"- **Companies:** {m['companies_succeeded']}/{m['companies_attempted']} succeeded")
    print(f"- **Postings seen:** {m['total_postings_seen']}")
    print(f"- **Matched:** {m['total_postings_matched']}")
    if m.get("uk_filter_enabled"):
        print(f"- **Dropped as non-UK:** {m.get('total_postings_excluded_non_uk', 0)}")
    print(f"- **Window:** {m['run_started_utc']} → {m['run_finished_utc']}\n")

    if jobs:
        print("### Matches\n")
        print("| Company | Title | Location | Arrangement | Salary |")
        print("| --- | --- | --- | --- | --- |")
        for j in jobs:
            loc = j["location"] or "—"
            if j.get("location_region") == "unknown":
                loc += " _(region unconfirmed)_"
            arr = j["work_arrangement"] or "unknown"
            if j["work_arrangement_confidence"] != "stated":
                arr += f" _({j['work_arrangement_confidence']})_"
            title = f"[{j['title']}]({j['url']})"
            print(
                f"| {j['company']} | {title} | {loc} | "
                f"{arr} | {j['salary_raw'] or '—'} |"
            )
        print()

    if m.get("companies_failed"):
        print("### Failed — check these manually\n")
        for f in m["companies_failed"]:
            print(f"- **{f['name']}** ({f['url']}): `{f['error']}`")
        print()

    if m.get("companies_no_postings"):
        print("### No postings found\n")
        print("Loaded fine but yielded nothing — either genuinely not hiring, ")
        print("or the page changed shape.\n")
        for c in m["companies_no_postings"]:
            print(f"- {c['name']} ({c['url']})")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
