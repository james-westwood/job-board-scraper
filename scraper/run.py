"""Entry point: scrape every tracked company, emit one JSON report per run.

Contract with the consuming Claude session:
  * one object per run, written to output/latest.json (plus a dated copy)
  * every currently-live matching posting, every run -- no dedup here, the
    consuming side already tracks what it has seen
  * a company that breaks lands in run_metadata.companies_failed, it never
    takes the run down with it
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

from .adapters.api import API_ADAPTERS
from .adapters.browser import enrich_with_browser, scrape_with_browser
from .config import MAX_CONCURRENCY, SCRAPER_VERSION, USER_AGENT
from .matching import detect_work_arrangement, match_title, normalise, parse_salary
from .models import CompanyResult, Job, Posting, make_job_id, utc_now

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

# A matched job gets at most this many detail fetches; keeps a company with a
# pathological number of matches from stalling the run.
MAX_ENRICH_PER_COMPANY = 15


def log(msg: str) -> None:
    print(msg, flush=True)


def build_job(company: str, posting: Posting, keyword: str, detail: str | None) -> Job:
    body = " ".join(filter(None, [posting.description, detail]))
    salary_raw, smin, smax = parse_salary(" ".join(filter(None, [posting.title, body])))
    arrangement, arr_detail, confidence = detect_work_arrangement(
        posting.title, posting.location, body
    )

    return Job(
        company=company,
        title=normalise(posting.title),
        location=normalise(posting.location) or None,
        work_arrangement=arrangement,
        work_arrangement_detail=arr_detail,
        work_arrangement_confidence=confidence,
        salary_raw=salary_raw,
        salary_min_gbp=smin,
        salary_max_gbp=smax,
        url=posting.url,
        job_id=make_job_id(company, posting.url),
        scraped_at_utc=utc_now(),
        matched_keyword=keyword,
    )


async def run_company(company: dict, client: httpx.AsyncClient, browser) -> CompanyResult:
    name = company["name"]
    result = CompanyResult(name=name, url=company["careers_url"])
    adapter = company.get("adapter", "browser")
    cfg = company.get("config", {})

    try:
        if adapter == "browser":
            postings = await scrape_with_browser(browser, company)
            detail_fn = None
        else:
            list_fn, detail_fn = API_ADAPTERS[adapter]
            postings = await list_fn(client, cfg)

        result.postings_seen = len(postings)

        matched: list[tuple[Posting, str]] = []
        for p in postings:
            kw = match_title(p.title)
            if kw and p.url:
                matched.append((p, kw))

        for posting, keyword in matched[:MAX_ENRICH_PER_COMPANY]:
            detail = None
            # Skip the detail fetch when the listing already gave us enough
            # text to read salary and work arrangement off.
            if not posting.description or len(posting.description) < 400:
                try:
                    if detail_fn is not None:
                        detail = await detail_fn(client, cfg, posting)
                    elif adapter == "browser":
                        detail = await enrich_with_browser(browser, posting.url)
                except Exception as e:  # noqa: BLE001 - enrichment is best-effort
                    log(f"    [{name}] enrich failed for {posting.url}: {type(e).__name__}: {e}")
            result.jobs.append(build_job(name, posting, keyword, detail))

        # Anything past the enrichment cap still gets reported, unenriched.
        for posting, keyword in matched[MAX_ENRICH_PER_COMPANY:]:
            result.jobs.append(build_job(name, posting, keyword, None))

        flag = "WARN" if result.postings_seen == 0 else "ok  "
        log(f"  {flag} {name}: {result.postings_seen} seen, {len(result.jobs)} matched")

    except Exception as e:  # noqa: BLE001 - one company must never kill the run
        result.error = f"{type(e).__name__}: {str(e)[:300]}"
        log(f"  FAIL {name}: {result.error}")
        if "--traceback" in sys.argv:
            traceback.print_exc()

    return result


async def scrape_all(companies: list[dict]) -> dict:
    started = utc_now()
    results: list[CompanyResult] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"},
            follow_redirects=True,
        ) as client:
            sem = asyncio.Semaphore(MAX_CONCURRENCY)

            async def guarded(c: dict) -> CompanyResult:
                async with sem:
                    return await run_company(c, client, browser)

            results = await asyncio.gather(*(guarded(c) for c in companies))
        await browser.close()

    finished = utc_now()
    jobs = [j for r in results for j in r.jobs]
    succeeded = [r for r in results if r.succeeded]

    return {
        "run_metadata": {
            "run_started_utc": started,
            "run_finished_utc": finished,
            "scraper_version": SCRAPER_VERSION,
            "companies_attempted": len(results),
            "companies_succeeded": len(succeeded),
            "total_postings_seen": sum(r.postings_seen for r in results),
            "total_postings_matched": len(jobs),
            "companies_failed": [
                {"name": r.name, "url": r.url, "error": r.error}
                for r in results
                if not r.succeeded
            ],
            # A company that loaded fine but yielded no postings at all is
            # ambiguous -- either genuinely not hiring, or the page changed
            # shape and we are now blind to it. Surfaced separately so it is
            # reviewable rather than silently indistinguishable from "0 matches".
            "companies_no_postings": [
                {"name": r.name, "url": r.url}
                for r in results
                if r.succeeded and r.postings_seen == 0
            ],
        },
        "jobs": [j.to_dict() for j in jobs],
    }


def write_output(report: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    runs = output_dir / "runs"
    runs.mkdir(exist_ok=True)

    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    latest = output_dir / "latest.json"
    dated = runs / f"{datetime.now(timezone.utc):%Y-%m-%d}.json"
    latest.write_text(payload, encoding="utf-8")
    dated.write_text(payload, encoding="utf-8")
    return latest, dated


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape tracked careers sites for data/ML roles.")
    ap.add_argument("--only", help="Comma-separated substrings; scrape just those companies.")
    ap.add_argument("--adapter", help="Scrape only companies using this adapter.")
    ap.add_argument("--output-dir", default=str(OUTPUT_DIR))
    ap.add_argument("--traceback", action="store_true", help="Print tracebacks for failures.")
    args = ap.parse_args()

    companies = json.loads((ROOT / "scraper" / "companies.json").read_text(encoding="utf-8"))

    if args.only:
        wanted = [s.strip().lower() for s in args.only.split(",") if s.strip()]
        companies = [c for c in companies if any(w in c["name"].lower() for w in wanted)]
    if args.adapter:
        companies = [c for c in companies if c.get("adapter", "browser") == args.adapter]
    if not companies:
        log("No companies selected.")
        return 1

    log(f"Scraping {len(companies)} companies (concurrency {MAX_CONCURRENCY})...")
    report = asyncio.run(scrape_all(companies))

    latest, dated = write_output(report, Path(args.output_dir))
    m = report["run_metadata"]
    log(
        f"\nDone: {m['companies_succeeded']}/{m['companies_attempted']} companies, "
        f"{m['total_postings_seen']} postings seen, {m['total_postings_matched']} matched."
    )
    if m["companies_failed"]:
        log("Failed:")
        for f in m["companies_failed"]:
            log(f"  - {f['name']}: {f['error']}")
    log(f"Wrote {latest} and {dated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
