"""Find the real careers URL for companies whose tracked URL is broken.

Fetches the company's homepage and pulls out every link whose href or anchor
text looks careers-shaped, so a human can pick the right one.
"""

import asyncio
import re

import httpx

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

ROOTS = [
    ("Ecotricity", "https://www.ecotricity.co.uk/"),
    ("BP Pulse", "https://www.bppulse.com/en-gb"),
    ("BeZero Carbon", "https://bezerocarbon.com/"),
    ("Treeconomy", "https://www.treeconomy.co/"),
    ("ScottishPower", "https://www.scottishpower.co.uk/"),
    ("Anglian Water", "https://www.anglianwater.co.uk/"),
]

ANCHOR = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
CAREERS = re.compile(r"career|job|vacanc|work-with-us|work-for-us|join-us|opportunit", re.I)
TAGS = re.compile(r"<[^>]+>")


async def go(client, name, root):
    lines = [f"\n=== {name}  ({root})"]
    try:
        r = await client.get(root, follow_redirects=True, timeout=30.0)
        lines.append(f"  {r.status_code} -> {r.url}")
        seen = set()
        for href, text in ANCHOR.findall(r.text):
            label = TAGS.sub("", text).strip()[:60]
            if not CAREERS.search(href) and not CAREERS.search(label):
                continue
            full = str(httpx.URL(str(r.url)).join(href))
            if full in seen:
                continue
            seen.add(full)
            lines.append(f"    {full[:95]}   [{label}]")
            if len(seen) >= 12:
                break
        if not seen:
            lines.append("    (no careers-shaped links found in HTML)")
    except Exception as e:
        lines.append(f"  ERR {type(e).__name__}: {str(e)[:120]}")
    return "\n".join(lines)


async def main():
    async with httpx.AsyncClient(headers={"User-Agent": UA}, verify=False) as c:
        for line in await asyncio.gather(*(go(c, n, u) for n, u in ROOTS)):
            print(line)


if __name__ == "__main__":
    asyncio.run(main())
