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

Run with:  python manage.py test
Django builds a throwaway database for these, so your local db.sqlite3 is untouched.
"""

import csv
import io
import json
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Brief, BriefItem, Connection, Message, Person, Space

LIST_ROUTES = [
    "item-list-manual",        # 1. FBV, HttpResponse
    "item-list-render",        # 2. FBV, render()
    "item-list-cbv-base",      # 3. base CBV
    "item-list-cbv-generic",   # 4. generic ListView
]


def _build_demo_rows():
    """
    The smallest database that still exercises the whole spine:
    one work space, one brief, two items in two lanes, and one message with an author, so the
    relationship-spanning queries and the "receipts" have something to walk.

    Returns the Needs-you item, which is the one most tests act on.
    """
    now = timezone.now()
    user = User.objects.create_user("tester")
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


class ItemViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        user = User.objects.create_user("tester")
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


class NavigationAndUrlTests(TestCase):
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


class OrmQueryTests(TestCase):
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


class FormTests(TestCase):
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
        response = client.post(self.item.get_absolute_url(), {"state": "handled"})
        self.assertEqual(response.status_code, 403)


class ChartTests(TestCase):
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


class ApiTests(TestCase):
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


class ExportAndReportTests(TestCase):
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


class EmptyReportTests(TestCase):
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
