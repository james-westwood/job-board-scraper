"""Send the run summary to WhatsApp via CallMeBot.

Deliberately mirrors the homelab `cmb-notify` message format --
``<icon> [<host>] <message> - <timestamp>`` -- so these land looking like part
of the same alerting system rather than a fourth, separate alerter.

It cannot call cmb-notify itself: that lives on Muddlehead and reads
/etc/cmb-notify.conf, neither of which a GitHub runner can reach. So it talks
to the CallMeBot HTTPS API directly, with the same credentials supplied as
repository secrets.

Credentials come from CMB_PHONE / CMB_APIKEY in the environment. Missing
credentials are a warning, not a failure -- a broken notifier must never fail
an otherwise good scrape.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
HOST_LABEL = "job-scraper"
RAW_URL = (
    "https://raw.githubusercontent.com/james-westwood/job-board-scraper/main/output/latest.json"
)

ICONS = {"CRITICAL": "🚨", "WARNING": "⚠️", "SUCCESS": "✅", "INFO": "ℹ️"}

# WhatsApp will take far more than this, but a phone notification that needs
# scrolling defeats the point. Detail lives behind the link.
MAX_JOB_LINES = 6
MAX_NEAR_LINES = 4


def build_message(path: Path) -> tuple[str, str]:
    """Return (priority, message body)."""
    if not path.exists():
        return "CRITICAL", "Job scrape produced no output file - the run failed."

    data = json.loads(path.read_text(encoding="utf-8"))
    m, jobs, near = data["run_metadata"], data["jobs"], data.get("near_misses", [])

    attempted = m["companies_attempted"]
    succeeded = m["companies_succeeded"]
    failed = m.get("companies_failed") or []

    lines = [
        f"Job scrape: {succeeded}/{attempted} companies, "
        f"{m['total_postings_seen']} postings seen."
    ]

    if jobs:
        lines.append(f"\n{len(jobs)} match{'es' if len(jobs) != 1 else ''}:")
        for j in jobs[:MAX_JOB_LINES]:
            loc = j.get("location") or "location unknown"
            lines.append(f"- {j['company']}: {j['title']} ({loc})")
        if len(jobs) > MAX_JOB_LINES:
            lines.append(f"- ...and {len(jobs) - MAX_JOB_LINES} more")
    else:
        # Distinguish a quiet week from a broken scraper, which is the whole
        # reason both counters exist.
        dropped = m.get("total_postings_excluded_non_uk", 0)
        if dropped:
            lines.append(
                f"\nNo UK matches ({dropped} matching roles were overseas)."
            )
        else:
            lines.append("\nNo matches this week.")

    if near:
        lines.append(f"\n{len(near)} near miss{'es' if len(near) != 1 else ''}:")
        for n in near[:MAX_NEAR_LINES]:
            lines.append(f"- {n['company']}: {n['title']}")
        if len(near) > MAX_NEAR_LINES:
            lines.append(f"- ...and {len(near) - MAX_NEAR_LINES} more")

    if failed:
        lines.append("\nFailed (check by hand): " + ", ".join(f["name"] for f in failed))

    lines.append(f"\n{RAW_URL}")

    # Anything that failed outright is worth a WARNING colour, since those
    # companies are unknown rather than confirmed empty.
    priority = "WARNING" if failed else ("SUCCESS" if jobs else "INFO")
    return priority, "\n".join(lines)


def send(priority: str, body: str) -> int:
    phone, apikey = os.environ.get("CMB_PHONE"), os.environ.get("CMB_APIKEY")
    if not phone or not apikey:
        print("notify: CMB_PHONE/CMB_APIKEY not set, skipping WhatsApp send.")
        return 0

    icon = ICONS.get(priority, "📊")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    full = f"{icon} [{HOST_LABEL}] {body} - {stamp} UTC"

    query = urllib.parse.urlencode({"phone": phone, "text": full, "apikey": apikey})
    try:
        with urllib.request.urlopen(f"{CALLMEBOT_URL}?{query}", timeout=20) as r:
            resp = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - a failed notification must not fail the run
        print(f"notify: send failed: {type(e).__name__}: {e}")
        return 0

    if "queued" in resp.lower():
        print(f"notify: sent ({priority}).")
    else:
        print(f"notify: send may have failed. Response: {resp[:200]}")
    return 0


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "output/latest.json")
    priority, body = build_message(path)
    if "--dry-run" in sys.argv:
        print(f"[{priority}]\n{body}")
        return 0
    return send(priority, body)


if __name__ == "__main__":
    raise SystemExit(main())
