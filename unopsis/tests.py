"""
Tests for the whole project:

  * ItemViewTests           the four view kinds and the shared templates (previous assignment)
  * NavigationAndUrlTests   Section 1 -- the home page, named routes, get_absolute_url()

Run with:  python manage.py test
Django builds a throwaway database for these, so your local db.sqlite3 is untouched.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
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
        for name in ("home", "brief-list", "item-list-cbv-generic"):
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
