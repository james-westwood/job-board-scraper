# Handback to the weekly Claude session

This file is for the Claude session (Cowork or otherwise) that reads this scraper's
output. It is fetchable at:

```
https://raw.githubusercontent.com/james-westwood/job-board-scraper/main/HANDOFF.md
```

## The one URL you need

```
https://raw.githubusercontent.com/james-westwood/job-board-scraper/main/output/latest.json
```

Public, no auth, plain GET — readable with `WebFetch`. Dated history lives alongside it at
`output/runs/YYYY-MM-DD.json`.

The scraper runs **06:00 UTC every Monday**, 30 minutes before the weekly check. Always
read `run_metadata.run_started_utc` and say how fresh the data is. If that timestamp is
more than ~8 days old the workflow has stopped running and should be flagged.

> `raw.githubusercontent.com` caches for a few minutes. If a run just finished and you're
> seeing stale content, append a cache-buster: `...latest.json?v=<timestamp>`.

## Paste-ready prompt

```
Read https://raw.githubusercontent.com/james-westwood/job-board-scraper/main/output/latest.json

This is the weekly scrape of the ~34 companies that have no public ATS API — it
complements the 8 companies you already query directly via Greenhouse/Lever/Ashby/
Workable.

Please:
1. Check run_metadata.run_started_utc and tell me how fresh this is.
2. Diff the jobs[] array against the roles already recorded in Job_Board_Watchlist.md,
   using job_id as the key. Only show me genuinely new ones.
3. For each new role, give me: company, title, location, work arrangement, salary if
   known, and the link. Flag anything where work_arrangement_confidence is not "stated"
   or location_region is "unknown" as needing a manual look.
4. List run_metadata.companies_failed and companies_no_postings so I know what to check
   by hand.
5. Add the new roles to Job_Board_Watchlist.md so next week's diff is clean.
```

## Reading the output

**Dedup is your job.** The scraper reports everything currently live that matches, every
run. It keeps no memory between runs by design. Use `job_id` as the key — it is stable
across runs (same URL always produces the same id) and namespaced `scrape:` so it cannot
collide with the `greenhouse:` / `ashby:` ids already tracked.

| Field | How to read it |
| --- | --- |
| `location_region` | `"uk"` confirmed UK. `"unknown"` means the location couldn't be determined — kept deliberately rather than dropped, so **check these manually**. Confidently non-UK roles are already filtered out. |
| `work_arrangement_confidence` | `"stated"` = the page said so. `"inferred"` = deduced from weaker signals. `"unknown"` = nothing to go on. Only trust `"stated"` without checking. |
| `salary_min_gbp` / `salary_max_gbp` | `null` unless a **sterling** figure was parsed confidently. USD/EUR postings keep `salary_raw` verbatim but are never converted. Always show `salary_raw` — it's there so a human can check the parse. |
| `matched_keyword` | Which filter term caught it. Useful for spotting loose matches — e.g. a full-stack role caught by `"data platform"`. |

## The three lists in `run_metadata`

- **`companies_failed`** — broke this run (timeout, bot wall, structure change). These need
  a manual check; treat them as unknown, not as "no jobs".
- **`companies_no_postings`** — loaded fine but yielded nothing. Either genuinely not
  hiring or the page changed shape. Worth an occasional eyeball.
- **`total_postings_excluded_non_uk`** — matching roles dropped by the UK filter. If this
  is high and `total_postings_matched` is 0, say so: it means the week wasn't empty, the
  roles were just all overseas.

A `total_postings_matched` of 0 with a healthy `total_postings_seen` is a real quiet week,
not a broken scraper. Say which it is rather than just reporting "no new jobs".

## Known permanent failures

- **ScottishPower** — refuses connections from datacentre IPs. Will essentially always be
  in `companies_failed`. Check `scottishpower.jobs` manually.
- **Anglian Water** — Cloudflare bot interstitial. Same: check by hand.

Neither is fixable without credentials or paid proxying, both of which are deliberately
out of scope.
