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

# Titles that are data-adjacent but don't clear INCLUDE_KEYWORDS. These are
# reported separately as "near misses" rather than dropped, because the strict
# list has real blind spots: NESO advertised "Lead AI Architect" and "Data
# Assurance Lead", South East Water an "Investment Portfolio Data & Reporting
# Lead" -- all invisible to a keyword list built around "engineer"/"scientist".
#
# Deliberately excludes a bare "analyst": every company here has a dozen
# compliance/quality/service analysts, and they would swamp the list. Anything
# genuinely relevant ("Data Quality Analyst") is caught by the "data" token.
NEAR_MISS_KEYWORDS = [
    "data",
    "ai",
    "ml",
    "machine learning",
    "analytics",
    "scientist",
    "quantitative",
    "quant",
    "statistical",
    "statistics",
    "modelling",
    "modeling",
    "algorithm",
    "algorithms",
    "business intelligence",
    "llm",
    "generative ai",
]

# Per-company ceiling on near misses, so a big group-wide tenant can't flood
# the report with loosely-related roles.
MAX_NEAR_MISSES_PER_COMPANY = 25

# Keep only UK (and undetermined) roles. Several tracked companies hire
# globally -- BP, Workiva and Teledyne especially -- and their US/APAC postings
# swamp the report otherwise. Postings whose location cannot be determined are
# always kept, so this never silently bins a job.
UK_ONLY = True

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
