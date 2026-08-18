"""File the weekly scrape into the career coach's evidence library.

Runs on coachbox, which is the single declared writer for the coach's vault
directory. It cannot run in GitHub Actions: the scraper runs in the cloud and
has no access to the vault or to the `cadence` package, so the workflow
publishes JSON and this pulls it.

Why the evidence library rather than the memory directory: `load_bundle()`
globs *.md in the memory dir and renders each one in full on every turn, so a
weekly report there would compound into the prompt forever. Evidence is loaded
on demand via recall, and only its one-line INDEX.md entry is always resident.

Why a fixed title with mode="replace": a dated title adds an INDEX.md line every
week, and the whole index sits in every prompt -- 52 lines a year, permanently.
One rolling document with the date in the description keeps it at one line.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAW_URL = (
    "https://raw.githubusercontent.com/james-westwood/job-board-scraper"
    "/main/output/latest.json"
)
DEFAULT_VAULT = Path("/home/deploy/vault/10_Work/Career_Coach")
EVIDENCE_TITLE = "Job scan"
SOURCE = "jobscanner"

# Older than this and the scrape has stopped running; say so in the report
# rather than presenting stale postings as current.
STALE_AFTER_DAYS = 8


def fetch(url: str) -> dict:
    # raw.githubusercontent caches for a few minutes; bust it so a run that
    # fires just after the scrape doesn't file last week's data.
    buster = int(datetime.now(timezone.utc).timestamp())
    req = urllib.request.Request(
        f"{url}?v={buster}", headers={"User-Agent": "cadence-jobscanner/1.0"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _fmt_job(j: dict) -> str:
    bits = [f"**{j['title']}** — {j['company']}"]
    loc = j.get("location")
    if loc:
        bits.append(loc)
    arr = j.get("work_arrangement")
    if arr:
        conf = j.get("work_arrangement_confidence")
        arr_txt = arr if conf == "stated" else f"{arr} (inferred)"
        detail = j.get("work_arrangement_detail")
        bits.append(f"{arr_txt}, {detail}" if detail else arr_txt)
    if j.get("salary_raw"):
        bits.append(j["salary_raw"])
    if j.get("location_region") == "unknown":
        bits.append("_UK eligibility unconfirmed_")
    return f"- {' · '.join(bits)}  \n  {j['url']}"


def build_report(data: dict) -> tuple[str, str, bool]:
    """Return (markdown, index_description, worth_a_nudge)."""
    m = data["run_metadata"]
    jobs = data.get("jobs", [])
    near = data.get("near_misses", [])
    failed = m.get("companies_failed") or []

    started = m["run_started_utc"]
    try:
        run_dt = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        run_dt = None
    stale = bool(run_dt and datetime.now(timezone.utc) - run_dt > timedelta(days=STALE_AFTER_DAYS))
    run_day = run_dt.strftime("%d %b %Y") if run_dt else started

    out = [
        f"# Job scan — {run_day}",
        "",
        "Automated scrape of tracked energy/climate employers whose careers sites have "
        "no public ATS API. Filtered to UK data/ML roles. Companion to the direct "
        "Greenhouse/Lever/Ashby/Workable checks.",
        "",
        f"Scanned {m['companies_succeeded']}/{m['companies_attempted']} companies, "
        f"{m['total_postings_seen']} postings seen.",
    ]

    if stale:
        out += [
            "",
            f"> **Stale.** This scrape last ran {run_day}, more than "
            f"{STALE_AFTER_DAYS} days ago. Treat these as possibly closed, and flag "
            "that the scraper has stopped running.",
        ]

    out += ["", f"## Matches ({len(jobs)})", ""]
    if jobs:
        out += [_fmt_job(j) for j in jobs]
    else:
        dropped = m.get("total_postings_excluded_non_uk", 0)
        out.append(
            f"None in the UK this week."
            + (f" {dropped} matching roles were overseas." if dropped else "")
        )

    if near:
        out += [
            "",
            f"## Worth a glance ({len(near)})",
            "",
            "Data-adjacent titles that did not clear the strict filter — architect, "
            "lead and analyst phrasings the keyword list misses.",
            "",
        ]
        out += [f"- **{n['title']}** — {n['company']}"
                + (f" ({n['location']})" if n.get("location") else "")
                + f"  \n  {n['url']}"
                for n in near]

    if failed:
        out += [
            "",
            "## Not checked",
            "",
            "These sites blocked or timed out, so they are unknown rather than empty:",
            "",
        ]
        out += [f"- {f['name']} — {f['url']}" for f in failed]

    out += [
        "",
        "---",
        f"Source: `{RAW_URL}`  ",
        f"Scrape run {started}; filed {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.",
    ]

    desc = (
        f"{len(jobs)} UK match{'es' if len(jobs) != 1 else ''} and {len(near)} near "
        f"miss{'es' if len(near) != 1 else ''} as of {run_day}"
    )
    if stale:
        desc += " (STALE — scraper may have stopped)"

    return "\n".join(out), desc, bool(jobs or near or stale)


def update_inbox(vault: Path, jobs: int, near: int, stale: bool) -> str:
    """Leave exactly one unread nudge from this source.

    Only unchecked lines render, under "Letters from other coaches", and they're
    marked read after the session closes. If James hasn't had a session since
    the last scan, replacing rather than appending stops the inbox filling with
    stale duplicates.
    """
    inbox = vault / "inbox.md"
    existing = inbox.read_text(encoding="utf-8") if inbox.exists() else "# Inbox\n"

    kept = [
        ln for ln in existing.splitlines()
        if not (ln.startswith("- [ ]") and f"| from {SOURCE} |" in ln)
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    if stale:
        msg = (
            f"job scan has not run for over {STALE_AFTER_DAYS} days — the scraper may "
            f'have stopped; recall "{EVIDENCE_TITLE}"'
        )
    else:
        parts = []
        if jobs:
            parts.append(f"{jobs} new UK match{'es' if jobs != 1 else ''}")
        if near:
            parts.append(f"{near} worth a glance")
        msg = (
            (", ".join(parts) if parts else "no new roles")
            + f' filed, recall "{EVIDENCE_TITLE}"'
        )

    line = f"- [ ] {stamp} | from {SOURCE} | {msg}"
    kept.append(line)
    inbox.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    return line


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    ap.add_argument("--url", default=RAW_URL)
    ap.add_argument("--dry-run", action="store_true", help="Print, write nothing.")
    args = ap.parse_args()

    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"ERROR: vault dir not found: {vault}", file=sys.stderr)
        return 1

    data = fetch(args.url)
    report, description, nudge = build_report(data)
    jobs = len(data.get("jobs", []))
    near = len(data.get("near_misses", []))
    stale = "STALE" in description

    if args.dry_run:
        print(f"--- INDEX description ---\n{description}\n")
        print(f"--- evidence: {EVIDENCE_TITLE} ---\n{report}\n")
        print(f"--- inbox nudge (would append: {nudge}) ---")
        if nudge:
            print(f"- [ ] ... | from {SOURCE} | ...")
        return 0

    # Imported here so --dry-run works anywhere, not just on coachbox.
    from cadence.evidence import EvidenceStore

    EvidenceStore(vault).save(
        title=EVIDENCE_TITLE,
        content=report,
        mode="replace",
        source=SOURCE,
        description=description,
    )
    print(f"filed evidence: {EVIDENCE_TITLE} ({description})")

    if nudge:
        print("inbox: " + update_inbox(vault, jobs, near, stale))
    else:
        print("inbox: nothing worth a nudge, no line written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
