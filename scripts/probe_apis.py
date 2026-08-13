"""Second recon pass: hit the concrete JSON endpoints implied by probe_ats.py.

Confirms which candidate APIs actually return job data before any of them get
wired into the real scraper.
"""

import asyncio
import json

import httpx

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

WORKDAY = [
    ("NESO", "neso", "wd103", "Careers"),
    ("South East Water", "southeastwater", "wd103", "South_East_Water_Careers_site"),
    ("ICAP Energy AS", "tp", "wd107", "TP-ICAP"),
    ("Centrica Energy", "centrica", "wd3", "Centrica"),
    ("Workiva", "workiva", "wd503", "careers"),
    ("Teledyne", "flir", "wd1", "flircareers"),
]

GETS = [
    ("Lime / ashby", "https://api.ashbyhq.com/posting-api/job-board/Lime"),
    ("Connected Kerb / workable v3",
     "https://apply.workable.com/api/v3/accounts/connected-kerb/jobs"),
    ("Connected Kerb / workable widget",
     "https://apply.workable.com/api/v1/widget/accounts/connected-kerb"),
    ("Greyparrot / recruitee", "https://greyparrotai.recruitee.com/api/offers/"),
    ("Aira / teamtailor page", "https://career.airahome.com/jobs"),
    ("ev.energy / hibob", "https://apply.hibob.com/api/v1/careers/evenergy/positions"),
]


async def try_workday(client, name, tenant, wd, site):
    url = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
    try:
        r = await client.post(url, json=body, timeout=30.0)
        if r.status_code != 200:
            return f"{name:<20} WORKDAY {r.status_code} {url}"
        d = r.json()
        total = d.get("total")
        posts = d.get("jobPostings", [])
        sample = posts[0].get("title") if posts else None
        return f"{name:<20} WORKDAY 200 total={total} n={len(posts)} e.g. {sample!r}"
    except Exception as e:
        return f"{name:<20} WORKDAY ERR {type(e).__name__}: {e}"


async def try_get(client, label, url):
    try:
        r = await client.get(url, follow_redirects=True, timeout=30.0)
        ct = r.headers.get("content-type", "")
        head = ""
        if "json" in ct:
            d = r.json()
            if isinstance(d, dict):
                head = f"keys={list(d)[:6]}"
                for k in ("jobs", "offers", "results", "positions", "data"):
                    if isinstance(d.get(k), list):
                        head += f" {k}={len(d[k])}"
                        if d[k]:
                            first = d[k][0]
                            head += f" e.g.{first.get('title') or first.get('name')!r}"
                        break
            elif isinstance(d, list):
                head = f"list n={len(d)}"
        else:
            head = f"ct={ct.split(';')[0]} len={len(r.text)}"
        return f"{label:<30} {r.status_code} {head}"
    except Exception as e:
        return f"{label:<30} ERR {type(e).__name__}: {e}"


async def main():
    async with httpx.AsyncClient(headers={"User-Agent": UA, "Accept": "application/json"}) as c:
        tasks = [try_workday(c, *w) for w in WORKDAY] + [try_get(c, *g) for g in GETS]
        for line in await asyncio.gather(*tasks):
            print(line)


if __name__ == "__main__":
    asyncio.run(main())
