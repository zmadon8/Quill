import time

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from diary.models import Case, Item, Note, Section, Subject, Subtopic, Topic
from diary.search import run_search
from diary.tests.helpers import join_main, main_profile


def para(text):
    return "<p>%s</p>" % text


class SearchTestBase(TestCase):
    def setUp(self):
        self.profile = main_profile()
        self.subject = Subject.objects.create(profile=self.profile, name="Zebra Subject", landing_position=1)
        self.topic = Topic.objects.create(profile=self.profile, subject=self.subject, name="Quokka Topic")
        self.subtopic = Subtopic.objects.create(profile=self.profile, topic=self.topic, name="Wombat Subtopic")

    def item(self, text, **fields):
        fields.setdefault("topic", self.topic)
        return Item.objects.create(profile=self.profile, text=para(text), **fields)

    def case(self, item, citation, comment=""):
        return Case.objects.create(profile=self.profile, item=item, citation=citation, comment=comment)

    def search(self, query, **kwargs):
        return run_search(self.profile, query, **kwargs)

    def kinds(self, query, **kwargs):
        return [(r.kind, r.label) for r in self.search(query, **kwargs)]

    def trash(self, obj):
        type(obj).objects.filter(pk=obj.pk).update(deleted_at=timezone.now())


class MatchEachRecordTypeTests(SearchTestBase):
    def test_subject_name(self):
        self.assertEqual(self.kinds("zebra"), [("Subject", "Zebra Subject")])

    def test_topic_name(self):
        self.assertEqual(self.kinds("quokka"), [("Topic", "Quokka Topic")])

    def test_subtopic_name(self):
        self.assertEqual(self.kinds("wombat"), [("Sub-topic", "Wombat Subtopic")])

    def test_section_name(self):
        Section.objects.create(profile=self.profile, topic=self.topic, name="Ibex Section")
        self.assertEqual(self.kinds("ibex"), [("Section", "Ibex Section")])

    def test_item_text(self):
        self.item("Lynx in the text")
        self.assertEqual(self.kinds("lynx"), [("Item", "Lynx in the text")])

    def test_case_citation_and_highlight(self):
        item = self.item("An item")
        self.case(item, "(2018) 9 SCC 49")
        results = self.search("2018 9 scc 49")
        self.assertEqual([(r.kind, r.label) for r in results], [("Item", "An item")])
        self.assertEqual(results[0].field_label, "Citation")
        highlighted = [text for text, on in results[0].segments if on]
        self.assertEqual(highlighted, ["2018) 9 SCC 49"])

    def test_case_comment(self):
        item = self.item("An item")
        self.case(item, "AIR 1990 SC 123", para("Narwhal comment"))
        results = self.search("narwhal")
        self.assertEqual([(r.kind, r.label) for r in results], [("Item", "An item")])
        self.assertEqual(results[0].field_label, "Comment")

    def test_second_citation_of_an_item_on_separate_lines(self):
        item = self.item("Group heading", citation_layout="lines")
        self.case(item, "First [2018 SCC 1]", para("Opening comment"))
        self.case(item, "Okapi [2019 SCC OnLine Bom 1234]")
        results = self.search("okapi 1234")
        self.assertEqual([(r.kind, r.label) for r in results], [("Item", "Group heading")])
        self.assertEqual(results[0].field_label, "Citation")
        self.assertTrue(results[0].url.endswith("#n-item-%d" % item.pk))
        self.assertEqual([r.label for r in self.search("opening comment")], ["Group heading"])

    def test_flag_text(self):
        self.item("Plain", flag="other", flag_text="Pangolin warning")
        results = self.search("pangolin")
        self.assertEqual([(r.kind, r.label) for r in results], [("Item", "Plain")])
        self.assertEqual(results[0].flag_text, "Pangolin warning")
        self.assertEqual(results[0].field_label, "Flag")

    def test_item_review_note(self):
        self.item("Plain", needs_review=True, review_note="Tapir check this")
        results = self.search("tapir")
        self.assertEqual([r.label for r in results], ["Plain"])
        self.assertTrue(results[0].needs_review)
        self.assertEqual(results[0].review_note, "Tapir check this")
        self.assertEqual(results[0].field_label, "Review note")

    def test_section_review_note(self):
        Section.objects.create(profile=self.profile, topic=self.topic, name="Sec", needs_review=True, review_note="Gecko note")
        self.assertEqual(self.kinds("gecko"), [("Section", "Sec")])

    def test_note_text_locates_at_parent_item(self):
        item = self.item("Parent item")
        note = Note.objects.create(profile=self.profile, item=item, text=para("Gnu remark"))
        results = self.search("gnu")
        self.assertEqual([(r.kind, r.label) for r in results], [("Note", "Gnu remark")])
        self.assertTrue(results[0].url.endswith("#n-note-%d" % note.pk))
        self.assertEqual(results[0].path[-1], ("Parent item", None))

    def test_note_on_section_and_headings(self):
        section = Section.objects.create(profile=self.profile, topic=self.topic, name="Sec")
        notes = {
            "Heron on section": Note.objects.create(profile=self.profile, section=section, text=para("Heron on section")),
            "Heron on topic": Note.objects.create(profile=self.profile, topic=self.topic, text=para("Heron on topic")),
            "Heron on subtopic": Note.objects.create(profile=self.profile, subtopic=self.subtopic, text=para("Heron on subtopic")),
            "Heron on subject": Note.objects.create(profile=self.profile, subject=self.subject, text=para("Heron on subject")),
        }
        urls = {r.label: r.url.split("#", 1)[1] for r in self.search("heron")}
        # Every Note hit opens the Note itself in context, whatever it sits on (D36).
        self.assertEqual(urls, {name: "n-note-%d" % note.pk for name, note in notes.items()})

    def test_item_with_a_citation_is_found_by_text_and_by_citation(self):
        child = self.item("Child badger")
        self.case(child, "AIR 1991 SC 5")
        results = self.search("badger")
        self.assertEqual([r.label for r in results], ["Child badger"])
        self.assertTrue(results[0].url.endswith("#n-item-%d" % child.pk))
        self.assertEqual([r.label for r in self.search("1991")], ["Child badger"])

    def test_item_matches_through_any_of_its_cases(self):
        item = self.item("Two cases")
        self.case(item, "(2010) 1 SCC 1")
        self.case(item, "(2011) 2 SCC 2")
        self.assertEqual(len(self.search("2011 2 scc 2")), 1)
        self.assertEqual(len(self.search("2010 2011")), 1)  # words may be in different fields

    def test_path_and_urls(self):
        item = self.item("Deep item", topic=None, subtopic=self.subtopic)
        result = self.search("deep")[0]
        self.assertEqual(result.path, [
            ("Zebra Subject", reverse("read_subject", args=[self.subject.pk])),
            ("Quokka Topic", reverse("read_topic", args=[self.topic.pk])),
            ("Wombat Subtopic", reverse("read_subtopic", args=[self.subtopic.pk])),
        ])
        self.assertEqual(result.url, reverse("read_subject", args=[self.subject.pk]) + "#n-item-%d" % item.pk)
        self.assertEqual(result.subject_id, self.subject.pk)

    def test_heading_results_link_to_heading_anchors(self):
        by_kind = {r.kind: r for r in self.search("subject") + self.search("quokka") + self.search("wombat")}
        base = reverse("read_subject", args=[self.subject.pk])
        self.assertEqual(by_kind["Subject"].url, base)
        self.assertEqual(by_kind["Topic"].url, base + "#n-topic-%d" % self.topic.pk)
        self.assertEqual(by_kind["Sub-topic"].url, base + "#n-subtopic-%d" % self.subtopic.pk)
        # a heading's own path does not repeat itself
        self.assertEqual([name for name, _ in by_kind["Sub-topic"].path], ["Zebra Subject", "Quokka Topic"])
        self.assertEqual(by_kind["Subject"].path, [])

    def test_phrase_and_partial_and_punctuation(self):
        self.item("The Arbitration Act")
        self.assertEqual(len(self.search("arbitr")), 1)
        self.assertEqual(len(self.search('"arbitr"')), 0)
        self.assertEqual(len(self.search('"arbitration act"')), 1)

    def test_empty_query_without_filters_lists_nothing(self):
        self.item("Anything")
        self.assertEqual(self.search(""), [])
        self.assertEqual(self.search("   ()  "), [])
        self.assertEqual(self.search("", subject_id=self.subject.pk), [])


class TrashTests(SearchTestBase):
    def test_deleted_records_are_excluded(self):
        item = self.item("Lynx deleted")
        self.trash(item)
        self.assertEqual(self.search("lynx"), [])

    def test_deleted_headings_are_excluded(self):
        self.trash(self.subtopic)
        self.assertEqual(self.search("wombat"), [])
        self.trash(self.topic)
        self.assertEqual(self.search("quokka"), [])

    def test_item_in_deleted_topic_is_excluded(self):
        self.item("Lynx in topic")
        self.item("Lynx in subtopic", topic=None, subtopic=self.subtopic)
        self.trash(self.topic)  # the Items themselves are not marked deleted
        self.assertEqual(self.search("lynx"), [])

    def test_item_in_item_in_deleted_subtopic_and_subject(self):
        self.item("Lynx in subtopic", topic=None, subtopic=self.subtopic)
        self.trash(self.subtopic)
        self.assertEqual(self.search("lynx"), [])
        self.subtopic.refresh_from_db()
        Subtopic.objects.filter(pk=self.subtopic.pk).update(deleted_at=None)
        self.assertEqual(len(self.search("lynx")), 1)
        self.trash(self.subject)
        self.assertEqual(self.search("lynx"), [])
        self.assertEqual(self.search("zebra"), [])

    def test_case_of_deleted_item_is_excluded(self):
        item = self.item("An item")
        self.case(item, "(2018) 9 SCC 49", para("Narwhal"))
        self.trash(item)
        self.assertEqual(self.search("2018 9 scc 49"), [])
        self.assertEqual(self.search("narwhal"), [])
        self.assertEqual(self.search("", citations_only=True), [])

    def test_deleted_case_is_not_searched_but_item_is(self):
        item = self.item("An item")
        case = self.case(item, "(2018) 9 SCC 49")
        self.trash(case)
        self.assertEqual(self.search("2018 9 scc 49"), [])
        self.assertEqual(len(self.search("item")), 1)

    def test_note_on_deleted_section_or_item_is_excluded(self):
        section = Section.objects.create(profile=self.profile, topic=self.topic, name="Sec")
        item = self.item("An item")
        Note.objects.create(profile=self.profile, section=section, text=para("Heron one"))
        Note.objects.create(profile=self.profile, item=item, text=para("Heron two"))
        self.assertEqual(len(self.search("heron")), 2)
        self.trash(section)
        self.assertEqual([r.label for r in self.search("heron")], ["Heron two"])
        self.trash(item)
        self.assertEqual(self.search("heron"), [])

    def test_deleted_note_is_excluded(self):
        note = Note.objects.create(profile=self.profile, topic=self.topic, text=para("Heron"))
        self.trash(note)
        self.assertEqual(self.search("heron"), [])

    def test_cases_of_a_deleted_item_are_excluded(self):
        item = self.item("Group")
        self.case(item, "Badger [2020] 1 SCC 1")
        self.assertEqual(len(self.search("badger")), 1)
        self.trash(item)
        self.assertEqual(self.search("badger"), [])

    def test_section_in_deleted_parent_is_excluded(self):
        Section.objects.create(profile=self.profile, topic=self.topic, name="Ibex Section")
        self.trash(self.topic)
        self.assertEqual(self.search("ibex"), [])


class ProfileScopeTests(SearchTestBase):
    def test_another_profile_never_appears(self):
        other = Profile.objects.create(program="diary", name="Junior")
        subject = Subject.objects.create(profile=other, name="Zebra Elsewhere")
        topic = Topic.objects.create(profile=other, subject=subject, name="Quokka Elsewhere")
        item = Item.objects.create(profile=other, topic=topic, text=para("Lynx elsewhere"))
        Case.objects.create(profile=other, item=item, citation="(2018) 9 SCC 49")
        Note.objects.create(profile=other, item=item, text=para("Gnu elsewhere"))
        Section.objects.create(profile=other, topic=topic, name="Ibex elsewhere", needs_review=True)
        self.item("Lynx here")
        for query in ("zebra", "quokka", "lynx", "2018 9 scc 49", "gnu", "ibex", "elsewhere"):
            labels = [r.label for r in self.search(query)]
            self.assertFalse([x for x in labels if "lsewhere" in x], (query, labels))
        self.assertEqual([r.label for r in self.search("lynx")], ["Lynx here"])
        self.assertEqual([r.label for r in run_search(other, "lynx")], ["Lynx elsewhere"])
        self.assertEqual([r.label for r in run_search(other, "", review_only=True)], ["Ibex elsewhere"])
        self.assertEqual(self.search("", review_only=True), [])
        self.assertEqual(self.search("zebra", subject_id=subject.pk), [])


class FilterTests(SearchTestBase):
    def setUp(self):
        super().setUp()
        self.other = Subject.objects.create(profile=self.profile, name="Common Other", show_on_landing=False)
        self.other_item = Item.objects.create(profile=self.profile, subject=self.other, text=para("Common scc text"))
        self.main_item = self.item("Common scc text too")

    def test_subject_filter(self):
        self.assertEqual(len(self.search("common")), 3)
        self.assertEqual([r.label for r in self.search("common", subject_id=self.subject.pk)], ["Common scc text too"])
        # an Other Subject can be chosen too
        self.assertEqual([r.label for r in self.search("common", subject_id=self.other.pk)],
                         ["Common Other", "Common scc text"])

    def test_citations_only(self):
        self.case(self.main_item, "(2018) 9 SCC 49")
        self.case(self.item("Group"), "Okapi (2019) 4 SCC 7")
        self.assertEqual([r.label for r in self.search("scc", citations_only=True)], ["Common scc text too", "Group"])
        # the text "scc" of the other Item and the headings are not citation fields
        self.assertEqual(self.search("common", citations_only=True), [])
        self.assertEqual([r.label for r in self.search("2019 4 scc 7", citations_only=True)], ["Group"])
        self.assertEqual({r.kind for r in self.search("scc", citations_only=True)}, {"Item"})

    def test_citations_only_without_query_lists_items_with_a_citation(self):
        self.case(self.main_item, "(2018) 9 SCC 49")
        self.assertEqual([r.label for r in self.search("", citations_only=True)], ["Common scc text too"])

    def test_review_only_covers_items_and_sections(self):
        Item.objects.filter(pk=self.main_item.pk).update(needs_review=True, review_note="check")
        Section.objects.create(profile=self.profile, topic=self.topic, name="Common Sec", needs_review=True)
        Section.objects.create(profile=self.profile, topic=self.topic, name="Common Plain Sec")
        results = self.search("common", review_only=True)
        self.assertEqual({(r.kind, r.label) for r in results}, {("Item", "Common scc text too"), ("Section", "Common Sec")})
        self.assertTrue(all(r.needs_review for r in results))

    def test_review_only_with_empty_query_lists_everything_marked(self):
        Item.objects.filter(pk=self.main_item.pk).update(needs_review=True)
        Item.objects.filter(pk=self.other_item.pk).update(needs_review=True)
        Section.objects.create(profile=self.profile, topic=self.topic, name="Sec", needs_review=True)
        Note.objects.create(profile=self.profile, topic=self.topic, text=para("Not marked"))
        results = self.search("", review_only=True)
        self.assertEqual(len(results), 3)
        self.assertEqual({r.kind for r in results}, {"Item", "Section"})
        self.assertEqual(len(self.search("", review_only=True, subject_id=self.other.pk)), 1)

    def test_review_only_includes_marked_items(self):
        self.item("Group")
        child = self.item("Child", needs_review=True)
        results = self.search("", review_only=True)
        self.assertEqual([r.label for r in results], ["Child"])
        self.assertTrue(results[0].url.endswith("#n-item-%d" % child.pk))

    def test_filters_combine(self):
        Item.objects.filter(pk=self.main_item.pk).update(needs_review=True)
        self.case(self.main_item, "(2018) 9 SCC 49")
        other_case_item = self.item("Not for review")
        self.case(other_case_item, "(2017) 1 SCC 1")
        results = self.search("scc", citations_only=True, review_only=True, subject_id=self.subject.pk)
        self.assertEqual([r.label for r in results], ["Common scc text too"])
        self.assertEqual(self.search("scc", citations_only=True, review_only=True, subject_id=self.other.pk), [])


class HeadersOnlyTests(SearchTestBase):
    def setUp(self):
        super().setUp()
        self.section = Section.objects.create(profile=self.profile, topic=self.topic, name="Pangolin Section")
        self.hit = self.item("Pangolin in the text")
        self.case(self.hit, "Pangolin v State (2020) 1 SCC 1", "Pangolin comment")

    def test_headers_only_finds_names_not_item_text(self):
        self.assertEqual(self.kinds("Pangolin", headers_only=True), [("Section", "Pangolin Section")])
        self.assertEqual(len(self.search("Pangolin")), 2)

    def test_headers_only_finds_subject_topic_subtopic(self):
        for word, kind in (("Zebra", "Subject"), ("Quokka", "Topic"), ("Wombat", "Sub-topic")):
            self.assertEqual([r.kind for r in self.search(word, headers_only=True)], [kind])

    def test_headers_only_skips_review_notes_notes_and_flags(self):
        Item.objects.filter(pk=self.hit.pk).update(review_note="Axolotl", flag_text="Axolotl")
        self.assertEqual(self.search("Axolotl", headers_only=True), [])

    def test_headers_only_excludes_trash_and_other_profiles(self):
        self.trash(self.section)
        self.assertEqual(self.search("Pangolin", headers_only=True), [])
        other = Profile.objects.create(name="Other", program="diary")
        subject = Subject.objects.create(profile=other, name="Pangolin Other", landing_position=1)
        self.assertEqual(run_search(other, "Pangolin", headers_only=True)[0].subject_id, subject.pk)
        self.assertEqual(self.search("Pangolin", headers_only=True), [])

    def test_headers_only_combines_with_subject_filter(self):
        other = Subject.objects.create(profile=self.profile, name="Pangolin Subject", landing_position=2)
        self.assertEqual(len(self.search("Pangolin", headers_only=True)), 2)
        self.assertEqual([r.label for r in self.search("Pangolin", headers_only=True, subject_id=other.pk)],
                         ["Pangolin Subject"])


class OrderTests(SearchTestBase):
    def test_diary_order(self):
        profile = self.profile
        a = Subject.objects.create(profile=profile, name="Marker Law", landing_position=2)
        other = Subject.objects.create(profile=profile, name="Marker Other", show_on_landing=False)
        topic = Topic.objects.create(profile=profile, subject=a, name="Marker Topic")
        sub = Subtopic.objects.create(profile=profile, topic=topic, name="Marker Sub")
        direct_sub = Subtopic.objects.create(profile=profile, subject=a, name="Marker Direct Sub")
        # created in a scrambled order on purpose
        Item.objects.create(profile=profile, subtopic=sub, text=para("marker in sub"))
        Item.objects.create(profile=profile, subject=other, text=para("marker in other"))
        Item.objects.create(profile=profile, topic=topic, text=para("marker in topic two"), position=2)
        Item.objects.create(profile=profile, topic=topic, text=para("marker in topic one"), position=1)
        Item.objects.create(profile=profile, subtopic=direct_sub, text=para("marker in direct sub"))
        Item.objects.create(profile=profile, subject=a, text=para("marker direct item"))
        self.assertEqual([r.label for r in run_search(profile, "marker")], [
            "Marker Law",
            "marker direct item",
            "Marker Direct Sub",
            "marker in direct sub",
            "Marker Topic",
            "marker in topic one",
            "marker in topic two",
            "Marker Sub",
            "marker in sub",
            "Marker Other",
            "marker in other",
        ])

    def test_section_before_item_at_same_position_and_notes_after_their_parent(self):
        profile = self.profile
        Item.objects.create(profile=profile, topic=self.topic, text=para("flock item"), position=1)
        Section.objects.create(profile=profile, topic=self.topic, name="flock section", position=1)
        item = Item.objects.create(profile=profile, topic=self.topic, text=para("flock second"), position=2)
        Note.objects.create(profile=profile, item=item, text=para("flock note"))
        Item.objects.create(profile=profile, topic=self.topic, text=para("flock third"), position=3)
        self.assertEqual([r.label for r in self.search("flock")],
                         ["flock section", "flock item", "flock second", "flock note", "flock third"])

    def test_whole_query_together_ranks_first(self):
        self.item("beta then alpha", position=1)
        self.item("alpha then beta", position=2)
        self.item("alpha beta together", position=3)
        self.item("only alpha", position=4)
        results = self.search("alpha beta")
        # only the third holds "alpha beta" together, so it is first although it comes last in the Diary
        self.assertEqual([r.label for r in results], ["alpha beta together", "beta then alpha", "alpha then beta"])
        self.assertEqual([r.score for r in results], [2, 1, 1])


@override_settings(SECURE_SSL_REDIRECT=False)
class ResultUrlTests(SearchTestBase):
    def test_every_result_url_resolves_to_an_element_id(self):
        user = join_main(get_user_model().objects.create_user("rita", password="x-long-pass-123"))
        self.client.force_login(user)
        section = Section.objects.create(profile=self.profile, topic=self.topic, name="Link marker section")
        item = self.item("Link marker item")
        self.case(item, "Link marker cite")
        lines = self.item("Link marker lines", citation_layout="lines")
        self.case(lines, "Link marker lines cite")
        note_on_item = Note.objects.create(profile=self.profile, item=item, text=para("Link marker note"))
        note_on_topic = Note.objects.create(profile=self.profile, topic=self.topic, text=para("Link marker topic note"))
        Topic.objects.filter(pk=self.topic.pk).update(name="Link marker topic")
        Subtopic.objects.filter(pk=self.subtopic.pk).update(name="Link marker subtopic")
        Subject.objects.filter(pk=self.subject.pk).update(name="Link marker subject")
        results = self.search("link marker")
        self.assertGreaterEqual(len(results), 8)
        seen = set()
        for result in results:
            path, _, anchor = result.url.partition("#")
            self.assertEqual(path, reverse("read_subject", args=[self.subject.pk]))
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200)
            if anchor:
                self.assertContains(resp, 'id="%s"' % anchor)
            seen.add(anchor)
        self.assertTrue({
            "n-section-%d" % section.pk, "n-item-%d" % item.pk, "n-item-%d" % lines.pk,
            "n-topic-%d" % self.topic.pk, "n-subtopic-%d" % self.subtopic.pk,
            "n-note-%d" % note_on_item.pk, "n-note-%d" % note_on_topic.pk,
        } <= seen)


class QueryCountTests(SearchTestBase):
    def fill(self, count):
        items = Item.objects.bulk_create([
            Item(profile=self.profile, topic=self.topic, text=para("count item %d" % i),
                 text_plain="count item %d" % i, position=i)
            for i in range(count)
        ])
        Case.objects.bulk_create([Case(profile=self.profile, item=it, citation="(2018) 9 SCC %d" % n)
                                  for n, it in enumerate(items)])
        Note.objects.bulk_create([Note(profile=self.profile, item=it, text=para("count note"), text_plain="count note")
                                  for it in items[:5]])

    def count_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            results = self.search("count scc")
        return len(ctx), len(results)

    def test_query_count_is_small_and_does_not_grow_with_records(self):
        self.fill(10)
        small_queries, small_results = self.count_queries()
        self.fill(90)
        large_queries, large_results = self.count_queries()
        self.assertEqual(small_results, 10)
        self.assertEqual(large_results, 100)
        self.assertEqual(small_queries, large_queries)
        self.assertLessEqual(large_queries, 8)


class SpeedTests(SearchTestBase):
    def test_five_thousand_items_under_a_second(self):
        # bulk_create skips save(), so the plain-text copies are set here
        items = Item.objects.bulk_create([
            Item(profile=self.profile, topic=self.topic, position=i,
                 text=para("Item number %d about arbitration and the court held that" % i),
                 text_plain="Item number %d about arbitration and the court held that" % i)
            for i in range(5000)
        ])
        Case.objects.bulk_create([
            Case(profile=self.profile, item=it, citation="(2018) 9 SCC %d" % n, comment=para("comment %d" % n),
                 comment_plain="comment %d" % n)
            for n, it in enumerate(items) if n % 2 == 0
        ])
        self.assertEqual(Item.objects.filter(profile=self.profile).count(), 5000)
        started = time.perf_counter()
        results = self.search("2018 9 scc 49")
        elapsed = time.perf_counter() - started
        print("\nrun_search over 5,000 Items (+2,500 Cases): %.3f s, %d results" % (elapsed, len(results)))
        self.assertGreater(len(results), 0)
        self.assertLess(elapsed, 1.0)
        started = time.perf_counter()
        everything = self.search("item arbitration")
        elapsed = time.perf_counter() - started
        print("run_search, 5,000 results: %.3f s" % elapsed)
        self.assertEqual(len(everything), 5000)
        self.assertLess(elapsed, 1.0)


@override_settings(SECURE_SSL_REDIRECT=False)
class SearchPageTests(SearchTestBase):
    def setUp(self):
        super().setUp()
        self.item("Pangolin one")
        self.other = Subject.objects.create(profile=self.profile, name="Yak Subject", landing_position=2)
        other_topic = Topic.objects.create(profile=self.profile, subject=self.other, name="Yak Topic")
        Item.objects.create(profile=self.profile, topic=other_topic, text=para("Pangolin two"))
        self.client.force_login(join_main(get_user_model().objects.create_user("rita", password="x-long-pass-123")))

    def test_no_review_list_link_inside_search(self):
        resp = self.client.get(reverse("search"))
        self.assertNotContains(resp, 'class="meta" href="%s' % reverse("review_list"))
        self.assertContains(resp, "For review only")
        self.assertContains(resp, "Search headers")

    def test_by_subject_view_lists_subjects_and_chosen_results(self):
        resp = self.client.get(reverse("search"), {"q": "Pangolin", "view": "subjects", "s": self.other.pk})
        self.assertContains(resp, 'class="search-subjects"')
        self.assertContains(resp, "Pangolin two")
        self.assertNotContains(resp, "Pangolin one")

    def test_by_subject_defaults_to_first_subject_and_is_not_used_with_a_filter(self):
        resp = self.client.get(reverse("search"), {"q": "Pangolin", "view": "subjects"})
        self.assertContains(resp, "Pangolin one")
        self.assertNotContains(resp, "Pangolin two")
        resp = self.client.get(reverse("search"), {"q": "Pangolin", "view": "subjects", "subject": self.other.pk})
        self.assertNotContains(resp, 'class="search-subjects"')

    def test_headers_param_is_passed_through(self):
        resp = self.client.get(reverse("search"), {"q": "Pangolin", "headers": "1"})
        self.assertContains(resp, "No results")
