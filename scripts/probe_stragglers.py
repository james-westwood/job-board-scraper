"""Third recon pass: chase the URLs that 404'd, timed out, or hid their ATS."""

import asyncio
import re

import httpx

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

CANDIDATES = [
    ("Lime ashby lower", "https://api.ashbyhq.com/posting-api/job-board/lime"),
    ("Lime ashby li.me", "https://api.ashbyhq.com/posting-api/job-board/li.me"),
    ("Good Energy careers", "https://www.goodenergy.co.uk/careers/"),
    ("Ecotricity careers", "https://www.ecotricity.co.uk/careers"),
    ("BP Pulse root", "https://www.bppulse.com/"),
    ("Zap-Map careers", "https://www.zap-map.com/careers"),
    ("BeZero careers", "https://bezerocarbon.com/careers"),
    ("BeZero root", "https://bezerocarbon.com/"),
    ("Treeconomy root", "https://www.treeconomy.co/"),
    ("GridBeyond nonwww", "https://gridbeyond.com/careers/"),
    ("ScottishPower", "https://www.scottishpower.jobs/"),
    ("ev.energy careers", "https://platform.ev.energy/careers"),
    ("Piclo about", "https://www.piclo.com/about"),
    ("RES careers", "https://www.res-group.com/careers/"),
    ("AECOM", "https://aecom.jobs"),
]

TOKENS = re.compile(
    r"(greenhouse\.io/[a-zA-Z0-9_/?=-]+|jobs\.lever\.co/[a-zA-Z0-9-]+|"
    r"ashbyhq\.com/[a-zA-Z0-9_.-]+|apply\.workable\.com/[a-zA-Z0-9-]+|"
    r"[a-zA-Z0-9-]+\.teamtailor\.com|[a-zA-Z0-9-]+\.recruitee\.com|"
    r"[a-zA-Z0-9-]+\.pinpointhq\.com|[a-zA-Z0-9-]+\.bamboohr\.com|"
    r"[a-zA-Z0-9-]+\.jobs\.personio\.[a-z]+|smartrecruiters\.com/[a-zA-Z0-9-]+|"
    r"[a-zA-Z0-9-]+\.\w*wd\d+\.myworkdayjobs\.com/[^\"'?\s]+|"
    r"[a-zA-Z0-9-]+\.hibob\.com[^\"'\s]{0,40}|"
    r"[a-zA-Z0-9-]+\.applytojob\.com|[a-zA-Z0-9-]+\.breezy\.hr|"
    r"jobs\.jobvite\.com/[a-zA-Z0-9-]+|icims\.com/[a-zA-Z0-9_/-]+|"
    r"careers?[a-z0-9-]*\.[a-z0-9-]+\.com/[a-zA-Z0-9_/-]{0,30})",
    re.IGNORECASE,
)


async def go(client, label, url):
    try:
        r = await client.get(url, follow_redirects=True, timeout=30.0)
        body = r.text
        hits = []
        seen = set()
        for m in TOKENS.findall(body):
            k = m.lower()
            if k not in seen:
                seen.add(k)
                hits.append(m)
        return f"{label:<22} {r.status_code} -> {str(r.url)[:70]}\n      {hits[:8]}"
    except Exception as e:
        return f"{label:<22} ERR {type(e).__name__}: {str(e)[:90]}"


async def main():
    async with httpx.AsyncClient(headers={"User-Agent": UA}, verify=False) as c:
        for line in await asyncio.gather(*(go(c, l, u) for l, u in CANDIDATES)):
            print(line)


if __name__ == "__main__":
    asyncio.run(main())
