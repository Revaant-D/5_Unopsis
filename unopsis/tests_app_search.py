"""
Tests for /search/ (ai_views.app_search): semantic search inside the app, plus the sign-in
warm-up (unopsis/ai/warmup.py).

No model is ever loaded. View tests replace semantic_search.search / ask.answer_question with
mocks that return rows built from real seeded messages. The ownership test runs the real search
with the bag-of-words fake_encode from tests_ai_search, so only the model is faked.
"""

from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .ai import ask, semantic_search, warmup
from .management.commands.seed_demo import seed_demo_data
from .models import BriefItem, Message
from .tests_ai_search import fake_encode

URL = "/search/"


def outcome_for(messages, query="q", mode="semantic", score=0.42):
    """What semantic_search.search() returns, for the given Message rows."""
    return {
        "query": query, "cleaned": query, "mode": mode, "k": 5, "min_score": 0.25,
        "model": "fake", "dropped": 0, "index_ms": 0, "ms": 3, "note": "",
        "results": [semantic_search._row(m, None if mode == "keyword" else score) for m in messages],
    }


class AppSearchTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", password="pw-123456!")
        cls.other = User.objects.create_user("other", password="pw-123456!")
        seed_demo_data(cls.owner)
        seed_demo_data(cls.other)

    def setUp(self):
        cache.clear()
        semantic_search._index.clear()
        self.client.force_login(self.owner)

    def msg(self, external_id, user=None):
        return Message.objects.get(external_id=external_id,
                                   connection__space__user=user or self.owner)

    # ------------------------------------------------------------------ access and states

    def test_signed_out_redirects_to_login(self):
        self.client.logout()
        response = self.client.get(URL, {"q": "mom"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_first_visit_shows_the_form_and_examples(self):
        with mock.patch.object(semantic_search, "search") as search:
            response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        search.assert_not_called()
        self.assertTemplateUsed(response, "unopsis/app/search.html")
        self.assertContains(response, 'name="q"')
        self.assertContains(response, "what did my mom say?")

    def test_world_parameter_alone_is_not_an_error(self):
        response = self.client.get(URL, {"world": "personal"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Catch up")           # the personal rail

    def test_unknown_world_falls_back_to_work(self):
        response = self.client.get(URL, {"world": "elsewhere"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["world"], "work")

    def test_empty_query_gets_a_friendly_message(self):
        with mock.patch.object(semantic_search, "search") as search:
            response = self.client.get(URL, {"q": "   "})
        self.assertEqual(response.status_code, 400)
        search.assert_not_called()
        self.assertContains(response, "Type a few words to search for.", status_code=400)

    def test_too_long_query_is_rejected(self):
        with mock.patch.object(semantic_search, "search") as search:
            response = self.client.get(URL, {"q": "x" * 400})
        self.assertEqual(response.status_code, 400)
        search.assert_not_called()

    def test_nothing_matched_is_plain_language(self):
        with mock.patch.object(semantic_search, "search", return_value=outcome_for([])):
            response = self.client.get(URL, {"q": "pizza recipe"})
        self.assertContains(response, "Nothing in your messages matches that.")
        self.assertNotContains(response, "cosine")
        self.assertNotContains(response, "threshold")

    def test_keyword_fallback_is_explained(self):
        with mock.patch.object(semantic_search, "search",
                               return_value=outcome_for([self.msg("m-v1")], mode="keyword")):
            response = self.client.get(URL, {"q": "invoice"})
        self.assertContains(response, "exact word matches")

    # ------------------------------------------------------------------ results → threads

    def test_result_links_to_the_thread_that_cites_it(self):
        mom3 = self.msg("w-mom3")
        item = BriefItem.objects.filter(messages=mom3).select_related("brief__space").first()
        self.assertIsNotNone(item, "seed data: an item should cite w-mom3")
        with mock.patch.object(semantic_search, "search", return_value=outcome_for([mom3])):
            response = self.client.get(URL, {"q": "grandma dinner"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("app-thread", args=[item.brief.space.kind, item.pk]))
        self.assertContains(response, "grandma&#x27;s birthday dinner")
        self.assertContains(response, 'id="r1"')

    def test_message_without_an_item_says_not_in_a_brief(self):
        loose = (Message.objects.filter(connection__space__user=self.owner, brief_items__isnull=True)
                 .first())
        self.assertIsNotNone(loose, "seed data: some message should not be cited by any item")
        with mock.patch.object(semantic_search, "search", return_value=outcome_for([loose])):
            response = self.client.get(URL, {"q": "anything"})
        self.assertContains(response, "Not in a brief")
        self.assertNotContains(response, "Open “")

    def test_noise_message_link_shows_hidden_messages(self):
        noisy = (Message.objects.filter(connection__space__user=self.owner, is_noise=True,
                                        brief_items__isnull=False).first())
        if noisy is None:
            self.skipTest("seed data has no cited noise message")
        with mock.patch.object(semantic_search, "search", return_value=outcome_for([noisy])):
            response = self.client.get(URL, {"q": "cart"})
        self.assertContains(response, "?show=all")

    def test_another_users_messages_never_appear(self):
        """Real search (only the model is faked): owner and other have identical seed text."""
        other_ids = set(Message.objects.filter(connection__space__user=self.other)
                        .values_list("pk", flat=True))
        with mock.patch.object(semantic_search, "encode", side_effect=fake_encode):
            response = self.client.get(URL, {"q": "staging deploy failed"})
        rows = response.context["outcome"]["results"]
        self.assertTrue(rows)
        self.assertFalse({r["id"] for r in rows} & other_ids)
        for row in rows:
            if row["item"] is not None:
                self.assertEqual(row["item"].brief.space.user, self.owner)

    def test_thread_links_only_use_the_users_own_brief_items(self):
        """Even if another account's item cited this user's message, it is never linked."""
        mom1 = self.msg("w-mom1")
        foreign = BriefItem.objects.filter(brief__space__user=self.other).first()
        foreign.messages.add(mom1)          # bad data on purpose: a cross-account citation
        with mock.patch.object(semantic_search, "search", return_value=outcome_for([mom1])):
            response = self.client.get(URL, {"q": "did you eat"})
        row = response.context["outcome"]["results"][0]
        self.assertTrue(row["item"] is None or row["item"].brief.space.user == self.owner)
        self.assertNotContains(response, reverse("app-thread", args=[foreign.brief.space.kind, foreign.pk]))

    # ------------------------------------------------------------------ the answer card

    def test_answer_citations_become_links_to_results(self):
        rows = [self.msg("w-mom3"), self.msg("w-mom2")]
        answer = {"status": "ok", "answer": "Sunday at 6 [1]. Also see [9].", "cited": [], "note": "",
                  "raw": "", "ms": 5, "model": "fake"}
        with mock.patch.object(semantic_search, "search", return_value=outcome_for(rows)), \
                mock.patch.object(ask, "answer_question", return_value=answer):
            response = self.client.get(URL, {"q": "grandma dinner", "ask": "on"})
        self.assertContains(response, '<a class="cite" href="#r1"')
        self.assertNotContains(response, 'href="#r9"')      # [9] points at nothing: left as text
        self.assertContains(response, "[9]")

    def test_answer_text_is_escaped(self):
        answer = {"status": "ok", "answer": "<script>alert(1)</script> [1]", "cited": [], "note": "",
                  "raw": "", "ms": 5, "model": "fake"}
        with mock.patch.object(semantic_search, "search", return_value=outcome_for([self.msg("w-mom3")])), \
                mock.patch.object(ask, "answer_question", return_value=answer):
            response = self.client.get(URL, {"q": "grandma", "ask": "on"})
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_answer_problems_are_explained_in_plain_words(self):
        answer = {"status": "unavailable", "answer": "", "cited": [], "note": "torch missing",
                  "raw": "", "ms": 0, "model": "fake"}
        with mock.patch.object(semantic_search, "search", return_value=outcome_for([self.msg("w-mom3")])), \
                mock.patch.object(ask, "answer_question", return_value=answer):
            response = self.client.get(URL, {"q": "grandma", "ask": "on"})
        self.assertContains(response, "The answer assistant isn")
        self.assertNotContains(response, "torch missing")

    def test_no_answer_unless_asked(self):
        with mock.patch.object(semantic_search, "search", return_value=outcome_for([self.msg("w-mom3")])), \
                mock.patch.object(ask, "answer_question") as answer:
            self.client.get(URL, {"q": "grandma"})
        answer.assert_not_called()

    @override_settings(AI_REQUESTS_PER_MINUTE=0)
    def test_answer_is_rate_limited(self):
        with mock.patch.object(semantic_search, "search", return_value=outcome_for([self.msg("w-mom3")])), \
                mock.patch.object(ask, "answer_question") as answer:
            response = self.client.get(URL, {"q": "grandma", "ask": "on"})
        self.assertEqual(response.status_code, 429)
        answer.assert_not_called()

    # ------------------------------------------------------------------ the rail link

    def test_rail_link_on_work_pages(self):
        response = self.client.get(reverse("app-work-brief"))
        self.assertContains(response, f'href="{URL}?world=work"')

    def test_rail_link_on_personal_pages(self):
        response = self.client.get(reverse("app-personal-catchup"))
        self.assertContains(response, f'href="{URL}?world=personal"')

    def test_rail_link_is_active_on_the_search_page(self):
        response = self.client.get(URL, {"world": "work"})
        self.assertContains(response, f'rail-link is-active" href="{URL}?world=work"')


class WarmupTests(TestCase):
    """F-7: the search index is built in the background when a user signs in."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("warm", password="pw-123456!")

    def setUp(self):
        semantic_search._index.clear()

    def test_off_under_the_test_runner_by_default(self):
        self.assertFalse(warmup.enabled())
        with mock.patch.object(warmup.threading, "Thread") as thread:
            self.client.login(username="warm", password="pw-123456!")
        thread.assert_not_called()

    @override_settings(AI_WARM_ON_LOGIN=True)
    def test_sign_in_starts_a_daemon_thread_for_that_user(self):
        with mock.patch.object(warmup.threading, "Thread") as thread:
            self.assertTrue(self.client.login(username="warm", password="pw-123456!"))
        thread.assert_called_once()
        kwargs = thread.call_args.kwargs
        self.assertIs(kwargs["target"], warmup.warm_user)
        self.assertEqual(kwargs["args"], (self.user.pk,))
        self.assertTrue(kwargs["daemon"])
        thread.return_value.start.assert_called_once()

    @override_settings(AI_WARM_ON_LOGIN=True)
    def test_skipped_when_already_warm(self):
        with mock.patch.object(warmup, "is_warm", return_value=True), \
                mock.patch.object(warmup.threading, "Thread") as thread:
            self.client.login(username="warm", password="pw-123456!")
        thread.assert_not_called()

    @override_settings(AI_WARM_ON_LOGIN=True, AI_SEARCH_ENABLED=False)
    def test_skipped_when_search_is_off(self):
        with mock.patch.object(warmup.threading, "Thread") as thread:
            self.client.login(username="warm", password="pw-123456!")
        thread.assert_not_called()

    @override_settings(AI_WARM_ON_LOGIN=True)
    def test_a_failure_never_breaks_sign_in(self):
        with mock.patch.object(warmup.threading, "Thread", side_effect=RuntimeError("no threads")), \
                self.assertLogs("unopsis.ai.warmup", level="ERROR") as logs:
            self.assertTrue(self.client.login(username="warm", password="pw-123456!"))
        self.assertIn("Could not start the search warm-up", logs.output[0])

    def test_warm_user_builds_the_index_and_closes_its_connection(self):
        with mock.patch.object(semantic_search, "build_index",
                               return_value={"ids": [1, 2], "ms": 7}) as build, \
                mock.patch("django.db.connection.close") as close:
            warmup.warm_user(self.user.pk)
        build.assert_called_once()
        self.assertEqual(build.call_args.args[0], self.user)
        close.assert_called_once()

    def test_warm_user_swallows_model_errors(self):
        with mock.patch.object(semantic_search, "build_index",
                               side_effect=semantic_search.SearchUnavailable("not installed")), \
                mock.patch("django.db.connection.close"):
            warmup.warm_user(self.user.pk)          # no exception

    def test_is_warm_needs_model_and_index(self):
        self.assertFalse(warmup.is_warm(self.user))
        key = (self.user.pk, semantic_search.model_name(), True)
        semantic_search._index[key] = {}
        with mock.patch.object(semantic_search, "is_loaded", return_value=True):
            self.assertTrue(warmup.is_warm(self.user))
