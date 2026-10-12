#!/usr/bin/env python3
"""
Alternative use 1 of the Unopsis public API: a stand-alone analysis script.

The scenario: somebody who is not us, and who has no account on our site, wants to know how
our triage workload is distributed -- what share of the backlog is actually waiting on a
human. They do not need our database, our code or our login; they need one URL. This script
is what that person writes. It pulls the live feed with `requests`, computes a share-of-total
table and a rank, and prints it as a formatted table.

The aggregation is done HERE, on the client, on purpose. The API hands out raw counts and
nothing else, which is what makes it reusable: percentages, ranks and a "needs you" ratio are
one reader's question, and baking them into the endpoint would have made it that reader's
endpoint instead of everybody's.

Run:
    python 01_python_aggregation.py

Point it somewhere else without editing a line:
    UNOPSIS_API=https://<your-pythonanywhere-domain> python 01_python_aggregation.py

Requires: requests (already in requirements.txt).
"""

import os
import sys

import requests

# The base URL comes from the environment so this file runs unchanged against a dev server
# today and against the deployed site later. A hard-coded hostname here is the thing that
# makes a script like this stale the day it is deployed.
BASE_URL = os.environ.get("UNOPSIS_API", "http://127.0.0.1:8000").rstrip("/")
ENDPOINT = f"{BASE_URL}/api/insights/items-by-lane/"
TIMEOUT_SECONDS = 10


def fetch_rows(url):
    """
    GET the public feed and return its rows, or exit with a readable message.

    Three different things can go wrong and they deserve three different sentences, because
    "it broke" sends the reader to the wrong place: the server may be unreachable (is it
    running? is the URL right?), it may answer with a status we did not expect (a 302 here
    would mean the endpoint is no longer public), or it may answer with something that is not
    the JSON we were promised (an HTML error page, typically).
    """
    try:
        response = requests.get(url, timeout=TIMEOUT_SECONDS)
    except requests.exceptions.Timeout:
        sys.exit(f"ERROR: {url} did not answer within {TIMEOUT_SECONDS}s.")
    except requests.exceptions.RequestException as exc:
        sys.exit(f"ERROR: could not reach {url} -- {exc}")

    if response.status_code != 200:
        # 302 is the interesting one: it is what a PROTECTED endpoint of this project
        # returns to an anonymous caller, so seeing it here means the public feed stopped
        # being public rather than that the network is down.
        hint = " (a redirect here means the endpoint now requires a login)" if \
            response.status_code in (301, 302) else ""
        sys.exit(f"ERROR: {url} answered HTTP {response.status_code}{hint}.")

    try:
        rows = response.json()
    except ValueError:
        sys.exit(f"ERROR: {url} did not return JSON. First 200 bytes:\n{response.text[:200]}")

    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        sys.exit(f"ERROR: expected a JSON array of objects, got {type(rows).__name__}.")
    return rows


def main():
    rows = fetch_rows(ENDPOINT)
    total = sum(row.get("total", 0) for row in rows)

    print("Unopsis brief items by lane")
    print(f"Source: {ENDPOINT}")
    print()

    if total == 0:
        # An empty backlog is a legitimate answer, not an error -- but dividing by it is not.
        print("The feed reports zero brief items, so there is no distribution to show.")
        return

    # Ranked by size, biggest share first. The API sends the lanes in the product's priority
    # order; this is the other question -- not "what should I look at first" but "where is
    # the work actually piling up".
    ranked = sorted(rows, key=lambda row: row.get("total", 0), reverse=True)

    header = f"{'#':>2}  {'Lane':<20} {'Items':>6} {'Share':>7}  Distribution"
    print(header)
    print("-" * len(header))
    for position, row in enumerate(ranked, start=1):
        count = row.get("total", 0)
        share = count / total * 100
        # A bar drawn in hashes: no plotting library, readable over ssh, and it makes the
        # shape of the distribution obvious at a glance in a terminal.
        bar = "#" * round(share / 4)
        print(f"{position:>2}  {row.get('label', '?'):<20} {count:>6} {share:>6.1f}%  {bar}")
    print("-" * len(header))
    print(f"{'':>2}  {'TOTAL':<20} {total:>6} {100.0:>6.1f}%")
    print()

    needs_you = next((row["total"] for row in rows if row.get("lane") == "needs_you"), 0)
    print(f"Waiting on a human: {needs_you} of {total} items "
          f"({needs_you / total * 100:.1f}% of the backlog).")


if __name__ == "__main__":
    main()
