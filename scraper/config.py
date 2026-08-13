"""Match criteria and run-wide constants."""

SCRAPER_VERSION = "1.0.0"

# A posting matches if its title contains any of these (case-insensitive).
INCLUDE_KEYWORDS = [
    "data scientist",
    "data science",
    "data engineer",
    "analytics engineer",
    "analytics engineering",
    "machine learning engineer",
    "ml engineer",
    "mlops",
    "ai engineer",
    "applied scientist",
    "data platform",
]

# ...unless it also contains one of these, in which case it is dropped.
EXCLUDE_KEYWORDS = [
    "intern",
    "internship",
    "sales",
    "marketing manager",
    "account executive",
    "business development",
]

# Per-page budget before a company is written off as failed.
PAGE_TIMEOUT_MS = 30_000

# Shorter budget for the detail page of an already-matched job: we already have
# the posting, enrichment is a bonus, so don't spend the full page budget on it.
DETAIL_TIMEOUT_MS = 20_000

# Concurrent companies in flight. Each generic-adapter company holds one browser
# context, so this is also the browser memory ceiling.
MAX_CONCURRENCY = 7

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
