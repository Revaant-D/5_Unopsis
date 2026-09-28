"""
Tests for the whole project:

  * ItemViewTests           the four view kinds and the shared templates (previous assignment)
  * NavigationAndUrlTests   Section 1 -- the home page, named routes, get_absolute_url()
  * OrmQueryTests           Section 2 -- search, relationship spanning, aggregation
  * StaticFilesTests        Section 3 -- the custom stylesheet is configured and linked
  * ChartTests              Section 4 -- the matplotlib PNG endpoints
  * FormTests               Section 5 -- the GET form, the POST forms, CSRF

Run with:  python manage.py test
Django builds a throwaway database for these, so your local db.sqlite3 is untouched.
"""

from datetime import timedelta

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
        for name in ("home", "brief-list", "item-list-cbv-generic", "insights"):
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


class StaticFilesTests(TestCase):
    """Section 3: the stylesheet is configured and actually linked."""

    def test_the_custom_stylesheet_is_found_by_the_staticfiles_finders(self):
        self.assertIsNotNone(finders.find("css/unopsis.css"))
        self.assertIsNotNone(finders.find("img/unopsis-logo.svg"))

    def test_every_page_links_the_stylesheet_through_the_static_tag(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn(f'href="{static("css/unopsis.css")}"', html)
        self.assertIn(f'src="{static("img/unopsis-logo.svg")}"', html)
