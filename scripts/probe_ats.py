"""One-off reconnaissance: figure out which companies sit behind a JSON ATS API.

Fetches each careers URL over plain HTTP and looks for tell-tale ATS tokens in the
HTML (embedded board scripts, iframe srcs, redirect targets). Anything found here
can be hit as a JSON endpoint instead of driven through a browser.

Not part of the scheduled run -- this is a dev tool, re-run it when a company's
careers site changes shape.
"""

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = json.loads((ROOT / "scraper" / "companies.json").read_text())

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# token -> regex capturing the board slug where one is recoverable
ATS_PATTERNS = {
    "greenhouse": r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-zA-Z0-9_-]+)",
    "lever": r"jobs\.lever\.co/([a-zA-Z0-9_-]+)",
    "ashby": r"jobs\.ashbyhq\.com/([a-zA-Z0-9_.-]+)",
    "workable": r"apply\.workable\.com/([a-zA-Z0-9_-]+)",
    "teamtailor": r"([a-zA-Z0-9_-]+)\.teamtailor\.com",
    "recruitee": r"([a-zA-Z0-9_-]+)\.recruitee\.com",
    "personio": r"([a-zA-Z0-9_-]+)\.jobs\.personio\.(?:de|com)",
    "smartrecruiters": r"careers\.smartrecruiters\.com/([a-zA-Z0-9_-]+)",
    "bamboohr": r"([a-zA-Z0-9_-]+)\.bamboohr\.com",
    "workday": r"([a-zA-Z0-9_-]+)\.(wd\d+)\.myworkdayjobs\.com/([^/\"'?\s]+)",
    "successfactors": r"([a-zA-Z0-9_-]+)\.jobs\.sap\.com|career\d*\.successfactors",
    "phenom": r"phenompeople|phenom\.com",
    "pinpoint": r"([a-zA-Z0-9_-]+)\.pinpointhq\.com",
    "jazzhr": r"([a-zA-Z0-9_-]+)\.applytojob\.com",
    "breezy": r"([a-zA-Z0-9_-]+)\.breezy\.hr",
    "polymer": r"([a-zA-Z0-9_-]+)\.polymer\.co",
    "rippling": r"ats\.rippling\.com/([a-zA-Z0-9_-]+)",
    "hibob": r"([a-zA-Z0-9_-]+)\.hibob\.com",
}


async def probe(client: httpx.AsyncClient, company: dict) -> dict:
    url = company["careers_url"]
    result = {
        "name": company["name"],
        "careers_url": url,
        "status": None,
        "final_url": None,
        "ats_hits": {},
        "error": None,
        "html_len": 0,
    }
    try:
        r = await client.get(url, follow_redirects=True, timeout=25.0)
        result["status"] = r.status_code
        result["final_url"] = str(r.url)
        html = r.text
        result["html_len"] = len(html)
        haystack = html + " " + str(r.url)
        for ats, pattern in ATS_PATTERNS.items():
            matches = re.findall(pattern, haystack, flags=re.IGNORECASE)
            if matches:
                flat = []
                for m in matches:
                    flat.append(m if isinstance(m, str) else "|".join(x for x in m if x))
                # dedupe, keep order, cap noise
                seen, uniq = set(), []
                for f in flat:
                    if f and f.lower() not in seen:
                        seen.add(f.lower())
                        uniq.append(f)
                result["ats_hits"][ats] = uniq[:5]
    except Exception as e:  # noqa: BLE001 - recon script, report everything
        result["error"] = f"{type(e).__name__}: {e}"
    return result


async def main() -> None:
    limits = httpx.Limits(max_connections=8)
    async with httpx.AsyncClient(
        headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"},
        limits=limits,
        verify=True,
    ) as client:
        sem = asyncio.Semaphore(8)

        async def guarded(c):
            async with sem:
                return await probe(client, c)

        results = await asyncio.gather(*(guarded(c) for c in COMPANIES))

    out = ROOT / "scripts" / "probe_results.json"
    out.write_text(json.dumps(results, indent=2))

    for r in results:
        hits = ", ".join(f"{k}={v}" for k, v in r["ats_hits"].items()) or "-"
        print(f"{r['name'][:34]:<36} {str(r['status']):<5} len={r['html_len']:<8} {hits}")
        if r["error"]:
            print(f"    ERROR {r['error']}")
    print(f"\nwrote {out}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
