"""Playwright adapter for careers sites that render their job list client-side.

The shape of these pages varies wildly, so this deliberately avoids per-company
CSS selectors (which rot fast and silently). Instead it renders the page, pushes
past the usual obstacles (cookie walls, "load more", lazy lists, embedded board
iframes) and treats every link on the page as a candidate job, letting the title
filter decide what is real.

That trades precision in ``postings_seen`` for not breaking every time a site is
restyled -- an approximate count that keeps working beats an exact one that
silently goes to zero.
"""

from __future__ import annotations

import re

from playwright.async_api import Browser, Error as PlaywrightError, TimeoutError as PWTimeout

from ..config import DETAIL_TIMEOUT_MS, PAGE_TIMEOUT_MS, USER_AGENT
from ..matching import match_title
from ..models import Posting

# Links whose destination looks like an individual posting.
JOB_HREF = re.compile(
    r"/(jobs?|careers?|positions?|vacanc\w*|opening|opportunit\w*|role|apply|listing)s?[/\-_?=.]|"
    r"/o/|/j/|jobid|job_id|requisition|gh_jid|lever\.co/|ashbyhq\.com/|workable\.com/",
    re.I,
)

# Plenty of sites hang postings off a bare requisition id with no /job/ segment
# at all (OVO: /senior-data-engineer/7771748), or off an opaque query param
# (Thames Water: VacancyInformation.aspx?VId=38429), so match the id shape too.
JOB_ID_HREF = re.compile(
    r"/\d{4,}(?:[/?#]|$)|[?&][\w]*(?:job|id|req|ref|vac|posting)\w*=\d+", re.I
)

# Links from a careers landing page through to the actual list of openings.
JOB_INDEX_HREF = re.compile(
    r"/(jobs?|vacanc\w*|opening\w*|opportunit\w*|positions?|roles?|search)(?:[/?#]|$)", re.I
)
JOB_INDEX_TEXT = re.compile(
    r"^(jobs?|all jobs|view all|view all jobs|see all jobs|current opportunities|"
    r"current vacancies|vacancies|job openings|current openings|open roles?|"
    r"open positions?|see open roles?|view openings?|search jobs|browse jobs|"
    r"our vacancies|live roles?|view jobs)\b",
    re.I,
)

# Pages that loaded but are an anti-bot interstitial, not the careers site.
BOT_WALL = re.compile(
    r"performing security verification|checking your browser|verify you are (?:not )?a human|"
    r"enable javascript and cookies to continue|are you a robot|access denied|"
    r"request unsuccessful|cf-browser-verification|ray id:",
    re.I,
)

# Anchor text that is navigation or chrome, never a job title.
NAV_TEXT = re.compile(
    r"^(careers?|jobs?|all jobs|view all|see all|view jobs|search|search jobs|apply|apply now|"
    r"open roles?|open positions?|vacancies|current vacancies|join us|work with us|"
    r"life at .*|benefits|culture|our people|read more|learn more|more info|back|next|"
    r"previous|home|about|about us|contact|contact us|privacy|cookies?|terms|sitemap|"
    r"login|sign in|register|menu|skip to content)$",
    re.I,
)

COOKIE_TEXTS = [
    "Accept all", "Accept All", "Accept all cookies", "Allow all", "I accept",
    "Accept cookies", "Agree", "Got it", "OK", "Continue",
]

MORE_TEXTS = ["Load more", "Show more", "See more", "View more", "More jobs", "Next"]

# Pulls every anchor out of one frame, with enough context to judge it.
#
# Job cards usually mark the title up as a heading and the location with a
# recognisable class, so read those directly where they exist -- taking the
# anchor's whole innerText gives titles like "Data Engineer Engineering ,
# Canada , Full time".
EXTRACT_JS = """
() => {
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href') || '';
    if (!href || href.startsWith('javascript:') || href.startsWith('mailto:')
        || href.startsWith('tel:') || href.startsWith('#')) continue;
    const text = clean(a.innerText || a.textContent);
    if (!text || text.length > 150) continue;

    const titleEl = a.querySelector('h1,h2,h3,h4,h5,[class*="title" i],[class*="name" i]');
    const title = titleEl ? clean(titleEl.innerText) : '';

    // Nearby text gives the location/arrangement without a detail fetch.
    const box = a.closest('li, article, .card, .job, [class*="job"], [class*="vacancy"], tr, div');
    const context = box ? clean(box.innerText).slice(0, 600) : '';

    const locEl = (box || a).querySelector('[class*="location" i], [class*="office" i]');
    const location = locEl ? clean(locEl.innerText).slice(0, 120) : '';

    out.push({href: a.href, text, title, location, context});
  }
  return out;
}
"""

# Links that are clearly editorial rather than a vacancy. Without this, a blog
# post titled "The data science of optimisation" matches the keyword filter.
NON_JOB_HREF = re.compile(
    r"/(blog|news|article|insight|press|media|resource|webinar|podcast|event|"
    r"case-stud|white-?paper|report|story|stories|guide|video)s?[/\-_?]|"
    # Team directories: an employee profile card reads exactly like a job card,
    # since it pairs a name with a job title. Fathom's careers site lists staff
    # as "Alex Marshall Senior Machine Learning Engineer".
    r"/(people|team|staff|leadership|profile|author|colleague|employee)s?[/\-_?]|"
    # Legal/footer pages. Teamtailor sites carry a "Data & privacy" link that
    # otherwise reads as a near miss on the word "data".
    r"/(privacy|cookies?|cookie-policy|legal|terms|gdpr|accessibility|"
    r"data-privacy|data-protection)(?:[/?#\-]|$)|"
    r"/\d{4}/\d{2}/",
    re.I,
)

# Some sites publish editorial at the site root with no /blog/ prefix, so the
# URL gives nothing away -- e.g. Habitat Energy's "The data science of
# optimisation: Q&A with ...". Headlines read very differently to job titles.
EDITORIAL_TITLE = re.compile(
    r"\bq&a\b|\bwebinar\b|\bpodcast\b|\binterview with\b|\bmeet (?:the|our)\b|"
    r"\bblog\b|\bcase stud|\bannounc|\bwe(?:'re| are) hiring\b|\bhow (?:we|i|to)\b|"
    r"\bwhy (?:we|i)\b|\bour approach\b|\bin conversation\b|\?",
    re.I,
)


async def _dismiss_cookies(page) -> None:
    for label in COOKIE_TEXTS:
        try:
            btn = page.get_by_role("button", name=label, exact=False)
            if await btn.count():
                await btn.first.click(timeout=2500)
                await page.wait_for_timeout(400)
                return
        except (PWTimeout, PlaywrightError):
            continue


async def _expand(page) -> None:
    """Click through 'load more' and lazy-scroll, within a fixed budget."""
    for _ in range(4):
        clicked = False
        for label in MORE_TEXTS:
            try:
                btn = page.get_by_role("button", name=label, exact=False)
                if not await btn.count():
                    btn = page.get_by_role("link", name=label, exact=False)
                if await btn.count() and await btn.first.is_visible():
                    await btn.first.click(timeout=3000)
                    await page.wait_for_timeout(1200)
                    clicked = True
                    break
            except (PWTimeout, PlaywrightError):
                continue
        if not clicked:
            break

    for _ in range(3):
        try:
            await page.mouse.wheel(0, 4000)
            await page.wait_for_timeout(600)
        except PlaywrightError:
            break


def _best_title(marked_up: str | None, full_text: str) -> str:
    """Pick the cleanest available title for a job card.

    Prefer the card's own heading element. Failing that, cut the anchor text at
    the first bullet/pipe separator, which is how most card layouts fence the
    title off from department/location/contract chips.
    """
    if marked_up and 3 <= len(marked_up) <= 120:
        return marked_up
    return re.split(r"\s*[•|·¦]\s*|\s{2,}", full_text.strip(), maxsplit=1)[0].strip() or full_text


def _is_candidate(href: str, text: str) -> bool:
    """Should this anchor be treated as a possible job posting?

    Errs towards including: a false positive here costs an inflated
    ``postings_seen``, whereas a false negative loses a real job silently. The
    title filter downstream is what actually decides.
    """
    if len(text) < 3 or NAV_TEXT.match(text):
        return False
    if NON_JOB_HREF.search(href):
        return False
    if EDITORIAL_TITLE.search(text):
        return False
    if JOB_HREF.search(href) or JOB_ID_HREF.search(href):
        return True
    # Regardless of URL shape, an anchor whose text is a role we care about is
    # always worth keeping -- this is the backstop against a restyled site.
    return match_title(text) is not None


async def _collect(page) -> list[Posting]:
    """Harvest candidates from the page and any embedded board iframes."""
    postings: dict[str, Posting] = {}
    for frame in page.frames:
        anchors = await _safe_eval(frame, EXTRACT_JS, [])
        for a in anchors:
            href, text = a.get("href", ""), a.get("text", "")
            title = _best_title(a.get("title"), text)
            # Judge on both: the marked-up title is cleaner, but the full anchor
            # text is what catches a card whose heading markup we misread.
            if not (_is_candidate(href, title) or _is_candidate(href, text)):
                continue
            if href not in postings:
                postings[href] = Posting(
                    title=title,
                    url=href,
                    location=a.get("location") or None,
                    description=a.get("context") or None,
                )
    return list(postings.values())


class BlockedError(RuntimeError):
    """The site served an anti-bot interstitial instead of its careers page."""


async def _safe_eval(target, js: str, default):
    """Evaluate JS, tolerating a navigation landing mid-call.

    Several of these pages redirect or hydrate a moment after load, which
    destroys the execution context underneath us; one retry is enough.
    """
    for attempt in range(2):
        try:
            return await target.evaluate(js)
        except PlaywrightError:
            if attempt == 0:
                try:
                    await target.wait_for_timeout(1500)
                except (PlaywrightError, AttributeError):
                    return default
            else:
                return default
    return default


async def _check_not_blocked(page) -> None:
    text = await _safe_eval(page, "() => document.body ? document.body.innerText : ''", "")
    # Real careers pages are long; a short page full of challenge wording is a wall.
    if len(text) < 2000 and BOT_WALL.search(text):
        raise BlockedError(
            "blocked by anti-bot interstitial; needs a manual check"
        )


async def _follow_to_job_index(page) -> bool:
    """Hop from a careers landing page to the page that actually lists openings.

    Several of these sites (Fathom, ev.energy) use the careers URL as a brochure
    page whose only job content is a 'View all jobs' link. One hop is enough;
    anything deeper is chasing a maze.
    """
    anchors = await _safe_eval(page, EXTRACT_JS, [])
    current = page.url.rstrip("/")
    best = None
    for a in anchors:
        href, text = a.get("href", ""), (a.get("text") or "").strip()
        if not href or href.rstrip("/") == current:
            continue
        by_text = bool(JOB_INDEX_TEXT.match(text))
        by_href = bool(JOB_INDEX_HREF.search(href))
        if not (by_text or by_href):
            continue
        # Prefer a link that matches on both signals.
        score = (2 if by_text and by_href else 1, -len(href))
        if best is None or score > best[0]:
            best = (score, href)

    if best is None:
        return False

    try:
        await page.goto(best[1], wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            await page.wait_for_timeout(1500)
        await _dismiss_cookies(page)
        await _expand(page)
        return True
    except (PWTimeout, PlaywrightError):
        return False


async def scrape_with_browser(browser: Browser, company: dict) -> list[Posting]:
    """Render a careers page and return every candidate posting found on it."""
    context = await browser.new_context(
        user_agent=USER_AGENT,
        locale="en-GB",
        timezone_id="Europe/London",
        viewport={"width": 1440, "height": 900},
        extra_http_headers={"Accept-Language": "en-GB,en;q=0.9"},
        ignore_https_errors=True,
    )
    try:
        page = await context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT_MS)
        try:
            await page.goto(
                company["careers_url"], wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS
            )
        except (PWTimeout, PlaywrightError):
            # Two things land here. Heavy SPAs (Notion-hosted boards especially)
            # miss domcontentloaded inside the budget while still being
            # perfectly renderable. And some sites are simply slow or flaky from
            # a datacentre IP -- Aira succeeds locally but ERR_TIMED_OUTs from
            # GitHub's US runners. Retry accepting the navigation as soon as it
            # commits, then give the app a fixed window to draw itself.
            await page.goto(company["careers_url"], wait_until="commit",
                            timeout=PAGE_TIMEOUT_MS)
            await page.wait_for_timeout(6000)
        # Best-effort settle: many of these pages never reach networkidle
        # (analytics beacons, polling), so a timeout here is not a failure.
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            await page.wait_for_timeout(1500)

        await _dismiss_cookies(page)
        await _check_not_blocked(page)
        await _expand(page)

        postings = await _collect(page)
        if not postings and await _follow_to_job_index(page):
            postings = await _collect(page)
        return postings
    finally:
        await context.close()


async def enrich_with_browser(browser: Browser, url: str) -> str | None:
    """Load one matched job page and return its visible text."""
    context = await browser.new_context(
        user_agent=USER_AGENT,
        locale="en-GB",
        viewport={"width": 1440, "height": 900},
        ignore_https_errors=True,
    )
    try:
        page = await context.new_page()
        page.set_default_timeout(DETAIL_TIMEOUT_MS)
        await page.goto(url, wait_until="domcontentloaded", timeout=DETAIL_TIMEOUT_MS)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PWTimeout:
            pass
        await _dismiss_cookies(page)
        # One "read more" expansion is reasonable; anything deeper is not.
        for label in ("Read more", "Show more", "See full description"):
            try:
                btn = page.get_by_role("button", name=label, exact=False)
                if await btn.count() and await btn.first.is_visible():
                    await btn.first.click(timeout=2500)
                    await page.wait_for_timeout(600)
                    break
            except (PWTimeout, PlaywrightError):
                continue
        text = await _safe_eval(page, "() => document.body ? document.body.innerText : ''", "")
        return re.sub(r"\s+", " ", text)[:20000] or None
    except (PWTimeout, PlaywrightError):
        return None
    finally:
        await context.close()
