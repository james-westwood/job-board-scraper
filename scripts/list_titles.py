"""List every posting title a company yields, matched or not.

The sanity check for a thin week: if a company shows 30 postings and none
matched, this tells you whether that's because they genuinely have no data
roles, or because the scraper is reading the wrong part of the page.

Usage: uv run python scripts/list_titles.py "NESO" "Good Energy"
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.adapters.api import API_ADAPTERS  # noqa: E402
from scraper.adapters.browser import scrape_with_browser  # noqa: E402
from scraper.config import USER_AGENT  # noqa: E402
from scraper.matching import match_title  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = json.loads((ROOT / "scraper" / "companies.json").read_text())


async def main():
    wanted = [w.lower() for w in sys.argv[1:]]
    targets = [c for c in COMPANIES if not wanted or any(w in c["name"].lower() for w in wanted)]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            for c in targets:
                name, adapter = c["name"], c.get("adapter", "browser")
                try:
                    if adapter == "browser":
                        postings = await scrape_with_browser(browser, c)
                    else:
                        postings = await API_ADAPTERS[adapter][0](client, c.get("config", {}))
                except Exception as e:  # noqa: BLE001
                    print(f"\n=== {name} [{adapter}] FAILED: {type(e).__name__}: {e}")
                    continue

                print(f"\n=== {name} [{adapter}] — {len(postings)} postings")
                for p in postings:
                    kw = match_title(p.title)
                    mark = f"  <== MATCH ({kw})" if kw else ""
                    loc = f"  [{p.location}]" if p.location else ""
                    print(f"    {p.title[:72]}{loc}{mark}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
