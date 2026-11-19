"""The short-lived in-memory copy of what Search reads (diary/searchcache.py): reused while nothing changed, never stale."""
from unittest import mock

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from diary import searchcache
from diary import searchtext as st
from diary import services as svc
from diary.search import run_search
from diary.tests.service_helpers import ServiceTestCase

TABLES = len(searchcache._TABLES)


@override_settings(SEARCH_CACHE_SECONDS=600)
class SearchCacheTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        searchcache.clear()
        self.addCleanup(searchcache.clear)
        self.subject = self.make("subject", name="Zebra")
        self.topic = self.make("topic", ("subject", self.subject.pk), name="Quokka")
        self.item = self.make("item", ("topic", self.topic.pk), text="lynx here")

    def labels(self, query, profile=None, **kwargs):
        return [r.label for r in run_search(profile or self.profile, query, **kwargs)]

    def queries(self, query):
        with CaptureQueriesContext(connection) as ctx:
            self.labels(query)
        return len(ctx)

    def test_a_repeat_search_reads_only_the_fingerprint(self):
        self.assertEqual(self.labels("lynx"), ["lynx here"])
        self.assertEqual(self.queries("lynx"), TABLES)
        self.assertEqual(self.queries("here"), TABLES)  # a different query uses the same copy
        self.assertEqual(self.labels("here"), ["lynx here"])

    def test_an_edit_shows_at_once(self):
        self.labels("lynx")
        svc.edit(self.profile, self.user, "item", self.item.pk, {"text": "ibex here"})
        self.assertEqual(self.labels("lynx"), [])
        self.assertEqual(self.labels("ibex"), ["ibex here"])

    def test_a_new_record_and_a_trashed_record_show_at_once(self):
        self.labels("lynx")
        second = self.make("item", ("topic", self.topic.pk), text="lynx again")
        self.assertEqual(sorted(self.labels("lynx")), ["lynx again", "lynx here"])
        svc.delete(self.profile, self.user, "item", second.pk)
        self.assertEqual(self.labels("lynx"), ["lynx here"])

    def test_renaming_a_heading_shows_at_once(self):
        self.assertEqual(self.labels("zebra"), ["Zebra"])
        svc.edit(self.profile, self.user, "subject", self.subject.pk, {"name": "Gnu"})
        self.assertEqual(self.labels("zebra"), [])
        self.assertEqual(self.labels("gnu"), ["Gnu"])

    def test_a_hard_delete_and_a_change_behind_the_services_back_are_noticed(self):
        self.labels("lynx")
        type(self.item).objects.filter(pk=self.item.pk).update(deleted_at=self.item.created_at)  # no version bump
        self.assertEqual(self.labels("lynx"), [])
        other = self.make("item", ("topic", self.topic.pk), text="lynx two")
        self.assertEqual(self.labels("lynx"), ["lynx two"])
        type(other).objects.filter(pk=other.pk).delete()
        self.assertEqual(self.labels("lynx"), [])

    def test_another_profile_never_gets_this_profiles_copy(self):
        subject = self.make("subject", profile=self.other_profile, name="Other subject")
        topic = self.make("topic", ("subject", subject.pk), profile=self.other_profile, name="Other topic")
        self.make("item", ("topic", topic.pk), profile=self.other_profile, text="lynx elsewhere")
        self.assertEqual(self.labels("lynx"), ["lynx here"])
        self.assertEqual(self.labels("lynx", profile=self.other_profile), ["lynx elsewhere"])
        self.assertEqual(self.labels("lynx"), ["lynx here"])

    def test_a_copy_older_than_the_limit_is_built_again(self):
        with mock.patch("diary.searchcache.time") as clock:
            clock.monotonic.return_value = 1000.0
            self.labels("lynx")
            self.assertEqual(self.queries("lynx"), TABLES)
            clock.monotonic.return_value = 1000.0 + 601
            self.assertGreater(self.queries("lynx"), TABLES)

    @override_settings(SEARCH_CACHE_SECONDS=0)
    def test_switched_off_it_reads_everything_each_time(self):
        self.labels("lynx")
        self.assertEqual(self.labels("lynx"), ["lynx here"])
        with CaptureQueriesContext(connection) as first:
            self.labels("lynx")
        with CaptureQueriesContext(connection) as second:
            self.labels("lynx")
        self.assertEqual(len(first), len(second))
        self.assertGreater(len(first), TABLES - 1)
        self.assertEqual(len(searchcache._entries), 0)

    def test_only_a_few_copies_are_kept(self):
        with mock.patch.object(searchcache, "MAX_ENTRIES", 2):
            for kwargs in ({}, {"citations_only": True}, {"headers_only": True}, {"flags_only": True}):
                self.labels("lynx", **kwargs)
            self.assertLessEqual(len(searchcache._entries), 2)


class PreparedTextTests(ServiceTestCase):
    FIELDS = [("text", "Fraud in a Clause"), ("citation", "(2018) 9 SCC 49")]

    def test_matching_with_prepared_text_gives_the_same_answer(self):
        norms = [st.normalise(text) for _key, text in self.FIELDS]
        for query in ("fraud", "scc 49", "fraud OR nothing", "fraud -scc", "zzz"):
            parsed = st.parse_search(query)
            self.assertEqual(st.match_fields(self.FIELDS, parsed), st.match_fields(self.FIELDS, parsed, norms), query)
        terms = st.parse_query("2018 9 scc")
        self.assertEqual(st.contains_whole_query(self.FIELDS, terms), st.contains_whole_query(self.FIELDS, terms, norms))
        self.assertTrue(st.contains_whole_query(self.FIELDS, terms, norms))
