"""Dump what the browser adapter actually sees on a page, to debug 0-seen cases.

Usage: uv run python scripts/debug_page.py "OVO Energy" "Thames Water"
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.adapters.browser import EXTRACT_JS, JOB_HREF, _dismiss_cookies, _expand  # noqa: E402
from scraper.config import USER_AGENT  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = json.loads((ROOT / "scraper" / "companies.json").read_text())


async def debug(browser, company):
    print(f"\n{'=' * 78}\n{company['name']}  {company['careers_url']}")
    ctx = await browser.new_context(
        user_agent=USER_AGENT, locale="en-GB", viewport={"width": 1440, "height": 900},
        ignore_https_errors=True,
    )
    try:
        page = await ctx.new_page()
        try:
            await page.goto(company["careers_url"], wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  GOTO FAILED: {type(e).__name__}: {str(e)[:100]}")
            return
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            await page.wait_for_timeout(1500)
        await _dismiss_cookies(page)
        await _expand(page)

        print(f"  final url: {page.url}")
        print(f"  frames: {len(page.frames)}")
        total = 0
        matching = 0
        samples = []
        for frame in page.frames:
            try:
                anchors = await frame.evaluate(EXTRACT_JS)
            except Exception:
                continue
            total += len(anchors)
            for a in anchors:
                if JOB_HREF.search(a["href"]):
                    matching += 1
                if len(samples) < 40:
                    samples.append((a["href"][:88], a["text"][:60]))
        print(f"  anchors total={total}  job-href-matching={matching}")
        body = await page.evaluate("() => document.body ? document.body.innerText : ''")
        print(f"  body text len={len(body)}")
        print(f"  body head: {re.sub(r'[ \t]+', ' ', body[:260])!r}")
        print("  sample anchors:")
        for href, text in samples[:28]:
            print(f"    {href:<90} [{text}]")
    finally:
        await ctx.close()


async def main():
    wanted = [w.lower() for w in sys.argv[1:]]
    targets = [c for c in COMPANIES if any(w in c["name"].lower() for w in wanted)]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        for c in targets:
            await debug(browser, c)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
