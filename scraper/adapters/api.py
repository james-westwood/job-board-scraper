"""Adapters for companies that expose a JSON endpoint.

Each adapter returns a list of Postings. Where the API hands back the full job
description for free (Workday detail, Pinpoint, Recruitee, Workable) it is put
on ``Posting.description`` so the runner can skip the detail fetch entirely.
"""

from __future__ import annotations

import html
import re

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..models import Posting

_TAGS = re.compile(r"<[^>]+>")


class RetryableStatus(Exception):
    """A response worth trying again -- rate limited or a server-side fault."""


@retry(
    retry=retry_if_exception_type((httpx.TransportError, RetryableStatus)),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=8),
    reraise=True,
)
async def request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """Make one HTTP call, retrying transient failures with backoff.

    Worth having because Workday pages 20 jobs at a time -- Teledyne's tenant is
    ~700 roles, so a single 503 partway through would otherwise lose that whole
    company for the week. The jittered backoff also keeps us from hammering a
    host that is already struggling.

    Only transport errors and 429/5xx are retried. A 404 is a real answer: the
    board moved, and repeating the call will not change that.
    """
    response = await client.request(method, url, **kwargs)
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableStatus(f"HTTP {response.status_code} from {url}")
    return response


def strip_html(raw: str | None) -> str | None:
    """HTML description -> plain text, good enough for keyword/salary scanning."""
    if not raw:
        return None
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<(br|/p|/div|/li|/h\d)\s*/?>", " \n", text, flags=re.I)
    text = _TAGS.sub(" ", text)
    return re.sub(r"[ \t]+", " ", html.unescape(text)).strip() or None


def _coerce(value) -> str | None:
    """These APIs are loosely typed -- 'location' may be a string, a dict or null."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "label", "text", "city", "value"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
        return _join(*(v for v in value.values() if isinstance(v, str)))
    if isinstance(value, (list, tuple)):
        return _join(*(_coerce(v) for v in value))
    return None


def _join(*parts) -> str | None:
    vals = [c for c in (_coerce(p) for p in parts) if c]
    return ", ".join(dict.fromkeys(vals)) or None


# --------------------------------------------------------------------------
# Workday  (7 of the tracked companies -- the big win of this build)
# --------------------------------------------------------------------------


async def workday(client: httpx.AsyncClient, cfg: dict) -> list[Posting]:
    """Workday's CXS endpoint: a POST that pages 20 at a time.

    Far more reliable than driving the JS portal, which is what these sites
    were originally flagged as needing.
    """
    tenant, host, site = cfg["tenant"], cfg["host"], cfg["site"]
    origin = f"https://{tenant}.{host}.myworkdayjobs.com"
    endpoint = f"{origin}/wday/cxs/{tenant}/{site}/jobs"

    postings: list[Posting] = []
    offset, limit = 0, 20
    total = None
    # Hard cap: some tenants (FLIR ~700) are group-wide. 50 pages = 1000 jobs.
    for _ in range(50):
        r = await request(
            client,
            "POST",
            endpoint,
            json={"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""},
            timeout=30.0,
        )
        r.raise_for_status()
        data = r.json()
        if total is None:
            total = data.get("total") or 0
        batch = data.get("jobPostings") or []
        if not batch:
            break
        for jp in batch:
            path = jp.get("externalPath") or ""
            postings.append(
                Posting(
                    title=jp.get("title") or "",
                    url=f"{origin}/{site}{path}" if path else f"{origin}/{site}",
                    location=jp.get("locationsText"),
                )
            )
        offset += limit
        if offset >= total:
            break
    return postings


async def workday_detail(client: httpx.AsyncClient, cfg: dict, posting: Posting) -> str | None:
    """Fetch one Workday job's description JSON (only for already-matched jobs)."""
    tenant, host, site = cfg["tenant"], cfg["host"], cfg["site"]
    origin = f"https://{tenant}.{host}.myworkdayjobs.com"
    path = posting.url.split(f"/{site}", 1)[-1]
    if not path:
        return None
    r = await request(client, "GET", f"{origin}/wday/cxs/{tenant}/{site}{path}", timeout=25.0)
    if r.status_code != 200:
        return None
    info = (r.json() or {}).get("jobPostingInfo") or {}
    return _join(
        strip_html(info.get("jobDescription")),
        info.get("location"),
        info.get("timeType"),
        info.get("remoteType"),
    )


# --------------------------------------------------------------------------
# Small-ATS adapters -- all return descriptions inline, so no detail pass.
# --------------------------------------------------------------------------


async def workable(client: httpx.AsyncClient, cfg: dict) -> list[Posting]:
    slug = cfg["slug"]
    r = await request(client, "GET", f"https://apply.workable.com/api/v1/widget/accounts/{slug}", timeout=30.0)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs") or []:
        loc = _join(j.get("city"), j.get("state"), j.get("country"))
        desc = _join(
            strip_html(j.get("description")),
            strip_html(j.get("requirements")),
            "Remote" if j.get("telecommuting") else None,
        )
        out.append(
            Posting(
                title=j.get("title") or "",
                url=j.get("url") or j.get("shortlink") or "",
                location=loc,
                description=desc,
            )
        )
    return out


async def recruitee(client: httpx.AsyncClient, cfg: dict) -> list[Posting]:
    slug = cfg["slug"]
    r = await request(client, "GET", f"https://{slug}.recruitee.com/api/offers/", timeout=30.0)
    r.raise_for_status()
    out = []
    for o in r.json().get("offers") or []:
        desc = _join(
            strip_html(o.get("description")),
            strip_html(o.get("requirements")),
            "Hybrid" if o.get("hybrid") else None,
            o.get("remote_option") if isinstance(o.get("remote_option"), str) else None,
        )
        out.append(
            Posting(
                title=o.get("title") or "",
                url=o.get("careers_url") or "",
                location=o.get("location") or _join(o.get("city"), o.get("country")),
                description=desc,
            )
        )
    return out


async def pinpoint(client: httpx.AsyncClient, cfg: dict) -> list[Posting]:
    slug = cfg["slug"]
    r = await request(client, "GET", f"https://{slug}.pinpointhq.com/postings.json", timeout=30.0)
    r.raise_for_status()
    out = []
    for p in r.json().get("data") or []:
        loc = p.get("location")
        if isinstance(loc, dict):
            loc = loc.get("name") or _join(loc.get("city"), loc.get("country"))

        # Pinpoint gives structured pay; surface it as text the salary parser
        # can read, but only when the employer chose to publish it.
        pay = None
        if p.get("compensation_visible"):
            lo, hi = p.get("compensation_minimum"), p.get("compensation_maximum")
            cur = "£" if (p.get("compensation_currency") or "GBP").upper() == "GBP" else ""
            if lo and hi:
                pay = f"Salary {cur}{int(float(lo)):,} - {cur}{int(float(hi)):,}"
            elif lo or hi:
                pay = f"Salary {cur}{int(float(lo or hi)):,}"
            if pay and p.get("compensation"):
                pay += f" ({p['compensation']})"

        out.append(
            Posting(
                title=p.get("title") or (p.get("job") or {}).get("title") or "",
                url=p.get("url") or f"https://{slug}.pinpointhq.com{p.get('path') or ''}",
                location=loc if isinstance(loc, str) else None,
                description=_join(
                    pay,
                    p.get("employment_type_text"),
                    strip_html(p.get("description")),
                    strip_html(p.get("key_responsibilities")),
                    strip_html(p.get("benefits")),
                ),
            )
        )
    return out


async def bamboohr(client: httpx.AsyncClient, cfg: dict) -> list[Posting]:
    slug = cfg["slug"]
    r = await request(client, "GET", f"https://{slug}.bamboohr.com/careers/list", timeout=30.0)
    r.raise_for_status()
    out = []
    for j in r.json().get("result") or []:
        atsloc = j.get("atsLocation") or {}
        loc = _join(atsloc.get("city"), atsloc.get("state"), atsloc.get("country"))
        out.append(
            Posting(
                title=(j.get("jobOpeningName") or "").strip(),
                url=f"https://{slug}.bamboohr.com/careers/{j.get('id')}",
                location=loc,
                description=_join(
                    j.get("employmentStatusLabel"),
                    "Remote" if j.get("isRemote") else None,
                ),
            )
        )
    return out


async def bamboohr_detail(client: httpx.AsyncClient, cfg: dict, posting: Posting) -> str | None:
    job_id = posting.url.rstrip("/").rsplit("/", 1)[-1]
    r = await request(client, "GET", f"https://{cfg['slug']}.bamboohr.com/careers/{job_id}/detail", timeout=25.0)
    if r.status_code != 200:
        return None
    res = (r.json() or {}).get("result") or {}
    jo = res.get("jobOpening") or res
    return _join(strip_html(jo.get("description")), jo.get("compensation"), jo.get("location"))


async def greenhouse(client: httpx.AsyncClient, cfg: dict) -> list[Posting]:
    slug = cfg["slug"]
    r = await request(client, "GET", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", timeout=30.0)
    r.raise_for_status()
    return [
        Posting(
            title=j.get("title") or "",
            url=j.get("absolute_url") or "",
            location=(j.get("location") or {}).get("name"),
            description=strip_html(j.get("content")),
        )
        for j in r.json().get("jobs") or []
    ]


async def lever(client: httpx.AsyncClient, cfg: dict) -> list[Posting]:
    slug = cfg["slug"]
    r = await request(client, "GET", f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=30.0)
    r.raise_for_status()
    out = []
    for j in r.json() or []:
        cats = j.get("categories") or {}
        out.append(
            Posting(
                title=j.get("text") or "",
                url=j.get("hostedUrl") or "",
                location=cats.get("location"),
                description=_join(
                    strip_html(j.get("descriptionPlain") or j.get("description")),
                    cats.get("commitment"),
                    cats.get("workplaceType"),
                ),
            )
        )
    return out


async def ashby(client: httpx.AsyncClient, cfg: dict) -> list[Posting]:
    slug = cfg["slug"]
    r = await request(
        client, "GET",
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
        timeout=30.0,
    )
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs") or []:
        comp = j.get("compensation") or {}
        summary = comp.get("compensationTierSummary") if isinstance(comp, dict) else None
        out.append(
            Posting(
                title=j.get("title") or "",
                url=j.get("jobUrl") or "",
                location=j.get("location"),
                description=_join(
                    summary,
                    strip_html(j.get("descriptionHtml") or j.get("descriptionPlain")),
                    "Remote" if j.get("isRemote") else None,
                ),
            )
        )
    return out


# name -> (list_fn, detail_fn or None)
API_ADAPTERS = {
    "workday": (workday, workday_detail),
    "workable": (workable, None),
    "recruitee": (recruitee, None),
    "pinpoint": (pinpoint, None),
    "bamboohr": (bamboohr, bamboohr_detail),
    "greenhouse": (greenhouse, None),
    "lever": (lever, None),
    "ashby": (ashby, None),
}
