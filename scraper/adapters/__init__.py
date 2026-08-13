"""Per-company strategies for turning a careers site into a list of Postings.

Two families:

* ``api``     -- a JSON endpoint exists; cheap, reliable, no browser.
* ``browser`` -- the page renders client-side, so Playwright drives it.

Always prefer an api adapter where one exists. The browser adapter is the
fallback, not the default.
"""

from .api import API_ADAPTERS
from .browser import scrape_with_browser

__all__ = ["API_ADAPTERS", "scrape_with_browser"]
