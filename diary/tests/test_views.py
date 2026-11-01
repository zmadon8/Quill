from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from diary import reading
from diary.models import Item, Note, NoteLink, Section, Subject, Subtopic, Topic
from diary.sample_data import SAMPLE_PREFIX, load_sample_data, remove_sample_data
from accounts.models import Profile
from diary.tests.helpers import join_main, main_profile


@override_settings(SECURE_SSL_REDIRECT=False)
class DiaryTests(TestCase):
    def test_home_requires_login(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("login")))

    def test_home_shows_title_and_username(self):
        user = get_user_model().objects.create_user("alice", password="x-long-pass-123")
        self.client.force_login(user)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "Case Law Diary")
        self.assertContains(resp, "alice")

    def test_healthz_without_login(self):
        resp = self.client.get("/healthz/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"ok")


PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False)
class HomeIndexTests(TestCase):
    """Option A index: per-Subject item counts, Other Subjects count, and role-based nav."""

    @classmethod
    def setUpTestData(cls):
        from django.utils import timezone

        cls.reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        cls.admin = join_main(User.objects.create_user("adam", password=PASSWORD, is_superuser=True), "editor")
        cls.arb = Subject.objects.create(profile=main_profile(), name="Arbitration", landing_position=1)
        cls.con = Subject.objects.create(profile=main_profile(), name="Contracts", landing_position=2)
        cls.empty = Subject.objects.create(profile=main_profile(), name="Empty Subject", landing_position=3)
        Subject.objects.create(profile=main_profile(), name="Other One", show_on_landing=False, other_acts_position=1)
        Subject.objects.create(profile=main_profile(), name="Other Two", show_on_landing=False, other_acts_position=2)
        Subject.objects.create(profile=main_profile(), name="Gone", show_on_landing=False, deleted_at=timezone.now())
        topic = Topic.objects.create(profile=main_profile(), subject=cls.arb, name="Fraud")
        sub = Subtopic.objects.create(profile=main_profile(), topic=topic, name="Ex parte")
        Item.objects.create(profile=main_profile(), subject=cls.arb, text="<p>direct</p>")
        Item.objects.create(profile=main_profile(), topic=topic, text="<p>in topic</p>", needs_review=True)
        Item.objects.create(profile=main_profile(), subtopic=sub, text="<p>in subtopic</p>")
        nested = Item.objects.create(profile=main_profile(), subtopic=sub, text="<p>nested</p>", kind="nested")
        Item.objects.create(profile=main_profile(), parent_item=nested, text="<p>child</p>")
        Item.objects.create(profile=main_profile(), subject=cls.arb, text="<p>deleted</p>", deleted_at=timezone.now())
        direct_sub = Subtopic.objects.create(profile=main_profile(), subject=cls.con, name="Direct")
        Item.objects.create(profile=main_profile(), subtopic=direct_sub, text="<p>c1</p>")

    def counts(self, resp):
        import re

        return dict(re.findall(r'<span class="name">(?:<em>)?([^<]+)(?:</em>)?</span><span class="count">([^<]+)</span>',
                               resp.content.decode()))

    def test_item_counts_per_subject_at_any_depth(self):
        self.client.force_login(self.reader)
        counts = self.counts(self.client.get(reverse("subjects")))
        self.assertEqual(counts["Arbitration"], "5")
        self.assertEqual(counts["Contracts"], "1")
        self.assertEqual(counts["Empty Subject"], "0")

    def test_other_subjects_entry_counts_live_other_subjects(self):
        self.client.force_login(self.reader)
        resp = self.client.get(reverse("subjects"))
        self.assertEqual(self.counts(resp)["Other Subjects"], "2 subjects")
        self.assertNotContains(resp, "Other One")

    def test_meta_line_totals(self):
        self.client.force_login(self.reader)
        resp = self.client.get(reverse("subjects"))
        self.assertContains(resp, "5 subjects &middot; 6 items &middot; 1 for review")

    def test_counts_use_a_fixed_number_of_queries(self):
        self.client.force_login(self.reader)
        self.client.get(reverse("subjects"))
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("subjects"))
        # session, user, landing Subjects, one item aggregate, Other count, live Subject ids
        self.assertLessEqual(len(ctx), 8)

    def test_search_box_leads_to_search_page(self):
        self.client.force_login(self.reader)
        resp = self.client.get(reverse("subjects"))
        self.assertContains(resp, 'action="%s"' % reverse("search"))
        self.assertContains(resp, "Search the diary")

    def test_nav_hides_admin_items_from_reader(self):
        self.client.force_login(self.reader)
        resp = self.client.get(reverse("subjects"))
        self.assertContains(resp, reverse("search"))
        self.assertNotContains(resp, 'href="%s"' % reverse("user_list"))
        self.assertNotContains(resp, 'href="%s"' % reverse("backup_list"))

    def test_nav_shows_admin_items_to_admin(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("subjects"))
        self.assertNotContains(resp, 'href="%s"' % reverse("user_list"))
        self.assertContains(resp, 'href="%s"' % reverse("backup_list"))
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, 'href="%s"' % reverse("user_list"))

    def test_nav_marks_current_page(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("user_list"))
        self.assertContains(resp, 'class="on" aria-current="page">Users</a>')
        self.assertNotContains(resp, 'class="on" aria-current="page">Subjects</a>')

    def test_home_is_program_picker(self):
        self.client.force_login(self.reader)
        resp = self.client.get(reverse("home"))
        self.assertEqual(reverse("home"), "/")
        self.assertContains(resp, "Case Law Diary")
        self.assertContains(resp, 'href="%s"' % reverse("subjects"))
        self.assertNotContains(resp, "Switch program")

    def test_legacy_programs_url_redirects_home(self):
        self.client.force_login(self.reader)
        self.assertRedirects(self.client.get("/programs/"), reverse("home"))

    def test_subjects_index_nav_has_no_other_subjects_or_users(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("subjects"))
        nav = resp.content.decode().split('class="program-nav"')[1].split("</nav>")[0]
        self.assertNotIn(reverse("other_subjects"), nav)
        self.assertNotIn(reverse("user_list"), nav)
        self.assertIn(reverse("backup_list"), nav)
        self.assertContains(resp, 'href="%s"' % reverse("other_subjects"))  # still reachable from the index

    def test_picker_top_row_is_users_name_logout_only(self):
        self.client.force_login(self.admin)
        nav = self.client.get(reverse("home")).content.decode().split('class="program-nav"')[1].split("</nav>")[0]
        self.assertIn(reverse("user_list"), nav)
        self.assertIn("adam", nav)
        self.assertIn("Log out", nav)
        for gone in (reverse("search"), reverse("subjects"), reverse("backup_list")):
            self.assertNotIn(gone, nav)
        self.assertNotIn("Admin", nav)
        self.client.force_login(self.reader)
        nav = self.client.get(reverse("home")).content.decode().split('class="program-nav"')[1].split("</nav>")[0]
        self.assertNotIn(reverse("user_list"), nav)

    def test_back_in_top_row_and_program_name_links_home(self):
        self.client.force_login(self.admin)
        for name in ("home", "subjects", "search", "user_list", "backup_list", "settings"):
            html = self.client.get(reverse(name)).content.decode()
            header = html.split('<header class="site-header">')[1].split("</header>")[0]
            self.assertIn("data-back", header, name)
            self.assertIn('<a href="%s" title="Go to Home (Alt+H)" aria-label="Go to Home">' % reverse("home"), header, name)
            self.assertNotIn("switch-program", html, name)
            self.assertNotIn('class="toolbar', html, name)
            if name in ("home", "user_list", "settings"):
                self.assertEqual(header.count(">Home</a>"), 1, name)  # brand only, no extra Home button
            else:
                self.assertNotIn(">Home</a>", header, name)
                self.assertIn(">Case Law Diary</a>", header, name)

    def test_users_screen_uses_suite_header_without_toolbar(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("user_list")).content.decode()
        self.assertNotIn('class="toolbar"', html)
        self.assertNotIn('class="breadcrumb"', html)
        self.assertNotIn(reverse("search"), html.split('class="program-nav"')[1].split("</nav>")[0])

    def test_breadcrumb_only_on_judgment_lists(self):
        self.client.force_login(self.admin)
        for name in ("home", "subjects", "other_subjects", "search", "user_list", "backup_list"):
            self.assertNotContains(self.client.get(reverse(name)), 'class="breadcrumb"', msg_prefix=name)


@override_settings(SECURE_SSL_REDIRECT=False)
class ReadingScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        load_sample_data(main_profile())
        cls.users = {
            role: join_main(
                User.objects.create_user(role, password=PASSWORD, is_superuser=(role == "admin")),
                "reader" if role == "reader" else "editor",
            )
            for role in ("reader", "editor", "admin")
        }
        cls.contract = Subject.objects.get(name=SAMPLE_PREFIX + "Contract Law")
        cls.longs = Subject.objects.get(name=SAMPLE_PREFIX + "Long Lists")
        cls.other = Subject.objects.get(name=SAMPLE_PREFIX + "Other Subject (Sample Act)")
        cls.clause = Subtopic.objects.get(name="Clause 12: Leave to Sue")
        cls.offer = Subtopic.objects.get(name="Offer")

    def urls(self):
        return [
            reverse("subjects"),
            reverse("other_subjects"),
            reverse("search"),
            reverse("subject_contents", args=[self.contract.pk]),
            reverse("read_subject", args=[self.contract.pk]),
            reverse("read_topic", args=[Topic.objects.get(name="Remedies").pk]),
            reverse("read_subtopic", args=[self.clause.pk]),
            reverse("read_subject", args=[self.other.pk]),
        ]

    def test_every_role_can_read_every_screen(self):
        for role, user in self.users.items():
            self.client.force_login(user)
            for url in self.urls():
                self.assertEqual(self.client.get(url).status_code, 200, f"{role} {url}")
            self.client.logout()

    def test_anonymous_is_sent_to_login(self):
        for url in self.urls():
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertTrue(resp["Location"].startswith(reverse("login")), url)

    def test_unknown_and_deleted_records_are_404(self):
        self.client.force_login(self.users["reader"])
        self.assertEqual(self.client.get(reverse("read_subject", args=[999999])).status_code, 404)
        from django.utils import timezone

        Subject.objects.filter(pk=self.longs.pk).update(deleted_at=timezone.now())
        self.assertEqual(self.client.get(reverse("read_subject", args=[self.longs.pk])).status_code, 404)
        topic = Topic.objects.filter(subject=self.longs).first()
        self.assertEqual(self.client.get(reverse("read_topic", args=[topic.pk])).status_code, 404)

    def test_landing_respects_show_on_landing(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("subjects"))
        self.assertContains(resp, "Contract Law")
        self.assertContains(resp, "Other Subjects")
        self.assertNotContains(resp, "Sample Act")
        resp = self.client.get(reverse("other_subjects"))
        self.assertContains(resp, "Sample Act")
        self.assertNotContains(resp, "Contract Law")

    def test_breadcrumb_shown_on_judgment_lists_with_subjects_root(self):
        self.client.force_login(self.users["reader"])
        for url in (reverse("subject_contents", args=[self.contract.pk]), reverse("read_subject", args=[self.contract.pk]),
                    reverse("read_subtopic", args=[self.clause.pk])):
            resp = self.client.get(url)
            self.assertContains(resp, 'class="breadcrumb"')
            self.assertContains(resp, '<a href="%s">Subjects</a>' % reverse("subjects"))

    def test_subject_links_open_whole_subject_view(self):
        self.client.force_login(self.users["reader"])
        whole = reverse("read_subject", args=[self.contract.pk])
        for url in (reverse("subject_contents", args=[self.contract.pk]), reverse("read_topic", args=[self.clause.topic_id]),
                    reverse("read_subtopic", args=[self.clause.pk])):
            html = self.client.get(url).content.decode()
            self.assertIn('<p class="toc-subject"><a href="%s"' % whole, html, url)
            self.assertIn('<a href="%s">%s</a>' % (whole, self.contract.name), html.split('class="breadcrumb"')[1], url)
        html = self.client.get(reverse("read_topic", args=[self.clause.topic_id])).content.decode()
        self.assertIn(reverse("read_subtopic", args=[self.clause.pk]), html.split('class="toc-box"')[1])

    def test_contents_lists_topics_and_subtopics(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("subject_contents", args=[self.contract.pk]))
        self.assertNotContains(resp, "View whole Subject")
        self.assertContains(resp, "Formation")
        self.assertContains(resp, "Acceptance")

    def test_contents_page_uses_side_panel_layout(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("subject_contents", args=[self.contract.pk]))
        self.assertContains(resp, 'class="reader-layout reader-layout--page"')
        self.assertContains(resp, 'id="contents-panel"')
        self.assertContains(resp, "Choose a Topic or Sub-topic from Contents, or click the Subject name to read the whole Subject.")
        self.assertNotContains(resp, "data-contents-toggle")
        self.assertContains(resp, 'data-toc-default="all"')
        self.assertContains(resp, "data-toc-expand-all")
        self.assertContains(resp, "data-toc-collapse-all")
        self.assertContains(resp, 'aria-expanded="true"')

    def test_contents_page_empty_subject_message(self):
        empty = Subject.objects.create(profile=main_profile(), name="Empty Subject", show_on_landing=True)
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("subject_contents", args=[empty.pk]))
        self.assertContains(resp, "This Subject has no Topics or Sub-topics.")
        self.assertNotContains(resp, 'id="contents-panel"')

    def test_reader_toc_marks_current_topic_and_defaults_to_current(self):
        self.client.force_login(self.users["reader"])
        topic = Topic.objects.get(name="Remedies")
        resp = self.client.get(reverse("read_topic", args=[topic.pk]))
        self.assertContains(resp, 'data-toc-default="current"')
        self.assertContains(resp, 'data-toc-node="%d" data-toc-current' % topic.pk)
        resp = self.client.get(reverse("read_subtopic", args=[self.offer.pk]))
        self.assertContains(resp, 'data-toc-node="%d" data-toc-current' % self.offer.topic_id)
        resp = self.client.get(reverse("read_subject", args=[self.contract.pk]))
        self.assertNotContains(resp, "data-toc-current")

    def test_other_subject_toc_has_nothing_to_expand(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("subject_contents", args=[self.other.pk]))
        self.assertNotContains(resp, "data-toc-toggle")
        self.assertNotContains(resp, "data-toc-expand-all")

    def test_other_subject_lists_subtopics_directly(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("subject_contents", args=[self.other.pk]))
        self.assertContains(resp, "Sample provision 1")
        self.assertContains(resp, "Sample provision 3")

    def test_reading_view_shows_expected_features(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("read_subject", args=[self.contract.pk]))
        self.assertContains(resp, '<em class="citation">Harvey v. Facey [1893] AC 552</em>', html=False)
        self.assertContains(resp, "flagged")
        self.assertContains(resp, "Overruled by New v. Law (1990)")
        self.assertContains(resp, "For review: Check the citation against the report.")
        self.assertContains(resp, "See also: ")
        self.assertContains(resp, "Carlill v. Carbolic Smoke Ball Co")
        self.assertContains(resp, " ; ")

    def test_topic_and_subtopic_views_show_correct_buttons_and_numbers(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("read_subtopic", args=[self.clause.pk]))
        for gone in ("View whole Subject", "View this Topic", "View this Sub-topic"):
            self.assertNotContains(resp, gone)
        self.assertContains(resp, "Clause 12: Leave to Sue")
        # Remedies is the second Topic and Clause 12 the first Sub-topic, even when read alone.
        self.assertContains(resp, '<span class="num">(b)</span> Leave to sue: procedure')
        self.assertContains(resp, '<span class="num">(8)</span>')
        self.assertNotContains(resp, '<span class="num">(viii)</span>')

    def test_user_formats_are_used(self):
        from diary.models import UserSettings

        UserSettings.objects.create(user=self.users["editor"], section_format="section_n", item_format="decimal")
        self.client.force_login(self.users["editor"])
        resp = self.client.get(reverse("read_subtopic", args=[self.clause.pk]))
        self.assertContains(resp, "Section 1")
        self.assertContains(resp, "Section 2")


class ReadingNumberingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        load_sample_data(main_profile())

    def labels(self, subtopic):
        """Labels of the Items and Sections shown directly in one Sub-topic, in order."""
        subject = subtopic.topic.subject if subtopic.topic_id else subtopic.subject
        ctx = reading.build_reading(subject, None, "subtopic", subtopic)
        return [b["label"] for b in ctx["blocks"] if b["kind"] in ("item", "section")]

    def test_clause_12_example(self):
        clause = Subtopic.objects.get(name="Clause 12: Leave to Sue")
        self.assertEqual(
            self.labels(clause),
            ["(1)", "(2)", "(a)", "(1)", "(2)", "(b)"] + ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)", "(8)"],
        )

    def test_long_lists_continue_correctly(self):
        many = Subtopic.objects.get(name__startswith="Forty-five")
        labels = self.labels(many)
        self.assertEqual(len(labels), 45)
        self.assertIn("(39)", labels)
        self.assertEqual(labels[39], "(40)")
        self.assertEqual(labels[-1], "(45)")
        plenty = Subtopic.objects.get(name__startswith="Thirty Sections")
        sections = self.labels(plenty)
        self.assertEqual(sections[25], "(z)")
        self.assertEqual(sections[26], "(aa)")
        self.assertEqual(sections[-1], "(ad)")

    def test_topics_and_subtopics_and_nested_bullets(self):
        contract = Subject.objects.get(name=SAMPLE_PREFIX + "Contract Law")
        ctx = reading.build_reading(contract, None)
        headings = [(b["level"], b["label"], b["name"]) for b in ctx["blocks"] if b["kind"] == "heading"]
        self.assertIn(("topic", "A", "Formation"), headings)
        self.assertIn(("topic", "B", "Remedies"), headings)
        self.assertIn(("subtopic", "2", "Acceptance"), headings)
        nested = [b for b in ctx["blocks"] if b["kind"] == "item" and b["is_nested"]][0]
        self.assertEqual([c["label"] for c in nested["children"]], ["\u2022", "\u2022"])
        self.assertEqual(nested["label"], "(4)")

    def test_deleted_records_are_not_shown_and_do_not_use_numbers(self):
        from django.utils import timezone

        offer = Subtopic.objects.get(name="Offer")
        Item.objects.filter(subtopic=offer, position=1).update(deleted_at=timezone.now())
        labels = self.labels(offer)
        self.assertEqual(labels[0], "(1)")
        self.assertEqual(len(labels), 5)

    def test_note_link_to_deleted_target_has_no_url(self):
        from django.utils import timezone

        acceptance = Subtopic.objects.get(name="Acceptance")
        Subtopic.objects.filter(pk=acceptance.pk).update(deleted_at=timezone.now())
        link = NoteLink.objects.get(subtopic=acceptance)
        path, url = reading.note_target(NoteLink.objects.select_related("subtopic").get(pk=link.pk))
        self.assertIsNone(url)
        self.assertIn("(deleted)", path)


class SampleDataTests(TestCase):
    def test_load_is_idempotent(self):
        self.assertTrue(load_sample_data(main_profile()))
        count = Item.objects.count()
        self.assertFalse(load_sample_data(main_profile()))
        self.assertEqual(Item.objects.count(), count)
        self.assertEqual(Subject.objects.filter(name__startswith=SAMPLE_PREFIX).count(), 3)

    def test_remove_deletes_only_sample_records(self):
        real = Subject.objects.create(profile=main_profile(), name="Real Subject")
        real_topic = Topic.objects.create(profile=main_profile(), subject=real, name="Real Topic")
        real_item = Item.objects.create(profile=main_profile(), topic=real_topic, text="<p>Mine</p>", citation="X")
        real_section = Section.objects.create(profile=main_profile(), topic=real_topic, name="S")
        real_note = Note.objects.create(profile=main_profile(), topic=real_topic, text="<p>n</p>")
        load_sample_data(main_profile())
        self.assertEqual(remove_sample_data(main_profile()), 3)
        self.assertEqual(list(Subject.objects.values_list("name", flat=True)), ["Real Subject"])
        self.assertTrue(Item.objects.filter(pk=real_item.pk).exists())
        self.assertTrue(Section.objects.filter(pk=real_section.pk).exists())
        self.assertTrue(Note.objects.filter(pk=real_note.pk).exists())
        self.assertEqual(Item.objects.count(), 1)
        self.assertEqual(NoteLink.objects.count(), 0)
        self.assertEqual(remove_sample_data(main_profile()), 0)

    def test_commands_run(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("load_sample_data", stdout=out)
        call_command("load_sample_data", stdout=out)
        self.assertIn("already loaded", out.getvalue())
        call_command("remove_sample_data", stdout=out)
        self.assertEqual(Subject.objects.count(), 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class ProfileScopingTests(TestCase):
    """Profiles are separate data spaces: nothing from profile B is visible to a user in profile A."""

    @classmethod
    def setUpTestData(cls):
        cls.a = main_profile()
        cls.b = Profile.objects.create(program="diary", name="Junior")
        cls.user_a = join_main(User.objects.create_user("ann", password=PASSWORD), "editor")
        cls.admin_a = join_main(User.objects.create_user("adm", password=PASSWORD, is_superuser=True), "editor")
        cls.user_b = User.objects.create_user("bea", password=PASSWORD)
        from accounts.profiles import set_user_profile

        set_user_profile(cls.user_b, cls.b)
        cls.loner = User.objects.create_user("lou", password=PASSWORD)
        cls.sub_a = Subject.objects.create(profile=cls.a, name="Alpha Subject", landing_position=1)
        cls.top_a = Topic.objects.create(profile=cls.a, subject=cls.sub_a, name="Alpha Topic")
        cls.st_a = Subtopic.objects.create(profile=cls.a, topic=cls.top_a, name="Alpha Subtopic")
        Item.objects.create(profile=cls.a, topic=cls.top_a, text="<p>a1</p>")
        cls.sub_b = Subject.objects.create(profile=cls.b, name="Beta Subject", landing_position=1)
        cls.oth_b = Subject.objects.create(profile=cls.b, name="Beta Other", show_on_landing=False, other_acts_position=1)
        cls.top_b = Topic.objects.create(profile=cls.b, subject=cls.sub_b, name="Beta Topic")
        cls.st_b = Subtopic.objects.create(profile=cls.b, topic=cls.top_b, name="Beta Subtopic")
        Item.objects.create(profile=cls.b, topic=cls.top_b, text="<p>b1</p>")
        Item.objects.create(profile=cls.b, topic=cls.top_b, text="<p>b2</p>")

    def test_index_lists_only_own_profile(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("subjects"))
        self.assertContains(resp, "Alpha Subject")
        self.assertNotContains(resp, "Beta Subject")
        self.assertEqual(resp.context["subject_total"], 1)
        self.assertEqual(resp.context["item_total"], 1)
        self.assertEqual(resp.context["other_count"], 0)

    def test_other_profile_sees_its_own_counts(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("subjects"))
        self.assertContains(resp, "Beta Subject")
        self.assertNotContains(resp, "Alpha Subject")
        self.assertEqual(resp.context["item_total"], 2)
        self.assertEqual(resp.context["other_count"], 1)

    def test_other_subjects_scoped(self):
        self.client.force_login(self.user_a)
        self.assertNotContains(self.client.get(reverse("other_subjects")), "Beta Other")
        self.client.force_login(self.user_b)
        self.assertContains(self.client.get(reverse("other_subjects")), "Beta Other")

    def test_cross_profile_ids_404(self):
        self.client.force_login(self.user_a)
        for url in (
            reverse("subject_contents", args=[self.sub_b.pk]),
            reverse("read_subject", args=[self.sub_b.pk]),
            reverse("read_subject", args=[self.oth_b.pk]),
            reverse("read_topic", args=[self.top_b.pk]),
            reverse("read_subtopic", args=[self.st_b.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        for url in (
            reverse("subject_contents", args=[self.sub_a.pk]),
            reverse("read_subject", args=[self.sub_a.pk]),
            reverse("read_topic", args=[self.top_a.pk]),
            reverse("read_subtopic", args=[self.st_a.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_admin_sees_only_own_profile(self):
        self.client.force_login(self.admin_a)
        self.assertNotContains(self.client.get(reverse("subjects")), "Beta Subject")
        self.assertEqual(self.client.get(reverse("read_subject", args=[self.sub_b.pk])).status_code, 404)

    def test_header_shows_profile_name(self):
        self.client.force_login(self.user_a)
        self.assertContains(self.client.get(reverse("subjects")), 'class="profile-name">&middot; Main</span>')
        self.client.force_login(self.user_b)
        self.assertContains(self.client.get(reverse("subjects")), "Junior")

    def test_user_without_profile_gets_403_with_message(self):
        self.client.force_login(self.loner)
        for name in ("subjects", "other_subjects", "search"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 403, name)
            self.assertContains(resp, "No profile assigned - ask the Admin", status_code=403)
        resp = self.client.get(reverse("read_subject", args=[self.sub_a.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_home_hides_program_without_profile(self):
        self.client.force_login(self.loner)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "No programs are available to you yet.")
        self.assertNotContains(resp, "No profile assigned")
        self.assertNotContains(resp, 'href="%s"' % reverse("subjects"))
        self.assertNotContains(resp, "Case Law Diary")
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("home"))
        self.assertNotContains(resp, "No programs are available")
        self.assertContains(resp, 'href="%s"' % reverse("subjects"))

    def test_home_hides_program_for_admin_without_profile(self):
        admin = User.objects.create_user("rootless", password=PASSWORD, is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "No programs are available to you yet.")
        self.assertNotContains(resp, 'href="%s"' % reverse("subjects"))
        self.assertContains(resp, 'href="%s"' % reverse("user_list"))
        self.assertEqual(self.client.get(reverse("subjects")).status_code, 403)

    def test_deleted_profile_means_no_access(self):
        from django.utils import timezone

        self.b.deleted_at = timezone.now()
        self.b.save()
        self.client.force_login(self.user_b)
        self.assertEqual(self.client.get(reverse("subjects")).status_code, 403)

    def test_opening_subject_must_belong_to_users_profile(self):
        from diary.models import UserSettings
        from diary.views import opening_subject_for

        settings = UserSettings.objects.create(user=self.user_a, opening_subject=self.sub_b)
        self.assertIsNone(opening_subject_for(self.user_a, self.a))
        settings.opening_subject = self.sub_a
        settings.save()
        self.user_a = User.objects.get(pk=self.user_a.pk)
        self.assertEqual(opening_subject_for(self.user_a, self.a), self.sub_a)
