# Three alternative uses of the Unopsis public API

Assignment 5, Part 3.4.

Everything in this folder reads one URL and nothing else:

```
GET <base>/api/insights/items-by-lane/
```

That endpoint needs no login, no API key and no account on our site. It returns a bare JSON
array of aggregate counts — `[{"lane": ..., "label": ..., "total": ...}, ...]` — and nothing
anybody typed. Every other JSON endpoint in the project (`/api/items/`, `/api/insights/`,
`/api/insights/messages-by-hour/`, the two exports) requires a session and answers an
anonymous caller with a 302 to `/accounts/login/`. The evidence for that contrast, taken from
a running server, is in [`../api_access_check.txt`](../api_access_check.txt).

The point of the three programs below is that they were written **for three different people**
— an analyst, a spreadsheet user, and a machine that nobody is watching — and none of them
needed us to change the API. That is what a public endpoint buys you.

## Running them

Each program is standalone: no shared module, no package, copy one file anywhere and it works.

```bash
# against a local dev server (the default — nothing to set)
python manage.py runserver          # in another terminal, from the project root
python 01_python_aggregation.py

# against the deployed site, same files, no edit
export UNOPSIS_API=https://<your-pythonanywhere-domain>
python 01_python_aggregation.py
```

The base URL comes from the `UNOPSIS_API` environment variable in all three, defaulting to
`http://127.0.0.1:8000`. A hard-coded hostname is what makes a script like this stale the day
the site is deployed, so there is not one anywhere in this folder.

All three handle a timeout, an unreachable host, a non-200 status and a body that is not JSON
with a message naming which of those happened, rather than a traceback. A 302 in particular is
called out by name, because that is what this project's *protected* endpoints return — seeing
one here would mean the public feed had stopped being public, not that the network was down.

## 1. `01_python_aggregation.py` — analysis in a Python script

Pulls the live feed with `requests` and computes something the API deliberately does not:
share-of-total percentages, a ranking by size, and a text bar chart, printed as a formatted
table. The aggregation is done on the client on purpose — the endpoint hands out raw counts,
which is exactly what makes it reusable, because "what percentage is waiting on a human" is
one reader's question and baking it into the endpoint would have made it that reader's
endpoint instead of everybody's. Real output: [`sample_output_1.txt`](sample_output_1.txt).

## 2. `02_csv_for_spreadsheets.py` — a bridge into Excel and Google Sheets

For the person who does not write Python at all. It converts the live JSON into a `.csv` that
Excel, Numbers or Sheets opens directly (`unopsis_lane_counts.csv` in this folder is a real
one it produced), and then prints the two ways into Google Sheets: a six-line Apps Script
custom function `=UNOPSIS_LANES()` that reads the JSON feed live, and an explanation of why
the obvious `=IMPORTDATA()` cannot — it parses CSV and HTML, never JSON, and this project's
CSV endpoint is behind the login, so Sheets would receive the login page. Real output:
[`sample_output_2.txt`](sample_output_2.txt).

## 3. `03_monitoring_check.py` — an unattended cron check

Nobody reads this one. It runs from cron, says nothing unless the backlog of items waiting on
a human crosses a threshold, and then prints one alert line and exits non-zero — the
convention cron, systemd, Jenkins, Nagios and GitHub Actions already understand, so no
integration code has to exist. It imports nothing outside the standard library, because a
monitoring box should not need a `pip install` to keep working, and it separates "the backlog
is too big" (exit 1) from "I could not find out" (exit 2): a failed probe that exits 0 is how
a monitor goes quiet for a week while the thing it watches is on fire. Real output, including
all three exit codes: [`sample_output_3.txt`](sample_output_3.txt).

## Screenshots

The sample outputs here are genuine stdout from real runs against a live server, captured
automatically — but they are text files, and the assignment asks for screenshots.

The full checklist, for all three parts of Assignment 5 and not only these three programs,
lives in [`../screenshots/README.md`](../screenshots/README.md): sixteen shots, each with what
has to be in frame and why it is the evidence for a particular numbered requirement. The four
that belong to this folder are `13_use1_python_aggregation.png`, `14_use2_terminal.png`,
`15_use2_spreadsheet.png` and `16_use3_monitoring.png`.

None of them can be produced from a checkout: every one needs the deployed hostname, which is
not in this repository and is not supposed to be. Set `UNOPSIS_API` to the production URL
first, so the `Source:` line in each program's own output names the live API rather than
localhost — that line is what makes the screenshot evidence rather than decoration.
