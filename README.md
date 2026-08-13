# Job board scraper

Weekly scrape of the careers sites that **don't** have a usable public ATS API, filtered
for data/ML roles, published as a single JSON file that a Claude session reads.

This is the second half of a two-part job-search pipeline. The first half (a weekly
scheduled Claude session) already hits Greenhouse/Lever/Ashby/Workable JSON APIs directly
for the companies that expose them. This repo covers the rest.

## Output

Every run writes:

- `output/latest.json` — the current run, always overwritten
- `output/runs/YYYY-MM-DD.json` — a dated copy, kept for history

The consuming session fetches the raw URL:

```
https://raw.githubusercontent.com/<user>/<repo>/main/output/latest.json
```

Shape:

```json
{
  "run_metadata": {
    "run_started_utc": "2026-08-18T07:00:00Z",
    "run_finished_utc": "2026-08-18T07:04:12Z",
    "scraper_version": "1.0.0",
    "companies_attempted": 34,
    "companies_succeeded": 32,
    "total_postings_seen": 1709,
    "total_postings_matched": 22,
    "companies_failed": [
      {"name": "ScottishPower", "url": "...", "error": "timeout after 30s"}
    ],
    "companies_no_postings": [{"name": "Piclo", "url": "..."}]
  },
  "jobs": [
    {
      "company": "AECOM",
      "title": "Senior AI Engineer",
      "location": "Singapore",
      "work_arrangement": "hybrid",
      "work_arrangement_detail": "2 days/week in office",
      "work_arrangement_confidence": "stated",
      "salary_raw": "£55,000 - £65,000",
      "salary_min_gbp": 55000,
      "salary_max_gbp": 65000,
      "url": "https://aecom.jobs/...",
      "job_id": "scrape:aecom:9f2a4c1e8b3d",
      "scraped_at_utc": "2026-08-18T07:01:33Z",
      "matched_keyword": "ai engineer"
    }
  ]
}
```

Notes for the consuming side:

- **No dedup happens here.** Every run reports everything currently live that matches.
  Diffing against what you've already seen is your job.
- `job_id` is `scrape:{company-slug}:{sha1(url)[:12]}` — stable across runs, and namespaced
  so it can't collide with the `greenhouse:` / `ashby:` ids you already track.
- `companies_failed` is the manual-check list. A page that broke never takes the run down.
- `companies_no_postings` (an addition to the original spec) lists companies that loaded
  fine but yielded nothing. That distinguishes "not hiring" from "the scraper went blind",
  which a bare `0` cannot.
- `salary_min_gbp` / `salary_max_gbp` are `null` unless a **sterling** figure was parsed
  confidently. `salary_raw` is kept verbatim regardless — including for USD/EUR postings,
  which are reported but never converted.

## How companies are scraped

Recon (`scripts/probe_ats.py`) found that most of these companies *do* sit behind a JSON
API — it just isn't the one the handoff assumed. Browser automation is the fallback, not
the default.

| Adapter | Companies | Notes |
| --- | --- | --- |
| `workday` | 7 | NESO, Centrica, Workiva, South East Water, ICAP/TP-ICAP, Teledyne (FLIR tenant), BP | Workday's CXS JSON endpoint — no browser needed |
| `pinpoint` / `workable` / `recruitee` / `bamboohr` | 4 | Good Energy, Connected Kerb, Greyparrot, GridBeyond | full descriptions inline |
| `browser` | 23 | everything else | Playwright/Chromium |
| `greenhouse` / `lever` / `ashby` | 0 | wired up, unused so far | for when a company migrates |

To move a company onto an API adapter, set `adapter` and `config` in
`scraper/companies.json` — no code change needed.

## Careers URLs are not to be trusted

Nine of the 34 URLs in the original handoff were wrong: 404s, a rebrand, a TLS
misconfiguration, and several careers pages that only *link* to the real board. They're
corrected in `scraper/companies.json`, each with a `notes` field recording what happened.

Re-run the recon scripts when a company starts failing or silently returns nothing:

```bash
uv run --with httpx python scripts/probe_ats.py        # which ATS is a site on?
uv run --with httpx python scripts/find_careers_urls.py # where did the careers page go?
uv run python scripts/debug_page.py "OVO Energy"        # what does the browser actually see?
```

## Running locally

```bash
uv sync --group dev
uv run playwright install chromium

uv run python -m scraper.run                        # everything (~3 min)
uv run python -m scraper.run --adapter workday      # one adapter
uv run python -m scraper.run --only "OVO,Lime"      # named companies
uv run python -m scraper.run --traceback            # tracebacks for failures

uv run pytest -q                                    # unit tests
uv run python scripts/validate_output.py            # schema check
```

## Schedule

`.github/workflows/scrape.yml` runs `0 6 * * 1` (06:00 UTC Monday), 30 minutes before the
Claude session that reads it, and commits the result back to `main`. It also accepts a
manual `workflow_dispatch` with optional `only` / `adapter` inputs.

CI runs the unit tests and validates the output schema before committing, so a malformed
file never reaches the consumer.

## Known limitations

- **ScottishPower** refuses connections from datacentre IPs. It fails locally and will
  almost certainly fail from GitHub runners. It lands in `companies_failed` by design.
- **Anglian Water** serves a Cloudflare bot interstitial. Detected explicitly and reported
  as failed rather than as an empty result.
- **Treeconomy, Piclo, Previsico, Flexitricity, BeZero Carbon** have no machine-readable
  board and showed no vacancies at all — verified they're not on any common ATS. They will
  sit in `companies_no_postings` until they publish something.
- `total_postings_seen` is exact for API adapters and approximate for browser ones, where
  it counts link candidates rather than confirmed postings.
- **No location filter.** The criteria in the spec are title-only, so US and APAC roles do
  come through (BP, Workiva and Teledyne are the noisy ones). Easy to add if wanted.

## Scope

v1 deliberately excludes ClimateBase individual job links, any login-gated scraping, and
any "have I seen this before" store — that lives on the Claude side. No credentials are
required, and none should be added.
