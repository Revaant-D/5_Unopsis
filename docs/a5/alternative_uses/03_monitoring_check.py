#!/usr/bin/env python3
"""
Alternative use 3 of the Unopsis public API: an unattended monitoring check.

The scenario: nobody is reading anything. This runs from cron every ten minutes on a small
box somewhere and says nothing at all unless the backlog of items waiting on a human crosses
a threshold, at which point it prints one alert line and exits non-zero -- which is the
convention cron, systemd timers, Nagios/Icinga, Jenkins and GitHub Actions all already
understand, so no integration code has to exist anywhere.

Two deliberate differences from the other two scripts in this folder, because this is a
different kind of program:

  * It imports nothing that is not in the standard library. A monitoring box should not need
    a pip install, a virtualenv or a requirements file to keep working; urllib is already
    there on every machine that has Python at all.
  * It distinguishes "the backlog is too big" (exit 1 -- a real alert about our data) from "I
    could not find out" (exit 2 -- an alert about the check itself). Collapsing those two is
    how a monitor goes quiet for a week while the thing it watches is on fire: a failed probe
    that exits 0 looks exactly like good news.

Run:
    python 03_monitoring_check.py

Configure without editing it, which is the whole point of a cron job:
    UNOPSIS_API=https://<your-pythonanywhere-domain> \
    UNOPSIS_MAX_NEEDS_YOU=10 \
    python 03_monitoring_check.py

Crontab line:
    */10 * * * * UNOPSIS_API=https://<your-pythonanywhere-domain> \
                 /usr/bin/python3 /path/to/03_monitoring_check.py

Requires: nothing. Python 3 standard library only.
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("UNOPSIS_API", "http://127.0.0.1:8000").rstrip("/")
ENDPOINT = f"{BASE_URL}/api/insights/items-by-lane/"
TIMEOUT_SECONDS = 10

# The lane being watched and the number above which it is worth waking somebody. Both are
# environment variables so the same file can be the staging check and the production check.
WATCHED_LANE = os.environ.get("UNOPSIS_WATCH_LANE", "needs_you")
THRESHOLD = int(os.environ.get("UNOPSIS_MAX_NEEDS_YOU", "3"))

EXIT_OK = 0
EXIT_ALERT = 1
EXIT_CHECK_FAILED = 2


def fetch_rows(url):
    """
    Return the feed's rows, or (None, reason) if the check itself could not run.

    This returns a reason instead of calling sys.exit() so that main() owns every exit code
    in one place; a monitoring script where any helper can exit is a script whose exit codes
    nobody can enumerate.
    """
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return None, f"HTTP {response.status} from {url}"
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # 302 is specifically interesting: the endpoint we monitor is supposed to be public,
        # so a redirect to the login page is a configuration change we want to hear about.
        return None, f"HTTP {exc.code} from {url} (is the endpoint still public?)"
    except urllib.error.URLError as exc:
        return None, f"could not reach {url} -- {exc.reason}"
    except TimeoutError:
        return None, f"{url} did not answer within {TIMEOUT_SECONDS}s"

    try:
        rows = json.loads(payload)
    except json.JSONDecodeError as exc:
        return None, f"{url} returned something that is not JSON ({exc})"

    if not isinstance(rows, list):
        return None, f"expected a JSON array from {url}, got {type(rows).__name__}"
    return rows, None


def main():
    rows, reason = fetch_rows(ENDPOINT)
    if reason is not None:
        print(f"CHECK FAILED: {reason}", file=sys.stderr)
        return EXIT_CHECK_FAILED

    match = next((row for row in rows if row.get("lane") == WATCHED_LANE), None)
    if match is None:
        # The feed answered, but not with the lane we watch. That is a schema change, not a
        # backlog problem, and it must not be reported as "0 items, all good".
        print(f"CHECK FAILED: no lane {WATCHED_LANE!r} in the feed "
              f"(saw: {[row.get('lane') for row in rows]})", file=sys.stderr)
        return EXIT_CHECK_FAILED

    count = match.get("total", 0)
    label = match.get("label", WATCHED_LANE)

    # "1 items" in an alert line is the detail that makes a monitor look unmaintained, and
    # the alert line is the only thing anybody ever reads from this program.
    noun = "item" if count == 1 else "items"

    if count > THRESHOLD:
        print(f"ALERT: {count} {noun} in '{label}' (threshold {THRESHOLD}) -- "
              f"the inbox is backing up. Source: {ENDPOINT}")
        return EXIT_ALERT

    print(f"OK: {count} {noun} in '{label}', at or under the threshold of {THRESHOLD}.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
