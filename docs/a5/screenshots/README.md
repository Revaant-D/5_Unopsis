# Assignment 5 screenshots — what to capture, and why each one

**Status: none of these exist yet, and none of them can be produced from a checkout.** Every
item below needs something this repository deliberately does not contain: the deployed
hostname, a real Google OAuth client, and a browser pointed at the live site. They are the
last step before submission and they belong to whoever does the deployment.

Drop each file in this folder under the filename given, and the links at the bottom of
[`../alternative_uses/README.md`](../alternative_uses/README.md) and in
[`../README.md`](../README.md) will resolve.

Before starting, set the environment variable the three programs read, so the production URL
is visible in the terminal output rather than only implied:

```bash
export UNOPSIS_API=https://<your-username>.pythonanywhere.com
```

## Part 1 — internal authentication

| File | What is in the shot | Why it is the evidence |
| --- | --- | --- |
| `01_login_page.png` | `/accounts/login/` on the **production domain**, URL bar legible | Part 1.1: the login page is ours, not Django's admin-styled default |
| `02_signup_page.png` | `/accounts/signup/` on the same domain | Part 1.1, the other half |
| `03_nav_logged_out.png` | The deployed home page in a **private/incognito window** | Part 1.5 "before": Briefs, Items, Insights, Reports and the API links are absent |
| `04_nav_logged_in.png` | The same page, same window size, after signing in | Part 1.5 "after": the same links present, plus the username and the Log out control |
| `05_protected_redirect.png` | `/reports/` requested in the incognito window | Part 1.4: an anonymous request lands on `/accounts/login/?next=/reports/`. The `?next=` in the URL bar is the part that matters |

A private window is not fussiness: it is what makes "logged out" visible to a reader who was
not there. A normal window with a stale session looks identical to a broken access check.

## Part 2 — Google OAuth

| File | What is in the shot | Why it is the evidence |
| --- | --- | --- |
| `06_google_button_live.png` | The deployed login page with **"Continue with Google" enabled** | With no credentials in `.env` the button renders *disabled* with an explanatory note. An enabled button is the proof the client is configured on the server |
| `07_google_cloud_redirect_uris.png` | Google Cloud Console → Credentials → the Web application client, showing the **Authorised redirect URIs** list | Part 2.3: both the localhost URI and the production one are registered. Crop or blank the client secret; the client id may stay |
| `08_google_consent.png` | Google's own account-chooser / consent screen, reached by clicking the button on the **production** site | Proves the redirect leaves our domain correctly rather than erroring |
| `09_signed_in_via_google.png` | Back on the deployed site, signed in, with the Google account's username in the navigation bar | The production clause: *"If OAuth works locally but fails in production, this is incomplete."* This is the shot that closes it |

The redirect URI to register is `/accounts/google/login/callback/` on each host. It is built by
allauth from the incoming request, so no hostname appears anywhere in this repository; the
exact strings are in [`../google-oauth-setup.md`](../google-oauth-setup.md).

## Part 3 — the public API, the chart, the three uses

| File | What is in the shot | Why it is the evidence |
| --- | --- | --- |
| `10_public_api_logged_out.png` | `/api/insights/items-by-lane/` in the **incognito window**, JSON on screen, production URL bar | Part 3.1: public, clean JSON, no login |
| `11_protected_api_logged_out.png` | `/api/items/` in the **same** window, landing on the login page | The contrast is the deliverable: same browser, two URLs, one open and one not |
| `12_vega_editor_chart.png` | <https://vega.github.io/editor/> with the spec from [`../vega_lite_chart.txt`](../vega_lite_chart.txt) pasted in, the placeholder replaced with the real host, and three bars rendered | Part 3.2/3.3. Both the editor URL and the `data.url` line must be legible — that is what shows the chart is pulling from the live API rather than from inline data |
| `13_use1_python_aggregation.png` | A terminal running `01_python_aggregation.py`, including the `export UNOPSIS_API=…` line above it and the share-of-total table it prints | Part 3.4, use 1 |
| `14_use2_terminal.png` | `02_csv_for_spreadsheets.py` running and writing `unopsis_lane_counts.csv` | Part 3.4, use 2 (half of it) |
| `15_use2_spreadsheet.png` | That CSV **open in Excel or Google Sheets, with a chart on it** | The half that actually demonstrates the use. A terminal alone does not show a spreadsheet use |
| `16_use3_monitoring.png` | `03_monitoring_check.py` run twice — once at the default threshold (the `ALERT:` line and `exit status: 1`) and once with `UNOPSIS_MAX_NEEDS_YOU=10` (the all-clear) | Part 3.4, use 3. Both states in one shot is more convincing than either alone |

## One thing to check before capturing anything

`/api/insights/items-by-lane/` reports **site-wide** counts, while every other view reports only
the signed-in account's own rows. That is deliberate — an aggregate over everybody is not a fact
about anybody, which is exactly why that feed can be published — but it means the number in shot
10 will not generally match the number on the signed-in `/insights/` page in shot 4. If a reader
would otherwise read that as a bug, say so in one line next to the pair.
