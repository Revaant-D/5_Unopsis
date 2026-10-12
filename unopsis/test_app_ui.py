"""
Tests for the wireframe UI: ui.py, app_views.py, app_urls.py and the app templates.

Kept apart from tests.py on purpose. tests.py pins the graded course pages and this work does
not edit it. Django's runner finds this file by its test*.py name.

Run with:  python manage.py test unopsis.test_app_ui
"""

from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from . import ui
from .models import Brief, BriefItem, Connection, Message, Person, Space
from .templatetags.app_ui import initials, provider_letter

# Every GET page that takes no pk. Later tasks append their route names here.
APP_ROUTES = []


def build_two_worlds():
    """
    A work space and a personal space shaped like the wireframe:

      work      Gmail (Inbox + Clients) and Slack (#acme, #ops, #eng-releases), a brief of 212
                messages covering 14 hours, two Needs-you items, one Moving, one FYI, digests at
                08:00 and 16:30, quiet from 19:00, one always-rule and one never-rule;
      personal  a Discord connection in the error state and a one-item catch-up.

    Returns the rows the tests act on, by name.
    """
    now = timezone.now()
    user = User.objects.create_user("tester")
    work = Space.objects.create(
        user=user, kind=Space.Kind.WORK, digest_times=["08:00", "16:30"],
        quiet_start=time(19, 0), quiet_end=time(8, 0),
        rules=[{"mode": "always", "target": "person", "value": "Priya"},
               {"mode": "never", "target": "channel", "value": "#random"}],
    )
    personal = Space.objects.create(user=user, kind=Space.Kind.PERSONAL)
    gmail = Connection.objects.create(
        space=work, provider="gmail", external_account="me@work.example",
        included_scopes=[{"name": "Inbox"}, {"name": "Clients"}],
    )
    slack = Connection.objects.create(
        space=work, provider="slack", external_account="acme.slack.com",
        included_scopes=[{"name": "#acme"}, {"name": "#ops"}, {"name": "#eng-releases"}],
    )
    discord = Connection.objects.create(
        space=personal, provider="discord", external_account="me#0001",
        status=Connection.Status.ERROR, last_error="401 Unauthorized: token revoked.",
    )
    priya = Person.objects.create(space=work, display_name="Priya Shah")
    dan = Person.objects.create(space=work, display_name="Dan Ito")
    maya = Person.objects.create(space=personal, display_name="Maya")

    def message(connection, author, external_id, scope, body, minutes_ago, noise=False):
        return Message.objects.create(
            connection=connection, author=author, external_id=external_id, scope_name=scope,
            body=body, sent_at=now - timedelta(minutes=minutes_ago), is_noise=noise,
        )

    m_priya = message(gmail, priya, "g1", "Inbox", "Two edits. Can you approve so we can sign at 2?", 90)
    m_dan = message(slack, dan, "s1", "#acme", "Numbers check out on my side.", 60)
    m_noise = message(slack, dan, "s2", "#acme", "thanks!", 59, noise=True)
    m_payroll = message(slack, priya, "s3", "#ops", "Payroll cutoff moved to Wednesday noon.", 120)
    m_maya = message(discord, maya, "d1", "#launches", "Would you share your launch numbers?", 30)

    brief = Brief.objects.create(
        space=work, window_start=now - timedelta(hours=14), window_end=now,
        trigger=Brief.Trigger.SCHEDULED, status=Brief.Status.READY,
        headline="Two things need you before noon.", message_count=212, topic_count=18,
        read_seconds=90, generated_at=now - timedelta(minutes=5),
        steps=[{"label": "Pulled 212 messages from 2 sources", "status": "done", "ms": 3000},
               {"label": "Writing the brief", "status": "done", "ms": 4000}],
    )
    sow = BriefItem.objects.create(
        brief=brief, title="Acme wants the revised SOW today", lane=BriefItem.Lane.NEEDS_YOU,
        rank=1, summary="Priya replied with two edits.",
        why="A deadline today, and you are the only person who can unblock it.",
        draft_body="Approved as written. Go ahead and send for signature at 2.",
        primary_message=m_priya,
        actions=[{"kind": "reply", "label": "Approve the wording", "primary": True},
                 {"kind": "forward", "label": "Forward to legal", "primary": False}],
    )
    sow.messages.set([m_priya, m_dan, m_noise])
    payroll = BriefItem.objects.create(
        brief=brief, title="Payroll cutoff moved to Wednesday", lane=BriefItem.Lane.NEEDS_YOU,
        rank=2, summary="Finance asked each lead to confirm headcount.",
        actions=[{"kind": "confirm", "label": "Confirm", "primary": True}],
    )
    payroll.messages.set([m_payroll])
    moving = BriefItem.objects.create(
        brief=brief, title="Design landed the pricing page", lane=BriefItem.Lane.MOVING,
        rank=1, summary="QA picks it up Thursday.",
    )
    fyi = BriefItem.objects.create(
        brief=brief, title="Promotions suppressed", lane=BriefItem.Lane.FYI, rank=1,
        summary="Two promos were filtered.",
    )
    pbrief = Brief.objects.create(
        space=personal, window_start=now - timedelta(hours=6), window_end=now,
        trigger=Brief.Trigger.ON_DEMAND, status=Brief.Status.READY,
        headline="One thing wants a reply.", message_count=318, topic_count=9,
    )
    mention = BriefItem.objects.create(
        brief=pbrief, title="Maya asked for your launch numbers", lane=BriefItem.Lane.NEEDS_YOU,
        rank=1, summary="The thread moved on to pricing.",
        actions=[{"kind": "reply", "label": "Reply in thread", "primary": True}],
    )
    mention.messages.set([m_maya])
    return {
        "work": work, "personal": personal, "brief": brief, "pbrief": pbrief,
        "sow": sow, "payroll": payroll, "moving": moving, "fyi": fyi, "mention": mention,
        "gmail": gmail, "slack": slack, "discord": discord,
    }


def at(hour, minute=0):
    """An aware datetime today at hour:minute in the project timezone (UTC)."""
    return timezone.make_aware(datetime.combine(timezone.localdate(), time(hour, minute)))


class UiHelperTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rows = build_two_worlds()

    def test_connection_label_lists_two_scopes_and_counts_more(self):
        self.assertEqual(ui.connection_label(self.rows["gmail"]), "Gmail · Inbox + Clients")
        self.assertEqual(ui.connection_label(self.rows["slack"]), "Slack · 3 channels")

    def test_connection_label_survives_missing_or_malformed_scopes(self):
        self.assertEqual(ui.connection_label(Connection(provider="gmail")), "Gmail · everything")
        self.assertEqual(
            ui.connection_label(Connection(provider="gmail", included_scopes=["oops", {}])),
            "Gmail · everything",
        )

    def test_source_chips_group_receipts_busiest_first(self):
        item = BriefItem.objects.prefetch_related("messages__connection").get(pk=self.rows["sow"].pk)
        self.assertEqual(
            ui.source_chips(item),
            [{"label": "Slack #acme", "count": 2}, {"label": "Gmail", "count": 1}],
        )

    def test_next_digest_picks_the_next_slot_and_wraps_to_tomorrow(self):
        self.assertEqual(ui.next_digest(self.rows["work"], at(9)), time(16, 30))
        self.assertEqual(ui.next_digest(self.rows["work"], at(17)), time(8, 0))

    def test_next_digest_ignores_unparseable_times(self):
        space = Space(kind=Space.Kind.WORK, digest_times=["soon", "25:99", None])
        self.assertIsNone(ui.next_digest(space, at(9)))
        self.assertIsNone(ui.next_digest(None, at(9)))

    def test_snooze_until_is_the_next_digest_today_else_three_hours(self):
        self.assertEqual(ui.snooze_until(self.rows["work"], at(9)), at(16, 30))
        self.assertEqual(ui.snooze_until(self.rows["work"], at(17)), at(20))

    def test_quiet_message_count_subtracts_needs_you_citations_and_never_goes_negative(self):
        # 212 read, 4 distinct messages cited by the two Needs-you items.
        self.assertEqual(ui.quiet_message_count(self.rows["brief"]), 208)
        Brief.objects.filter(pk=self.rows["brief"].pk).update(message_count=1)
        self.rows["brief"].refresh_from_db()
        self.assertEqual(ui.quiet_message_count(self.rows["brief"]), 0)

    def test_window_hours_and_reading_load(self):
        self.assertEqual(ui.window_hours(self.rows["brief"]), 14)
        self.assertEqual(ui.daily_reading_load(self.rows["brief"]), 363)   # 212 * 24 / 14

    def test_lane_items_is_open_only_and_rank_ordered(self):
        titles = [i.title for i in ui.lane_items(self.rows["brief"], BriefItem.Lane.NEEDS_YOU)]
        self.assertEqual(titles, ["Acme wants the revised SOW today", "Payroll cutoff moved to Wednesday"])

    def test_primary_and_secondary_actions(self):
        self.assertEqual(ui.primary_action(self.rows["sow"])["label"], "Approve the wording")
        self.assertEqual([a["label"] for a in ui.secondary_actions(self.rows["sow"])], ["Forward to legal"])
        self.assertIsNone(ui.primary_action(self.rows["moving"]))

    def test_places_rank_what_wants_you_first(self):
        rows = ui.places(self.rows["personal"], self.rows["pbrief"])
        self.assertEqual(rows[0]["name"], "#launches")
        self.assertEqual(rows[0]["wants_you"], 1)
        self.assertEqual(ui.places(self.rows["personal"], None)[0]["wants_you"], 0)


class ApplyActionTests(TestCase):
    def setUp(self):
        self.rows = build_two_worlds()
        self.item = self.rows["sow"]

    def test_handle_stamps_handled_at_and_keeps_the_draft(self):
        ui.apply_action(self.item, "handle", at(9))
        self.item.refresh_from_db()
        self.assertEqual(self.item.state, BriefItem.State.HANDLED)
        self.assertEqual(self.item.handled_at, at(9))
        self.assertTrue(self.item.draft_body.startswith("Approved as written"))

    def test_snooze_sets_snoozed_until(self):
        ui.apply_action(self.item, "snooze", at(9))
        self.item.refresh_from_db()
        self.assertEqual(self.item.state, BriefItem.State.SNOOZED)
        self.assertEqual(self.item.snoozed_until, at(16, 30))

    def test_dismiss_records_negative_feedback(self):
        ui.apply_action(self.item, "dismiss", at(9))
        self.item.refresh_from_db()
        self.assertEqual((self.item.state, self.item.feedback), (BriefItem.State.DISMISSED, -1))

    def test_reopen_clears_the_clock_fields(self):
        ui.apply_action(self.item, "handle", at(9))
        ui.apply_action(self.item, "reopen", at(10))
        self.item.refresh_from_db()
        self.assertEqual(self.item.state, BriefItem.State.OPEN)
        self.assertIsNone(self.item.handled_at)
        self.assertIsNone(self.item.snoozed_until)

    def test_unknown_action_raises_and_changes_nothing(self):
        with self.assertRaises(ValueError):
            ui.apply_action(self.item, "delete", at(9))
        self.item.refresh_from_db()
        self.assertEqual(self.item.state, BriefItem.State.OPEN)


class EmptyDatabaseHelperTests(TestCase):
    def test_helpers_return_safe_defaults_with_no_rows(self):
        self.assertIsNone(ui.current_space(Space.Kind.WORK))
        self.assertIsNone(ui.latest_brief(None))
        self.assertEqual(list(ui.lane_items(None, BriefItem.Lane.NEEDS_YOU)), [])
        self.assertEqual(ui.window_hours(None), 0)
        self.assertEqual(ui.quiet_message_count(None), 0)
        self.assertEqual(ui.daily_reading_load(None), 0)
        self.assertEqual(ui.places(None, None), [])
        context = ui.sidebar_context(Space.Kind.WORK, None, None, timezone.now())
        self.assertEqual((context["needs_you_count"], context["connections"]), (0, []))


class TemplateFilterTests(TestCase):
    def test_initials(self):
        self.assertEqual(initials("Priya Shah"), "PS")
        self.assertEqual(initials("Prof. Ramirez"), "PR")
        self.assertEqual(initials("Mom"), "M")
        self.assertEqual(initials(""), "?")

    def test_provider_letter(self):
        self.assertEqual(provider_letter(Connection(provider="whatsapp_business")), "W")
        self.assertEqual(provider_letter("Gmail"), "G")
        self.assertEqual(provider_letter(None), "·")


APP_ROUTES += ["app-signup", "app-login"]


class ShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rows = build_two_worlds()

    def test_every_app_page_renders_inside_the_shell_and_base(self):
        for name in APP_ROUTES:
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "unopsis/app/shell.html")
                self.assertTemplateUsed(response, "base.html")

    def test_shell_links_back_to_the_course_pages(self):
        html = self.client.get(reverse("app-signup")).content.decode()
        self.assertIn(f'href="{reverse("home")}"', html)
        self.assertIn("Under the hood", html)

    def test_course_pages_keep_their_own_layout_and_link_into_the_app(self):
        response = self.client.get(reverse("brief-list"))
        self.assertTemplateNotUsed(response, "unopsis/app/shell.html")
        self.assertContains(response, f'href="{reverse("app-work-brief")}"')

    def test_app_stylesheet_only_loads_inside_the_shell(self):
        from django.templatetags.static import static
        self.assertContains(self.client.get(reverse("app-signup")), static("css/app.css"))
        self.assertNotContains(self.client.get(reverse("home")), static("css/app.css"))


class AuthScreenTests(TestCase):
    """A5 Part 1 wins over the wireframe: two separate pages, Django-shaped fields, Google only."""

    def test_login_and_signup_are_separate_pages(self):
        for name, active, heading in (
            ("app-signup", "Create account", "Know what happened, in one page a day."),
            ("app-login", "Sign in", "Welcome back."),
        ):
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertTemplateUsed(response, "unopsis/app/auth.html")
                self.assertContains(response, heading)
                self.assertContains(response, f'aria-current="page">{active}<')

    def test_fields_follow_django_auth_not_the_wireframe(self):
        login = self.client.get(reverse("app-login")).content.decode()
        signup = self.client.get(reverse("app-signup")).content.decode()
        self.assertIn(">Username<", login)
        self.assertIn(">Password<", login)
        self.assertNotIn("Work email", login + signup)
        for label in (">Username<", ">Email<", ">Password<", ">Confirm password<"):
            self.assertIn(label, signup)

    def test_auth_pages_submit_nothing(self):
        for name in ("app-signup", "app-login"):
            with self.subTest(route=name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertNotIn('method="post"', html)
                self.assertNotIn("name=", html.split("<main", 1)[1])   # no named inputs in the page

    def test_google_button_on_both_pages_disabled_until_a5_and_no_microsoft(self):
        for name in ("app-signup", "app-login"):
            with self.subTest(route=name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertIn("Continue with Google", html)
                self.assertIn("disabled", html)
                self.assertNotIn("Microsoft", html)
                self.assertNotIn("Digest", html)   # discrepancy 1: the brand is Unopsis


APP_ROUTES += ["app-setup-world", "app-setup-sources", "app-setup-scope", "app-setup-tuning"]


class SetupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rows = build_two_worlds()

    def test_each_step_marks_itself_current_in_the_rail(self):
        for number, name in enumerate(
            ["app-setup-world", "app-setup-sources", "app-setup-scope", "app-setup-tuning"], start=1
        ):
            with self.subTest(step=number):
                response = self.client.get(reverse(name))
                self.assertContains(response, "Setting up")
                self.assertContains(response, f"Setup · {number} of 4")
                self.assertContains(response, 'aria-current="step"')

    def test_world_shows_both_worlds_and_what_feeds_them(self):
        response = self.client.get(reverse("app-setup-world"))
        self.assertContains(response, "Which inbox life should I keep on top of?")
        self.assertContains(response, "Ranked by who is blocked and what has a deadline.")
        self.assertContains(response, "Ranked by mentions and by plans that changed.")
        self.assertContains(response, f'href="{reverse("app-setup-sources")}"')

    def test_sources_lists_every_provider_and_a_request_tile(self):
        response = self.client.get(reverse("app-setup-sources"))
        for label in ("Gmail", "Slack", "Outlook", "Discord", "WhatsApp Business", "iMessage"):
            self.assertContains(response, label)
        self.assertContains(response, "connected")
        self.assertContains(response, "can't sync")             # the Discord row is in error
        self.assertContains(response, "Request a source")
        self.assertContains(response, "Teams")                  # discrepancy 5
        self.assertContains(response, "2 connected")

    def test_scope_shows_included_scopes_and_the_reading_load(self):
        response = self.client.get(reverse("app-setup-scope"))
        for scope in ("#acme", "#ops", "#eng-releases", "Inbox", "Clients"):
            self.assertContains(response, scope)
        self.assertContains(response, "~363 messages a day")

    def test_tuning_shows_rules_schedule_quiet_hours_and_delivery(self):
        response = self.client.get(reverse("app-setup-tuning"))
        self.assertContains(response, "Priya")
        self.assertContains(response, "#random")
        self.assertContains(response, "8:00 AM")
        self.assertContains(response, "4:30 PM")
        self.assertContains(response, "7:00 PM – 8:00 AM")
        self.assertContains(response, f'href="{reverse("app-work-building")}"')


class EmptySetupTests(TestCase):
    def test_setup_pages_render_with_no_spaces(self):
        for name in ("app-setup-world", "app-setup-sources", "app-setup-scope", "app-setup-tuning"):
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class ItemActionTests(TestCase):
    def setUp(self):
        self.rows = build_two_worlds()
        self.sow = self.rows["sow"]
        self.url = reverse("app-item-action", args=[self.sow.pk])

    def test_handle_lands_on_the_wrap_up_with_an_undo_marker(self):
        response = self.client.post(self.url, {"action": "handle", "return_to": "handled"})
        self.assertRedirects(response, f'{reverse("app-work-handled")}?done={self.sow.pk}',
                             fetch_redirect_response=False)
        self.sow.refresh_from_db()
        self.assertEqual(self.sow.state, BriefItem.State.HANDLED)

    def test_dismiss_moves_on_to_the_next_open_item(self):
        response = self.client.post(self.url, {"action": "dismiss", "return_to": "next"})
        self.assertRedirects(response, reverse("app-work-focus", args=[self.rows["payroll"].pk]),
                             fetch_redirect_response=False)

    def test_next_after_the_last_item_is_the_wrap_up(self):
        url = reverse("app-item-action", args=[self.rows["payroll"].pk])
        response = self.client.post(url, {"action": "snooze", "return_to": "next"})
        self.assertRedirects(response, reverse("app-work-handled"), fetch_redirect_response=False)

    def test_personal_items_always_land_back_on_the_catch_up(self):
        url = reverse("app-item-action", args=[self.rows["mention"].pk])
        response = self.client.post(url, {"action": "handle", "return_to": "next"})
        self.assertRedirects(response, reverse("app-personal-catchup"), fetch_redirect_response=False)

    def test_missing_return_to_defaults_to_the_brief(self):
        response = self.client.post(self.url, {"action": "snooze"})
        self.assertRedirects(response, reverse("app-work-brief"), fetch_redirect_response=False)

    def test_unknown_action_is_a_400_and_changes_nothing(self):
        response = self.client.post(self.url, {"action": "delete"})
        self.assertEqual(response.status_code, 400)
        self.sow.refresh_from_db()
        self.assertEqual(self.sow.state, BriefItem.State.OPEN)

    def test_return_to_cannot_be_a_url(self):
        response = self.client.post(self.url, {"action": "handle", "return_to": "https://evil.example/"})
        self.assertEqual(response.status_code, 400)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_missing_item_is_a_404(self):
        response = self.client.post(reverse("app-item-action", args=[99999]), {"action": "handle"})
        self.assertEqual(response.status_code, 404)

    def test_csrf_token_is_required(self):
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post(self.url, {"action": "handle"}).status_code, 403)


APP_ROUTES += ["app-work-building", "app-work-brief", "app-personal-building"]


class WorkBriefTests(TestCase):
    def setUp(self):
        self.rows = build_two_worlds()

    def get(self):
        return self.client.get(reverse("app-work-brief"))

    def test_header_line_and_headline(self):
        response = self.get()
        self.assertContains(response, "Covers 14 hours · 212 messages · 2 sources")
        self.assertContains(response, "Two things need you before noon.")
        self.assertContains(response, "read time 90s")

    def test_needs_you_items_in_rank_order_with_source_chips(self):
        html = self.get().content.decode()
        self.assertLess(html.index("Acme wants the revised SOW today"),
                        html.index("Payroll cutoff moved to Wednesday"))
        self.assertIn("Slack #acme · 2", html)
        self.assertIn("Gmail · 1", html)
        self.assertIn(f'href="{reverse("app-work-focus", args=[self.rows["sow"].pk])}"', html)

    def test_first_item_offers_a_snooze_that_posts(self):
        html = self.get().content.decode()
        self.assertIn(f'action="{reverse("app-item-action", args=[self.rows["sow"].pk])}"', html)
        self.assertIn('value="snooze"', html)
        self.assertIn("csrfmiddlewaretoken", html)

    def test_moving_section_and_quiet_line(self):
        response = self.get()
        self.assertContains(response, "Moving without you")
        self.assertContains(response, "Design landed the pricing page")
        self.assertContains(response, "208 messages needed nothing from you.")
        self.assertContains(response, "Promotions suppressed")   # inside "Show anyway"

    def test_sidebar(self):
        response = self.get()
        self.assertContains(response, "Needs you · 2")
        self.assertContains(response, "Gmail · Inbox + Clients")
        self.assertContains(response, "Slack · 3 channels")
        self.assertContains(response, "quiet hours from 7 PM")

    def test_healthy_work_space_has_no_error_banner(self):
        self.assertNotContains(self.get(), "couldn't be read this time")

    def test_a_broken_work_connection_shows_the_error_banner(self):
        Connection.objects.filter(pk=self.rows["slack"].pk).update(
            status=Connection.Status.ERROR, last_error="401 Unauthorized: token revoked.")
        response = self.get()
        self.assertContains(response, "Slack couldn't be read this time.")
        self.assertContains(response, "Slack · can't sync")

    def test_handled_items_leave_the_brief(self):
        ui.apply_action(self.rows["sow"], "handle", timezone.now())
        response = self.get()
        self.assertContains(response, "Needs you · 1")
        self.assertNotContains(response, "Slack #acme · 2")


class BuildingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rows = build_two_worlds()

    def test_work_building_replays_the_stored_steps_and_the_funnel(self):
        response = self.client.get(reverse("app-work-building"))
        self.assertContains(response, "Reading 14 hours for you.")
        self.assertContains(response, "Pulled 212 messages from 2 sources")
        self.assertContains(response, "212 messages → 18 topics → 2 things that need you")
        self.assertContains(response, f'href="{reverse("app-work-brief")}"')
        self.assertContains(response, "data-animate-steps")

    def test_first_run_chip_shows_the_real_total_of_the_stored_steps(self):
        # 3000 ms + 4000 ms of stored steps -> "~7s", not a figure derived from the step count.
        self.assertContains(self.client.get(reverse("app-work-building")), "first run · ~7s")

    def test_personal_building_points_at_the_catch_up(self):
        response = self.client.get(reverse("app-personal-building"))
        self.assertContains(response, "Reading 6 hours for you.")
        self.assertContains(response, f'href="{reverse("app-personal-catchup")}"')


class EmptyWorkTests(TestCase):
    def test_brief_and_building_explain_the_emptiness(self):
        for name in ("app-work-brief", "app-work-building", "app-personal-building"):
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "seed_demo")


class FocusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rows = build_two_worlds()

    def get(self, item):
        return self.client.get(reverse("app-work-focus", args=[item.pk]))

    def test_position_why_and_navigation(self):
        response = self.get(self.rows["sow"])
        self.assertContains(response, "1 of 2")
        self.assertContains(response, "Why this is number one")
        self.assertContains(response, "A deadline today, and you are the only person who can unblock it.")
        self.assertContains(response, f'href="{reverse("app-work-focus", args=[self.rows["payroll"].pk])}"')
        self.assertContains(response, f'href="{reverse("app-thread", args=["work", self.rows["sow"].pk])}"')

    def test_buttons_post_and_carry_keyboard_shortcuts(self):
        html = self.get(self.rows["sow"]).content.decode()
        for key in ('data-key="e"', 'data-key="s"', 'data-key="j"'):
            self.assertIn(key, html)
        self.assertIn('value="dismiss"', html)          # "Not important"
        self.assertIn('Forward to legal', html)
        self.assertIn('disabled', html)                 # secondary actions never send

    def test_second_item_has_previous_but_no_next(self):
        html = self.get(self.rows["payroll"]).content.decode()
        self.assertIn("2 of 2", html)
        self.assertIn('data-key="k"', html)
        self.assertNotIn('data-key="j"', html)

    def test_item_without_why_or_receipt_time_still_renders(self):
        self.assertEqual(self.get(self.rows["payroll"]).status_code, 200)

    def test_personal_items_are_not_found_under_work(self):
        self.assertEqual(self.get(self.rows["mention"]).status_code, 404)

    def test_missing_item_is_a_404(self):
        self.assertEqual(self.client.get(reverse("app-work-focus", args=[99999])).status_code, 404)

    def test_needs_you_redirects_to_the_first_open_item(self):
        self.assertRedirects(self.client.get(reverse("app-work-needs-you")),
                             reverse("app-work-focus", args=[self.rows["sow"].pk]))


class EmptyFocusTests(TestCase):
    def test_needs_you_falls_back_to_the_brief(self):
        self.assertRedirects(self.client.get(reverse("app-work-needs-you")), reverse("app-work-brief"))


class ThreadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rows = build_two_worlds()

    def url(self, kind, item, **query):
        base = reverse("app-thread", args=[kind, item.pk])
        return base + ("?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else "")

    def test_receipts_in_order_with_noise_hidden_by_default(self):
        response = self.client.get(self.url("work", self.rows["sow"]))
        html = response.content.decode()
        self.assertLess(html.index("Two edits. Can you approve"), html.index("Numbers check out"))
        self.assertNotIn("thanks!", html)
        self.assertIn("1 message hidden", html)

    def test_show_all_includes_the_noise(self):
        self.assertContains(self.client.get(self.url("work", self.rows["sow"], show="all")), "thanks!")

    def test_unknown_show_value_is_ignored(self):
        response = self.client.get(self.url("work", self.rows["sow"], show="<script>"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "thanks!")

    def test_decision_panel_draft_copy_buttons_and_people(self):
        html = self.client.get(self.url("work", self.rows["sow"])).content.decode()
        self.assertIn("Needs a decision", html)
        self.assertIn("Approve the wording", html)
        self.assertIn("Approved as written. Go ahead and send for signature at 2.", html)
        self.assertIn('data-copy="#draft"', html)
        self.assertIn("Copy text", html)
        self.assertIn(">PS<", html)    # Priya Shah
        self.assertIn(">DI<", html)    # Dan Ito
        self.assertIn("nothing is sent from here", html)

    def test_item_without_a_draft_or_primary_message_still_renders(self):
        response = self.client.get(self.url("work", self.rows["payroll"]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-copy="#draft"')

    def test_personal_thread_uses_the_personal_rail(self):
        response = self.client.get(self.url("personal", self.rows["mention"]))
        self.assertContains(response, "Your places")
        self.assertContains(response, "Would you share your launch numbers?")

    def test_wrong_world_and_unknown_world_are_404(self):
        self.assertEqual(self.client.get(self.url("personal", self.rows["sow"])).status_code, 404)
        self.assertEqual(self.client.get(f"/elsewhere/thread/{self.rows['sow'].pk}/").status_code, 404)
        self.assertEqual(self.client.get(reverse("app-thread", args=["work", 99999])).status_code, 404)


APP_ROUTES += ["app-work-handled"]


class HandledTests(TestCase):
    def setUp(self):
        self.rows = build_two_worlds()
        self.url = reverse("app-work-handled")

    def test_counts_what_is_left_and_offers_each_primary_action(self):
        response = self.client.get(self.url)
        self.assertContains(response, "2 things left. About 4 minutes.")
        self.assertContains(response, "Approve the wording")
        self.assertContains(response, ">Confirm<")
        self.assertContains(response, 'value="handle"')

    def test_handled_today_lists_what_was_closed(self):
        ui.apply_action(self.rows["sow"], "handle", timezone.now())
        response = self.client.get(self.url)
        self.assertContains(response, "1 thing left. About 2 minutes.")
        self.assertContains(response, "Handled today")
        self.assertContains(response, f'href="{reverse("app-thread", args=["work", self.rows["sow"].pk])}"')

    def test_done_marker_shows_an_undo_that_reopens(self):
        ui.apply_action(self.rows["sow"], "handle", timezone.now())
        response = self.client.get(f"{self.url}?done={self.rows['sow'].pk}")
        self.assertContains(response, "marked handled")
        self.assertContains(response, 'value="reopen"')

    def test_bad_done_values_are_ignored(self):
        for value in ("abc", "99999", "-1", ""):
            with self.subTest(done=value):
                response = self.client.get(f"{self.url}?done={value}")
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'value="reopen"')

    def test_new_messages_since_the_brief_are_counted(self):
        Message.objects.create(
            connection=self.rows["gmail"], author=Person.objects.get(display_name="Dan Ito"),
            external_id="late-1", sent_at=timezone.now(), body="late message",
        )
        self.assertContains(self.client.get(self.url), "1 new message")

    def test_nothing_left(self):
        for item in (self.rows["sow"], self.rows["payroll"]):
            ui.apply_action(item, "handle", timezone.now())
        self.assertContains(self.client.get(self.url), "Nothing left.")


APP_ROUTES += ["app-personal-catchup", "app-personal-caught-up"]


class PersonalTests(TestCase):
    def setUp(self):
        self.rows = build_two_worlds()

    def test_catch_up_leads_with_what_wants_a_reply(self):
        response = self.client.get(reverse("app-personal-catchup"))
        self.assertContains(response, "You were gone 6 hours.")
        self.assertContains(response, "318 messages · 1 place · 1 want a reply")
        self.assertContains(response, "Maya asked for your launch numbers")
        self.assertContains(response, f'href="{reverse("app-thread", args=["personal", self.rows["mention"].pk])}"')
        self.assertContains(response, 'value="dismiss"')        # "Ignore"

    def test_rail_ranks_places_and_flags_the_broken_source(self):
        response = self.client.get(reverse("app-personal-catchup"))
        self.assertContains(response, "Your places — ranked by what wants you")
        self.assertContains(response, "#launches")
        self.assertContains(response, 'class="badge-count">1<')
        self.assertContains(response, "Discord · can't sync")

    def test_error_banner_for_the_broken_connection(self):
        response = self.client.get(reverse("app-personal-catchup"))
        self.assertContains(response, "Discord couldn't be read this time.")
        self.assertContains(response, "401 Unauthorized: token revoked.")

    def test_caught_up_empty_then_filled(self):
        url = reverse("app-personal-caught-up")
        self.assertContains(self.client.get(url), "Nothing marked done yet")
        ui.apply_action(self.rows["mention"], "handle", timezone.now())
        response = self.client.get(url)
        self.assertContains(response, "That was everything.")
        self.assertContains(response, "Maya asked for your launch numbers")
        # The next work digest depends on the wall clock (08:00 or 16:30 UTC), so accept either.
        self.assertRegex(response.content.decode(), r"Work brief (8:00 AM|4:30 PM)")
        self.assertContains(response, f'href="{reverse("app-setup-world")}"')
        self.assertContains(response, f'href="{reverse("app-journey")}"')


class EmptyPersonalTests(TestCase):
    def test_personal_pages_render_with_no_rows(self):
        for name in ("app-personal-catchup", "app-personal-caught-up"):
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "seed_demo")


APP_ROUTES += ["app-journey"]


class JourneyAndHomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rows = build_two_worlds()

    def test_journey_links_every_screen_in_order(self):
        html = self.client.get(reverse("app-journey")).content.decode()
        order = ["app-signup", "app-setup-world", "app-setup-sources", "app-setup-scope",
                 "app-setup-tuning", "app-work-building", "app-work-brief", "app-work-handled",
                 "app-personal-building", "app-personal-catchup", "app-personal-caught-up"]
        positions = [html.index(f'href="{reverse(name)}"') for name in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(f'href="{reverse("app-work-focus", args=[self.rows["sow"].pk])}"', html)
        self.assertIn(f'href="{reverse("app-thread", args=["work", self.rows["sow"].pk])}"', html)

    def test_home_hero_opens_the_app(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'href="{reverse("app-work-brief")}"')
        self.assertContains(response, f'href="{reverse("app-personal-catchup")}"')
        self.assertContains(response, f'href="{reverse("app-journey")}"')


class EmptyJourneyTests(TestCase):
    def test_journey_without_items_skips_the_item_screens(self):
        response = self.client.get(reverse("app-journey"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "needs a seeded item")


class NothingIsComingSoonTests(TestCase):
    def test_no_route_still_points_at_the_placeholder(self):
        from . import app_urls
        self.assertFalse(hasattr(app_urls, "soon"))
        for pattern in app_urls.urlpatterns:
            with self.subTest(route=pattern.name):
                self.assertNotEqual(pattern.callback.__name__, "coming_soon")


class ReviewFixTests(TestCase):
    """Findings from the whole-branch review: never 500 on bad input, never lose a snoozed item."""

    def setUp(self):
        self.rows = build_two_worlds()

    def test_unicode_digit_in_done_is_ignored_not_a_500(self):
        response = self.client.get(reverse("app-work-handled") + "?done=%C2%B2")   # "²"
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="reopen"')

    def test_a_snoozed_item_comes_back_once_its_time_has_passed(self):
        sow = self.rows["sow"]
        ui.apply_action(sow, "snooze", timezone.now())
        self.assertNotContains(self.client.get(reverse("app-work-brief")), "Acme wants the revised SOW today")
        BriefItem.objects.filter(pk=sow.pk).update(snoozed_until=timezone.now() - timedelta(minutes=1))
        response = self.client.get(reverse("app-work-brief"))
        self.assertContains(response, "Acme wants the revised SOW today")
        self.assertContains(response, "Needs you · 2")

    def test_building_survives_malformed_step_durations(self):
        Brief.objects.filter(pk=self.rows["brief"].pk).update(
            steps=[{"label": "Read", "ms": None}, {"label": "Ranked", "ms": "fast"}, {"label": "Wrote"}])
        response = self.client.get(reverse("app-work-building"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "first run · ~0s")

    def test_only_http_permalinks_are_opened(self):
        Message.objects.filter(external_id="g1").update(permalink="javascript:alert(1)")
        html = self.client.get(reverse("app-thread", args=["work", self.rows["sow"].pk])).content.decode()
        self.assertNotIn("javascript:", html)
        self.assertNotIn("data-open=", html)
        Message.objects.filter(external_id="g1").update(permalink="https://mail.example/g1")
        html = self.client.get(reverse("app-thread", args=["work", self.rows["sow"].pk])).content.decode()
        self.assertIn('data-open="https://mail.example/g1"', html)
