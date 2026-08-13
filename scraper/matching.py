"""Title matching, salary parsing and work-arrangement detection.

Deliberately conservative: when a field cannot be read off the page it comes back
as None/"unknown" rather than a guess, and a job is never dropped for missing
salary or work arrangement.
"""

from __future__ import annotations

import re

from .config import EXCLUDE_KEYWORDS, INCLUDE_KEYWORDS

_WS = re.compile(r"\s+")


def normalise(text: str | None) -> str:
    return _WS.sub(" ", (text or "")).strip()


def match_title(title: str) -> str | None:
    """Return the include-keyword the title matched, or None.

    Exclusions win over inclusions, so 'Data Science Intern' is dropped.
    """
    t = normalise(title).lower()
    if not t:
        return None
    if any(bad in t for bad in EXCLUDE_KEYWORDS):
        return None
    for kw in INCLUDE_KEYWORDS:
        if kw in t:
            return kw
    return None


# --------------------------------------------------------------------------
# Salary
# --------------------------------------------------------------------------

# The bare number in a salary: 55,000 / 55k / 55000.
_NUM = r"(\d{1,3}(?:,\d{3})+|\d{2,3}(?:\.\d)?\s*k\b|\d{5,6})"
_DASH = r"\s*(?:-|–|—|to)\s*"

# "£55,000 - £65,000" (the second £ optional).
_RANGE_RE = re.compile(rf"£\s*{_NUM}{_DASH}(?:£\s*)?{_NUM}", re.IGNORECASE)

# "55,000 - 65,000 GBP" / "55k-65k per annum" -- no £ sign, so require a
# trailing currency or period cue to avoid matching arbitrary number ranges.
_RANGE_LOOSE_RE = re.compile(
    rf"{_NUM}{_DASH}{_NUM}\s*(?:gbp|per annum|pa\b|p\.a\.)", re.IGNORECASE
)

_SINGLE_RE = re.compile(
    rf"(?:up to|from|circa|c\.|around|salary of)?\s*£\s*{_NUM}", re.IGNORECASE
)

# Non-sterling pay (common on the US-heavy Workday tenants). Worth surfacing
# verbatim so James can see the number, but never converted -- the output field
# is explicitly *_gbp, and a made-up FX rate would be worse than a null.
_FOREIGN_RANGE_RE = re.compile(rf"[$€]\s*{_NUM}{_DASH}(?:[$€]\s*)?{_NUM}", re.IGNORECASE)
_FOREIGN_SINGLE_RE = re.compile(
    rf"(?:up to|from|circa|around|salary of)?\s*[$€]\s*{_NUM}", re.IGNORECASE
)

# Contexts where a number is a rate, not an annual salary -- don't parse those
# into min/max, but still keep the raw string for a human to read.
_NON_ANNUAL = re.compile(r"per\s+(?:day|hour|diem)|daily rate|hourly|/day|/hr|per hr", re.I)

_SALARY_CUE = re.compile(
    r"salary|compensation|remuneration|£|[$€]|\b(?:gbp|usd|eur)\b|per annum|\bpa\b|package", re.I
)


def _to_int(raw: str) -> int | None:
    s = raw.strip().lower().replace(",", "").replace(" ", "")
    try:
        if s.endswith("k"):
            return int(float(s[:-1]) * 1000)
        return int(float(s))
    except ValueError:
        return None


def _plausible(v: int | None) -> bool:
    # Filters out years ("2025"), headcounts and phone numbers that happen to
    # sit next to a pound sign.
    return v is not None and 15_000 <= v <= 500_000


def parse_salary(text: str | None) -> tuple[str | None, int | None, int | None]:
    """Return (salary_raw, min_gbp, max_gbp).

    salary_raw is the verbatim matched string so a human can sanity-check the
    parse; min/max are None whenever parsing is not confident.
    """
    if not text:
        return None, None, None
    body = normalise(text)
    if not _SALARY_CUE.search(body):
        return None, None, None

    for rx in (_RANGE_RE, _RANGE_LOOSE_RE):
        for m in rx.finditer(body):
            lo, hi = _to_int(m.group(1)), _to_int(m.group(2))
            window = body[max(0, m.start() - 40) : m.end() + 40]
            if _NON_ANNUAL.search(window):
                return m.group(0).strip(), None, None
            if _plausible(lo) and _plausible(hi) and lo <= hi:
                return m.group(0).strip(), lo, hi

    for m in _SINGLE_RE.finditer(body):
        val = _to_int(m.group(1))
        window = body[max(0, m.start() - 40) : m.end() + 40]
        if not _plausible(val):
            continue
        raw = m.group(0).strip()
        if _NON_ANNUAL.search(window):
            return raw, None, None
        if re.match(r"^\s*up to", raw, re.I):
            return raw, None, val
        if re.match(r"^\s*(from|circa|c\.|around)", raw, re.I):
            return raw, val, None
        return raw, val, val

    # Nothing in sterling -- fall back to reporting a foreign figure verbatim,
    # with no GBP parse.
    for rx in (_FOREIGN_RANGE_RE, _FOREIGN_SINGLE_RE):
        for m in rx.finditer(body):
            vals = [_to_int(g) for g in m.groups() if g]
            if vals and all(_plausible(v) for v in vals):
                return m.group(0).strip(), None, None

    return None, None, None


# --------------------------------------------------------------------------
# Work arrangement
# --------------------------------------------------------------------------

# A bare "hybrid" or "remote" anywhere in a long job description means nothing --
# BP sells hybrid vehicles, Teledyne makes hybrid circuits, and half of these
# companies mention "remote sensing". So the body text only counts when the word
# is used in an actual working-pattern phrase.
_HYBRID_PHRASE = re.compile(
    r"\bhybrid\s*(?:working|work|role|position|model|arrangement|schedule|basis|"
    r"pattern|approach|set[- ]?up|policy|environment)\b"
    r"|\b(?:working|work|role|position|policy)\s*(?:is|:)?\s*hybrid\b"
    r"|\bhybrid\s*[:(\-]",
    re.I,
)
_REMOTE_PHRASE = re.compile(
    r"\b(?:fully|100%|entirely|permanently)\s*remote\b"
    r"|\bremote[- ](?:first|working|work|role|position|based|friendly|opportunity)\b"
    r"|\bwork(?:ing)?\s+from\s+home\b"
    r"|\bwork\s+remotely\b"
    r"|\bremote\s*[:(\-]",
    re.I,
)
_ONSITE_PHRASE = re.compile(
    r"\bon[- ]?site\b|\bin[- ]?office\b|\boffice[- ]based\b|\bin the office\b"
    r"|\bin person\b|\bfully on[- ]?site\b",
    re.I,
)

# "Remote" appearing in the location field is a much stronger signal than in
# free text -- that field is structured and short.
_LOC_REMOTE = re.compile(r"\bremote\b|\bwork from home\b|\bwfh\b", re.I)
_LOC_HYBRID = re.compile(r"\bhybrid\b", re.I)

_REMOTE_NEGATED = re.compile(
    r"\bnot?\s+remote\b|\bno remote\b|remote work is not|not a remote", re.I
)

_DAYS_DETAIL = re.compile(
    r"(\d\s*(?:-|–|to)\s*\d|\d|one|two|three|four)\s*days?\s*(?:per|a|/|each)?\s*week"
    r"(?:[^.]{0,40}?(?:office|site|hq))?",
    re.I,
)
_DETAIL_CONTEXT = re.compile(r"office|site|hq|onsite|in person", re.I)


def detect_work_arrangement(
    title: str | None = None,
    location: str | None = None,
    body: str | None = None,
) -> tuple[str | None, str | None, str]:
    """Return (arrangement, detail, confidence).

    ``location`` and ``title`` are short structured fields, so a match there is
    trusted directly. ``body`` is long free text, so it only counts when the
    keyword appears in a genuine working-pattern phrase.

    confidence is 'stated' when the page says it explicitly, 'inferred' when
    deduced from weaker signals, 'unknown' when there is nothing to go on.
    """
    loc = normalise(location)
    head = normalise(f"{title or ''} {location or ''}")
    text = normalise(body)
    if not (head or text):
        return None, None, "unknown"

    detail = None
    m = _DAYS_DETAIL.search(text)
    if m:
        window = text[max(0, m.start() - 60) : m.end() + 60]
        if _DETAIL_CONTEXT.search(window):
            detail = normalise(m.group(0))

    negated = bool(_REMOTE_NEGATED.search(text))

    # 1. Structured fields win outright.
    if _LOC_HYBRID.search(head):
        return "hybrid", detail, "stated"
    if _LOC_REMOTE.search(head) and not negated:
        return "remote", detail, "stated"

    # 2. Then explicit working-pattern phrasing in the body.
    has_hybrid = bool(_HYBRID_PHRASE.search(text))
    has_remote = bool(_REMOTE_PHRASE.search(text)) and not negated
    has_onsite = bool(_ONSITE_PHRASE.search(text))

    if has_hybrid:
        return "hybrid", detail, "stated"
    if has_remote and has_onsite:
        # Both patterns described and no "hybrid" wording -- a split week is the
        # most likely reading, but we are reading between the lines.
        return "hybrid", detail, "inferred"
    if has_remote:
        return "remote", detail, "stated"
    if has_onsite:
        return "onsite", detail, "stated"

    # 3. A stated days-in-office split implies hybrid even with no label.
    if detail:
        return "hybrid", detail, "inferred"

    # 4. A named office location and no working-pattern wording at all is weak
    #    evidence of onsite -- worth recording, clearly flagged as a guess.
    if loc and not _LOC_REMOTE.search(loc):
        return "onsite", None, "inferred"

    return None, None, "unknown"
