#!/usr/bin/env python3
"""
Alternative use 2 of the Unopsis public API: a bridge into a spreadsheet.

The scenario: the person who wants this data does not write Python at all. They live in Excel
or Google Sheets, and what they want is a column of lane names next to a column of numbers so
they can drop a pivot or a chart on top of it. JSON is not a thing a spreadsheet opens; CSV
is. This script is the two-line adapter between the two.

There are two ways to get there and this file documents both, because they fail differently:

  1. This script: fetch the JSON, write a .csv, open it. Works in Excel, works offline once
     written, and gives you a frozen snapshot -- which is what you want for a report that
     must still say the same thing next week.

  2. Google Sheets, live, no file in between: a six-line Apps Script custom function that
     calls the same URL and returns the rows into the grid, so the sheet re-reads production
     every time it recalculates. The script prints it at the end, along with the reason
     =IMPORTDATA() -- the formula everyone reaches for first -- cannot do this job: it parses
     CSV and HTML, never JSON. That is printed by the program rather than buried in a README
     because the person who needs it is looking at a terminal, not at our repo.

Run:
    python 02_csv_for_spreadsheets.py                 # writes ./unopsis_lane_counts.csv
    python 02_csv_for_spreadsheets.py /tmp/lanes.csv  # or wherever you want it

Point it at production without editing a line:
    UNOPSIS_API=https://<your-pythonanywhere-domain> python 02_csv_for_spreadsheets.py

Requires: requests (already in requirements.txt).
"""

import csv
import os
import sys
from datetime import datetime, timezone

import requests

BASE_URL = os.environ.get("UNOPSIS_API", "http://127.0.0.1:8000").rstrip("/")
ENDPOINT = f"{BASE_URL}/api/insights/items-by-lane/"
TIMEOUT_SECONDS = 10
DEFAULT_OUTPUT = "unopsis_lane_counts.csv"

# The column order of the CSV, which is also the order of the API's own keys. Writing it out
# explicitly rather than taking dict order means a new key appearing in the feed one day adds
# nothing silently to the middle of somebody's spreadsheet.
COLUMNS = ["lane", "label", "total"]


def fetch_rows(url):
    """GET the feed, or exit with a message that says which of the three failures happened."""
    try:
        response = requests.get(url, timeout=TIMEOUT_SECONDS)
    except requests.exceptions.Timeout:
        sys.exit(f"ERROR: {url} did not answer within {TIMEOUT_SECONDS}s.")
    except requests.exceptions.RequestException as exc:
        sys.exit(f"ERROR: could not reach {url} -- {exc}")

    if response.status_code != 200:
        sys.exit(f"ERROR: {url} answered HTTP {response.status_code}, expected 200.")

    try:
        rows = response.json()
    except ValueError:
        sys.exit(f"ERROR: {url} did not return JSON. First 200 bytes:\n{response.text[:200]}")

    if not isinstance(rows, list):
        sys.exit(f"ERROR: expected a JSON array, got {type(rows).__name__}.")
    return rows


def write_csv(rows, path):
    """
    Write the feed to `path` as CSV with a header row.

    newline="" is not decoration: without it the csv module's \\r\\n and the platform's own
    line ending both land in the file on Windows and every other row of the spreadsheet comes
    out blank. restval="" fills in a column the feed did not send rather than raising.
    """
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore", restval="")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTPUT
    rows = fetch_rows(ENDPOINT)
    write_csv(rows, path)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Fetched  {ENDPOINT}")
    print(f"Wrote    {path}  ({len(rows)} data rows + 1 header, as of {stamp})")
    print()
    print("File contents:")
    print("-" * 46)
    with open(path, encoding="utf-8") as handle:
        sys.stdout.write(handle.read())
    print("-" * 46)
    print()
    print("1. EXCEL / NUMBERS -- open the file directly.")
    print("   File > Open, pick the .csv. Columns A-C are lane, label, total; select B:C and")
    print("   Insert > Chart to get the same bar chart the Vega-Lite spec draws.")
    print()
    print("2. GOOGLE SHEETS, LIVE -- paste this into Extensions > Apps Script, save, then put")
    print("   =UNOPSIS_LANES() in a cell. It reads the public JSON feed directly, so the sheet")
    print("   refreshes from production instead of from a file somebody re-uploaded in March:")
    print()
    print('       function UNOPSIS_LANES() {')
    print('         var url = "https://<your-pythonanywhere-domain>/api/insights/items-by-lane/";')
    print('         var rows = JSON.parse(UrlFetchApp.fetch(url).getContentText());')
    print('         return [["lane", "label", "total"]].concat(')
    print('           rows.map(function (r) { return [r.lane, r.label, r.total]; }));')
    print('       }')
    print()
    print("3. GOOGLE SHEETS, =IMPORTDATA() -- worth knowing why it does NOT work here, because")
    print("   it is the first thing everyone tries. IMPORTDATA parses CSV and HTML, never JSON,")
    print("   and the project's CSV endpoint /api/items.csv is one of the ones Assignment 5 put")
    print("   behind a login, so Sheets receives the login page and shows you HTML. Use the")
    print("   Apps Script above for live data, or File > Import > Upload this .csv for a frozen")
    print("   snapshot.")


if __name__ == "__main__":
    main()
