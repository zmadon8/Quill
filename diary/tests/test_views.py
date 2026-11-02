import re
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
        join_main(user)
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

        return dict(re.findall(r'<span class="name">([^<]+)</span><span class="count">([^<]+)</span>',
                               resp.content.decode()))

    def test_item_counts_per_subject_at_any_depth(self):
        self.client.force_login(self.reader)
        counts = self.counts(self.client.get(reverse("subjects")))
        self.assertEqual(counts["Arbitration"], "5")
        self.assertEqual(counts["Contracts"], "1")
        self.assertEqual(counts["Empty Subject"], "0")

    def test_other_subjects_listed_inline_with_counts_below_a_divider(self):
        self.client.force_login(self.reader)
        resp = self.client.get(reverse("subjects"))
        html = resp.content.decode()
        counts = self.counts(resp)
        self.assertEqual(counts["Other One"], "0")
        self.assertEqual(counts["Other Two"], "0")
        self.assertNotIn("Gone", counts)
        self.assertNotIn("Other Subjects", counts)  # no longer a link entry
        self.assertContains(resp, '<h2 id="other-subjects" class="other-title">Other Subjects</h2>')
        self.assertLess(html.index("Empty Subject"), html.index('<hr class="other-divider">'))
        self.assertLess(html.index('<hr class="other-divider">'), html.index("Other One"))
        self.assertLess(html.index("Other One"), html.index("Other Two"))
        self.assertNotContains(resp, 'href="%s"' % reverse("other_subjects"))

    def test_other_subjects_url_redirects_to_the_section(self):
        self.client.force_login(self.reader)
        resp = self.client.get(reverse("other_subjects"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("subjects") + "#other-subjects")
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("other_subjects") + "?edit=1")
        self.assertEqual(resp["Location"], reverse("subjects") + "?edit=1#other-subjects")

    def test_meta_line_totals(self):
        self.client.force_login(self.reader)
        resp = self.client.get(reverse("subjects"))
        self.assertContains(resp, "5 subjects &middot; 6 items &middot; ")
        self.assertContains(resp, '>1 for review</a>')

    def test_counts_use_a_fixed_number_of_queries(self):
        self.client.force_login(self.reader)
        self.client.get(reverse("subjects"))
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("subjects"))
        # session, user, landing Subjects, one item aggregate, Other Subjects, live Subject ids
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
        nav = resp.content.decode().split('class="program-nav"')[1].split("</nav>")[0]
        self.assertNotIn('href="%s"' % reverse("user_list"), nav)
        self.assertNotIn('href="%s"' % reverse("backup_list"), nav)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, 'href="%s"' % reverse("user_list"))
        self.assertContains(resp, 'href="%s"' % reverse("backup_list"))

    def test_nav_marks_current_page(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("user_list"))
        self.assertContains(resp, 'class="on" aria-current="page">Users</a>')
        self.assertNotContains(resp, 'class="on" aria-current="page">Subjects</a>')

    def test_login_page_is_plain(self):
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Case Law Diary")
        self.assertContains(resp, "Log in")

    def test_username_shown_on_suite_pages_but_not_inside_the_program(self):
        self.client.force_login(self.reader)
        home = self.client.get(reverse("home"))
        self.assertContains(home, 'class="who"')
        for name in ("subjects", "search"):
            self.assertNotContains(self.client.get(reverse(name)), 'class="who"', msg_prefix=name)

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

    def test_caselaw_urls_and_old_urls_redirect(self):
        self.client.force_login(self.reader)
        self.assertEqual(reverse("subjects"), "/caselaw/subjects/")
        self.assertEqual(reverse("search"), "/caselaw/search/")
        self.assertEqual(reverse("subject_contents", args=[7]), "/caselaw/subjects/7/")
        self.assertEqual(reverse("read_subject", args=[7]), "/caselaw/subjects/7/read/")
        self.assertEqual(reverse("read_topic", args=[7]), "/caselaw/topics/7/read/")
        self.assertEqual(reverse("read_subtopic", args=[7]), "/caselaw/subtopics/7/read/")
        for name in ("other_subjects", "review_list", "import_word", "profile_settings"):
            self.assertTrue(reverse(name).startswith("/caselaw/"), name)
        for root in ("/", "/healthz/", "/users/", "/settings/", "/backups/", "/profiles/", "/login/", "/logout/"):
            self.assertFalse(root.startswith("/caselaw/"))
        self.assertEqual(reverse("backup_list"), "/backups/")
        self.assertEqual(reverse("healthz"), "/healthz/")
        moved = {
            "/subjects/": "/caselaw/subjects/",
            "/subjects/7/": "/caselaw/subjects/7/",
            "/subjects/7/read/": "/caselaw/subjects/7/read/",
            "/topics/7/read/": "/caselaw/topics/7/read/",
            "/subtopics/7/read/": "/caselaw/subtopics/7/read/",
            "/other-subjects/": "/caselaw/other-subjects/",
            "/search/": "/caselaw/search/",
            "/review/": "/caselaw/review/",
            "/import/": "/caselaw/import/",
            "/profile-settings/": "/caselaw/profile-settings/",
        }
        for old, new in moved.items():
            resp = self.client.get(old)
            self.assertEqual(resp.status_code, 301, old)
            self.assertEqual(resp["Location"], new, old)
        resp = self.client.get("/search/?q=abc")
        self.assertEqual(resp["Location"], "/caselaw/search/?q=abc")

    def test_nav_lacks_a_subjects_link_and_brand_links_to_subjects(self):
        self.client.force_login(self.reader)
        html = self.client.get(reverse("search")).content.decode()
        nav = html.split('class="program-nav"')[1].split("</nav>")[0]
        self.assertNotIn(">Subjects</a>", nav)
        self.assertNotIn('href="%s"' % reverse("subjects"), nav)
        self.assertIn(reverse("search"), nav)
        header = html.split('<header class="site-header"')[1].split("</header>")[0]
        self.assertIn('<a href="%s" title="Subjects"' % reverse("subjects"), header)
        self.assertIn("Log out", nav)

    def test_home_icon_button_precedes_program_name_in_programs_and_suite_pages(self):
        self.client.force_login(self.reader)
        header = self.client.get(reverse("subjects")).content.decode().split('<header class="site-header"')[1].split("</header>")[0]
        self.assertIn('class="home-button" href="%s?home=1"' % reverse("home"), header)
        self.assertIn('aria-label="Home (Alt+H)"', header)
        self.assertLess(header.index("home-button"), header.index('class="brand"'))
        self.assertLess(header.index('class="brand"'), header.index("data-back"))
        self.assertLess(header.index("data-back"), header.index("data-forward"))
        self.client.force_login(self.admin)
        for name in ("home", "user_list", "settings"):
            suite_header = self.client.get(reverse(name)).content.decode().split('<header class="site-header"')[1].split("</header>")[0]
            self.assertIn('class="home-button" href="%s?home=1"' % reverse("home"), suite_header, name)
            self.assertLess(suite_header.index("home-button"), suite_header.index('class="brand"'), name)

    def _choose_landing(self, user, key="diary"):
        User.objects.filter(pk=user.pk).update(landing_program=key)

    def test_entry_visit_to_home_redirects_to_chosen_landing_program(self):
        self._choose_landing(self.reader)
        self.client.force_login(self.reader)
        resp = self.client.get(reverse("home"))
        self.assertRedirects(resp, reverse("subjects"), fetch_redirect_response=False)
        resp = self.client.get(reverse("home"), HTTP_REFERER="https://elsewhere.example/page")
        self.assertRedirects(resp, reverse("subjects"), fetch_redirect_response=False)

    def test_entry_visit_shows_home_without_landing_program(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_entry_visit_shows_home_when_the_landing_profile_is_gone(self):
        from accounts.models import ProfileMembership

        self._choose_landing(self.reader)
        ProfileMembership.objects.filter(user=self.reader).delete()
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_deliberate_home_visits_are_not_redirected(self):
        self._choose_landing(self.reader)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("home") + "?home=1").status_code, 200)
        resp = self.client.get(reverse("home"), HTTP_REFERER="http://testserver" + reverse("subjects"))
        self.assertEqual(resp.status_code, 200)
        html = self.client.get(reverse("subjects")).content.decode()
        self.assertIn('class="home-button" href="%s?home=1"' % reverse("home"), html)
        self.assertIn('data-home="%s?home=1"' % reverse("home"), html)

    def test_home_picker_is_one_link_with_only_the_program_name(self):
        self.client.force_login(self.reader)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, '<a class="program-link" href="%s">Case Law Diary</a>' % reverse("subjects"))
        self.assertNotContains(resp, ">Open<")
        self.assertNotContains(resp, "Case law, by Subject")

    def test_subjects_index_nav_has_no_other_subjects_or_users(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("subjects"))
        nav = resp.content.decode().split('class="program-nav"')[1].split("</nav>")[0]
        self.assertNotIn(reverse("other_subjects"), nav)
        self.assertNotIn(reverse("user_list"), nav)
        self.assertNotIn(reverse("backup_list"), nav)
        self.assertContains(resp, 'id="other-subjects"')  # on the same page

    def test_picker_top_row_is_users_name_logout_only(self):
        self.client.force_login(self.admin)
        nav = self.client.get(reverse("home")).content.decode().split('class="program-nav"')[1].split("</nav>")[0]
        self.assertIn(reverse("user_list"), nav)
        self.assertIn("adam", nav)
        self.assertIn("Log out", nav)
        self.assertIn(reverse("backup_list"), nav)
        for gone in (reverse("search"), reverse("subjects")):
            self.assertNotIn(gone, nav)
        self.assertNotIn("Admin", nav)
        self.client.force_login(self.reader)
        nav = self.client.get(reverse("home")).content.decode().split('class="program-nav"')[1].split("</nav>")[0]
        self.assertNotIn(reverse("user_list"), nav)

    def test_back_in_top_row_and_program_name_links_home(self):
        self.client.force_login(self.admin)
        for name in ("home", "subjects", "search", "user_list", "backup_list", "settings"):
            html = self.client.get(reverse(name)).content.decode()
            header = html.split('<header class="site-header"')[1].split("</header>")[0]
            self.assertIn("data-back", header, name)
            if name in ("home", "user_list", "backup_list", "settings"):
                self.assertIn('<a href="%s?home=1" title="Go to Home (Alt+H)" aria-label="Go to Home">' % reverse("home"), header, name)
            else:
                self.assertIn('<a href="%s" title="Subjects"' % reverse("subjects"), header, name)
            self.assertNotIn("switch-program", html, name)
            self.assertNotIn('class="toolbar', html, name)
            if name in ("home", "user_list", "backup_list", "settings"):
                self.assertEqual(header.count(">Home</a>"), 1, name)  # brand only, no extra Home button
            else:
                self.assertNotIn(">Home</a>", header, name)
                self.assertIn(">Case Law Diary</a>", header, name)  # brand; the Home icon has no text

    def test_back_and_forward_sit_right_of_the_program_name(self):
        self.client.force_login(self.admin)
        for name in ("home", "subjects", "user_list"):
            header = self.client.get(reverse(name)).content.decode().split('<header class="site-header"')[1].split("</header>")[0]
            brand = header.index('class="brand"')
            back = header.index("data-back")
            forward = header.index("data-forward")
            self.assertLess(brand, back, name)
            self.assertLess(back, forward, name)
            self.assertLess(forward, header.index('class="program-nav"'), name)
            self.assertIn('aria-label="Back"', header)
            self.assertIn('aria-label="Forward"', header)
            self.assertNotIn("Back</button>", header)
            self.assertNotIn("Forward</button>", header)
            for attr in ("data-back", "data-forward"):
                start = header.rindex("<button", 0, header.index(attr))
                button = header[start : header.index("</button>", start) + len("</button>")]
                self.assertEqual(button.count("<svg"), 1, name)
                inner = button.split(">", 1)[1].rsplit("</button>", 1)[0]
                self.assertEqual(re.sub(r"<svg.*?</svg>", "", inner, flags=re.S).strip(), "", name)
            self.assertEqual(header.count("<svg") - 2, 1, name)  # the Home icon is on every page, Home included
            self.assertIn('data-fallback="%s"' % reverse("home"), header)

    def test_review_in_diary_nav_for_anyone_with_a_profile(self):
        for user in (self.reader, self.admin):
            self.client.force_login(user)
            nav = self.client.get(reverse("subjects")).content.decode().split('class="program-nav"')[1].split("</nav>")[0]
            self.assertIn('href="%s"' % reverse("review_list"), nav)
            self.assertIn(">Review</a>", nav)
        nav = self.client.get(reverse("review_list")).content.decode().split('class="program-nav"')[1].split("</nav>")[0]
        self.assertIn('class="on" aria-current="page">Review</a>', nav)
        nav = self.client.get(reverse("home")).content.decode().split('class="program-nav"')[1].split("</nav>")[0]
        self.assertNotIn(reverse("review_list"), nav)

    def test_site_js_keeps_back_and_forward_inside_the_site(self):
        from pathlib import Path

        js = (Path(__file__).resolve().parents[2] / "static" / "js" / "site.js").read_text()
        self.assertNotIn("history.back", js)
        self.assertNotIn("history.go", js)
        self.assertIn("sessionStorage", js)
        self.assertIn("isSitePath", js)

    def test_search_button_cannot_break_over_two_lines(self):
        from pathlib import Path

        css = (Path(__file__).resolve().parents[2] / "static" / "css" / "site.css").read_text()
        self.assertIn("button, .button { white-space: nowrap;", css)
        self.assertIn(".home-search button { min-height: 52px; min-width: 6rem;", css)

    def test_users_screen_uses_suite_header_without_toolbar(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("user_list")).content.decode()
        self.assertNotIn('class="toolbar"', html)
        self.assertNotIn('class="breadcrumb"', html)
        self.assertNotIn(reverse("search"), html.split('class="program-nav"')[1].split("</nav>")[0])

    def test_breadcrumb_only_on_judgment_lists(self):
        self.client.force_login(self.admin)
        for name in ("home", "subjects", "search", "user_list", "backup_list"):
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

    def setUp(self):
        # The last-used view defaults to the whole Subject; most tests read single Topics, so start there.
        self.client.cookies["quill_in_context"] = "0"

    def urls(self):
        return [
            reverse("subjects"),
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
            self.client.cookies["quill_in_context"] = "0"  # logout() below clears the jar
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
        self.assertContains(resp, "Sample Act")  # an Other Subject, listed under the Other Subjects heading
        self.assertContains(resp, 'id="other-subjects"')
        html = resp.content.decode()
        self.assertLess(html.index("Contract Law"), html.index('id="other-subjects"'))
        self.assertLess(html.index('id="other-subjects"'), html.index("Sample Act"))

    def test_crumb_for_an_other_subject_links_to_the_section(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("read_subject", args=[self.other.pk]))
        self.assertContains(resp, '<a href="%s#other-subjects">Other Subjects</a>' % reverse("subjects"))

    def test_breadcrumb_shown_on_judgment_lists_with_subjects_root(self):
        self.client.force_login(self.users["reader"])
        for url in (reverse("subject_contents", args=[self.contract.pk]), reverse("read_subject", args=[self.contract.pk]),
                    reverse("read_subtopic", args=[self.clause.pk])):
            resp = self.client.get(url)
            self.assertContains(resp, 'class="breadcrumb"')
            self.assertContains(resp, '<a href="%s"' % reverse("subjects"))
            self.assertContains(resp, ">Subjects</a>")

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
        self.assertContains(resp, "Choose a Topic or Sub-topic from the list, or click the Subject name to read the whole Subject.")
        self.assertNotContains(resp, "data-contents-toggle")
        self.assertContains(resp, "data-toc-expand-all")
        self.assertContains(resp, "data-toc-collapse-all")
        self.assertContains(resp, 'aria-expanded="true"')

    def test_breadcrumb_subjects_link_switches_panel_and_there_is_no_all_checkbox(self):
        self.client.force_login(self.users["reader"])
        for url in (reverse("subject_contents", args=[self.contract.pk]), reverse("read_subject", args=[self.contract.pk])):
            html = self.client.get(url).content.decode()
            crumb = html.split('class="crumb-row"')[1].split("</div>")[0]
            self.assertIn('href="%s" data-panel-switch aria-controls="panel-subjects" aria-expanded="false"' % reverse("subjects"), crumb, url)
            self.assertNotIn("data-in-context", html, url)
            self.assertNotIn("> All</label>", html, url)
            self.assertNotIn("View in context", html, url)
            self.assertIn('data-header-toggle hidden aria-expanded="false" aria-controls="site-header"', crumb, url)
            self.assertIn('aria-label="Show header"', crumb, url)
            self.assertIn('title="Show header"', crumb, url)
            self.assertLess(crumb.index("data-header-toggle"), crumb.index("<nav"), url)
            self.assertIn('id="site-header"', html, url)
            panel = html.split('id="contents-panel"')[1].split("</aside>")[0]
            self.assertNotIn("data-in-context", panel, url)
            self.assertNotIn("panel-heading", html, url)
            self.assertIn('id="panel-subjects"', panel, url)
            self.assertIn("data-toc-expand-all", panel, url)

    def test_panel_lists_every_subject(self):
        self.client.force_login(self.users["reader"])
        for url in (reverse("subject_contents", args=[self.contract.pk]), reverse("read_subject", args=[self.contract.pk]),
                    reverse("read_topic", args=[Topic.objects.get(name="Remedies").pk])):
            html = self.client.get(url).content.decode()
            self.assertIn("data-panel-switch", html, url)
            self.assertNotIn("<h2>Contents</h2>", html, url)
            panel = html.split("data-panel-subjects")[1]
            for subject in (self.contract, self.longs, self.other):
                self.assertIn('href="%s"' % reverse("subject_contents", args=[subject.pk]), panel, url)
            self.assertIn("Other Subjects", panel)
            self.assertIn('class="current" aria-current="true">%s' % self.contract.name, panel)
            self.assertIn("&lsaquo; Topics", panel)
            self.assertLess(panel.index(self.contract.name), panel.index("Other Subjects"))
            self.assertIn("data-toc-resizer", html)
            self.assertIn('role="separator"', html)
            self.assertIn("data-toc-reset", html)

    def test_phone_contents_icon_button_sits_in_the_header_row_of_pages_with_a_panel(self):
        self.client.force_login(self.users["reader"])
        topic = Topic.objects.get(name="Remedies")
        for url in (reverse("read_subject", args=[self.contract.pk]), reverse("read_topic", args=[topic.pk])):
            html = self.client.get(url).content.decode()
            crumb = html.split('class="crumb-row"')[1].split("</div>")[0]
            self.assertEqual(html.count("data-contents-toggle"), 1, url)
            self.assertIn("data-contents-toggle", crumb, url)
            self.assertIn('aria-controls="contents-panel" aria-expanded="false" aria-label="Contents"', crumb, url)
            button = crumb.split("<button")[2]  # the first button is Show header
            self.assertEqual(button.count("<circle"), 3, url)  # three dots
            self.assertEqual(button.count("<path"), 1, url)  # and three lines
            self.assertIn("M10 6h11M10 12h11M10 18h11", button, url)
            self.assertNotIn('aria-expanded="false">Subjects</button>', html, url)
            self.assertIn('data-panel-switch', crumb, url)  # the breadcrumb Subjects link stays
            self.assertIn("M4 6h16M4 12h16M4 18h16", crumb, url)  # and so does the plain three-line Show header icon
            self.assertIn('id="contents-panel"', html, url)

    def test_pages_without_the_slide_over_panel_have_no_contents_button(self):
        self.client.force_login(self.users["reader"])
        for url in (reverse("subjects"), reverse("search"), reverse("subject_contents", args=[self.contract.pk])):
            html = self.client.get(url).content.decode()
            self.assertNotIn("data-contents-toggle", html, url)
            self.assertNotIn('title="Contents"', html, url)

    def test_panel_and_reading_labels_both_have_a_full_stop(self):
        import re

        self.client.force_login(self.users["reader"])
        html = self.client.get(reverse("read_subject", args=[self.contract.pk])).content.decode()
        toc = html.split('class="toc-box"')[1].split("</aside>")[0]
        labels = re.findall(r'<span class="num">([^<]*)</span>', toc)
        self.assertTrue(labels)
        self.assertTrue(all(lab.endswith(".") for lab in labels), labels)
        self.assertIn('<span class="num">A.</span> ', toc)
        reading_part = html.split("</aside>")[1]
        self.assertIn('<span class="num">A.</span> ', reading_part)

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
        self.assertContains(resp, 'data-toc-node="%d" data-toc-current' % topic.pk)
        resp = self.client.get(reverse("read_subtopic", args=[self.offer.pk]))
        self.assertContains(resp, 'data-toc-node="%d" data-toc-current' % self.offer.topic_id)
        resp = self.client.get(reverse("read_subject", args=[self.contract.pk]))
        self.assertNotContains(resp, "data-toc-current")

    def test_direct_topic_and_subtopic_pages_never_redirect(self):
        self.client.force_login(self.users["reader"])
        topic = Topic.objects.get(name="Remedies")
        for cookie in ("1", "0"):
            self.client.cookies["quill_in_context"] = cookie
            self.assertEqual(self.client.get(reverse("read_topic", args=[topic.pk])).status_code, 200)
            self.assertEqual(self.client.get(reverse("read_subtopic", args=[self.clause.pk])).status_code, 200)
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_mode="always_on")
        self.assertEqual(self.client.get(reverse("read_topic", args=[topic.pk])).status_code, 200)

    def test_heading_links_in_whole_subject_view_open_only_that_topic_or_subtopic(self):
        self.client.force_login(self.users["reader"])
        topic = Topic.objects.get(name="Remedies")
        resp = self.client.get(reverse("read_subject", args=[self.contract.pk]))
        html = resp.content.decode()
        self.assertIn('data-reading-view="all"', html)
        self.assertRegex(html, r'<h2 id="n-topic-%d" class="topic-heading"><a class="heading-link" data-heading-toggle href="%s" title="Show only this Topic">' % (topic.pk, reverse("read_topic", args=[topic.pk])))
        self.assertRegex(html, r'<h3 id="n-subtopic-%d" class="subtopic-heading"><a class="heading-link" data-heading-toggle href="%s" title="Show only this Sub-topic">' % (self.clause.pk, reverse("read_subtopic", args=[self.clause.pk])))

    def test_heading_links_in_single_scope_view_open_the_whole_subject_at_the_heading(self):
        self.client.force_login(self.users["reader"])
        topic = Topic.objects.get(name="Remedies")
        whole = reverse("read_subject", args=[self.contract.pk])
        html = self.client.get(reverse("read_topic", args=[topic.pk])).content.decode()
        self.assertIn('data-reading-view="scope"', html)
        self.assertIn('<a class="heading-link" data-heading-toggle href="%s#n-topic-%d" title="Show the whole Subject, at this Topic">' % (whole, topic.pk), html)
        html = self.client.get(reverse("read_subtopic", args=[self.clause.pk])).content.decode()
        self.assertIn('<a class="heading-link" data-heading-toggle href="%s#n-subtopic-%d" title="Show the whole Subject, at this Sub-topic">' % (whole, self.clause.pk), html)

    def test_heading_links_keep_edit_mode(self):
        self.client.force_login(self.users["editor"])
        topic = Topic.objects.get(name="Remedies")
        whole = reverse("read_subject", args=[self.contract.pk])
        html = self.client.get(reverse("read_topic", args=[topic.pk]) + "?edit=1").content.decode()
        self.assertIn('href="%s?edit=1#n-topic-%d"' % (whole, topic.pk), html)
        html = self.client.get(whole + "?edit=1").content.decode()
        self.assertIn('href="%s?edit=1" title="Show only this Topic"' % reverse("read_topic", args=[topic.pk]), html)

    def test_no_cookie_follows_profile_default_for_contents_links(self):
        self.client.force_login(self.users["reader"])
        topic = Topic.objects.get(name="Remedies")
        whole = reverse("read_subject", args=[self.contract.pk])
        del self.client.cookies["quill_in_context"]
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_default=False)
        resp = self.client.get(reverse("subject_contents", args=[self.contract.pk]))
        self.assertContains(resp, 'data-own-url="%s"' % reverse("read_topic", args=[topic.pk]))
        self.assertNotContains(resp, 'href="%s#n-topic-' % whole)
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_default=True)
        resp = self.client.get(reverse("subject_contents", args=[self.contract.pk]))
        self.assertContains(resp, 'href="%s#n-topic-%d"' % (whole, topic.pk))

    def test_remembered_view_cookie_beats_profile_default_for_contents_links_on_the_contents_page(self):
        self.client.force_login(self.users["reader"])
        topic = Topic.objects.get(name="Remedies")
        whole = reverse("read_subject", args=[self.contract.pk])
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_default=False)
        self.client.cookies["quill_in_context"] = "1"
        self.assertContains(self.client.get(reverse("subject_contents", args=[self.contract.pk])), 'href="%s#n-topic-%d"' % (whole, topic.pk))
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_default=True)
        self.client.cookies["quill_in_context"] = "0"
        self.assertNotContains(self.client.get(reverse("subject_contents", args=[self.contract.pk])), 'href="%s#n-topic-%d"' % (whole, topic.pk))

    def test_remember_mode_contents_links_follow_the_page_shown_not_the_cookie(self):
        self.client.force_login(self.users["reader"])
        topic = Topic.objects.get(name="Remedies")
        whole = reverse("read_subject", args=[self.contract.pk])
        toc_whole = '<a href="%s#n-topic-%d" data-own-url' % (whole, topic.pk)
        self.client.cookies["quill_in_context"] = "1"  # last view was the whole Subject, but this page is a single Topic
        self.assertNotContains(self.client.get(reverse("read_topic", args=[topic.pk])), toc_whole)
        self.client.cookies["quill_in_context"] = "0"
        self.assertContains(self.client.get(reverse("read_subject", args=[self.contract.pk])), toc_whole)

    def test_always_modes_ignore_cookie_for_contents_links(self):
        self.client.force_login(self.users["reader"])
        topic = Topic.objects.get(name="Remedies")
        whole = reverse("read_subject", args=[self.contract.pk])
        toc_whole = '<a href="%s#n-topic-%d" data-own-url' % (whole, topic.pk)
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_mode="always_on", reading_all_default=False)
        self.client.cookies["quill_in_context"] = "0"
        self.assertContains(self.client.get(reverse("read_topic", args=[topic.pk])), toc_whole)
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_mode="always_off", reading_all_default=True)
        self.client.cookies["quill_in_context"] = "1"
        self.assertNotContains(self.client.get(reverse("read_topic", args=[topic.pk])), toc_whole)
        self.assertContains(self.client.get(reverse("read_topic", args=[topic.pk])), '<a href="%s" data-own-url' % reverse("read_topic", args=[topic.pk]))

    def test_login_page_has_no_diary_name(self):
        from django.test import Client

        resp = Client().get(reverse("login"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Case Law Diary")

    def test_username_hidden_inside_program_but_shown_on_suite_pages(self):
        self.client.force_login(self.users["reader"])
        self.assertNotContains(self.client.get(reverse("read_subject", args=[self.contract.pk])), 'class="who"')
        self.assertContains(self.client.get(reverse("home")), "reader")

    def test_cross_reference_links_point_into_the_whole_subject_page(self):
        item = Item.objects.filter(subtopic=self.offer, deleted_at=None).first()
        note = Note.objects.filter(deleted_at=None).first()
        link = NoteLink.objects.create(profile=main_profile(), note=note, item=item)
        _, url = reading.note_target(link)
        subject_id = self.offer.subject_id or self.offer.topic.subject_id
        self.assertEqual(url, "%s#n-item-%d" % (reverse("read_subject", args=[subject_id]), item.pk))

    def test_contents_page_in_context_links_go_to_whole_subject(self):
        self.client.force_login(self.users["reader"])
        del self.client.cookies["quill_in_context"]
        resp = self.client.get(reverse("subject_contents", args=[self.contract.pk]))
        self.assertNotContains(resp, "data-in-context")
        self.assertContains(resp, 'href="%s#n-topic-' % reverse("read_subject", args=[self.contract.pk]))

    def test_icon_buttons_are_labelled_and_other_subjects_group_is_marked(self):
        self.client.force_login(self.users["reader"])
        resp = self.client.get(reverse("subject_contents", args=[self.contract.pk]))
        self.assertContains(resp, 'title="Expand all" aria-label="Expand all"')
        self.assertContains(resp, 'title="Collapse all" aria-label="Collapse all"')
        self.assertContains(resp, 'class="panel-label panel-label--other">Other Subjects')

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
        # Several citations are labelled (a), (b); a single citation shows without a label.
        self.assertContains(
            resp, '<span class="num">(a)</span> <em class="citation">Carlill v. Carbolic Smoke Ball Co [1893] 1 QB 256</em>',
            html=False)
        self.assertNotContains(resp, '<span class="num">(a)</span> <em class="citation">Harvey', html=False)
        self.assertContains(resp, '<span class="case-comment">', html=False)

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


class DottedFilterTests(TestCase):
    def test_dotted(self):
        from diary.templatetags.diary_tags import dotted

        self.assertEqual(dotted("A"), "A.")
        self.assertEqual(dotted("12"), "12.")
        self.assertEqual(dotted("iv"), "iv.")
        self.assertEqual(dotted("(a)"), "(a)")
        self.assertEqual(dotted(""), "")


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
        self.assertIn(("subtopic", "1", "Acceptance"), headings)  # alphabetical: before Offer
        self.assertIn(("subtopic", "2", "Offer"), headings)
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


class ReadingCitationTests(TestCase):
    """An Item's citations are its Cases: one shows plain, several are labelled by the Multi-Item format."""

    @classmethod
    def setUpTestData(cls):
        load_sample_data(main_profile())

    def block(self, text, user=None):
        subject = Subject.objects.get(name=SAMPLE_PREFIX + "Contract Law")
        ctx = reading.build_reading(subject, user)
        return next(b for b in ctx["blocks"] if b["kind"] == "item" and text in b["text"])

    def test_one_citation_has_no_label_and_is_not_multi(self):
        block = self.block("invitation to treat")
        self.assertEqual([(c["label"], c["citation"]) for c in block["cases"]], [("", "Harvey v. Facey [1893] AC 552")])
        self.assertFalse(block["is_multi"])
        self.assertEqual(block["citation"], "")

    def test_several_citations_are_labelled_and_keep_their_comments(self):
        block = self.block("general offer")
        self.assertTrue(block["is_multi"])
        self.assertEqual([c["label"] for c in block["cases"]], ["(a)", "(b)", "(c)"])
        self.assertEqual([c["has_comment"] for c in block["cases"]], [True, False, True])

    def test_an_item_without_a_citation_has_no_cases(self):
        item = Item.objects.get(text__contains="placed directly under the Subject")
        item.cases.all().delete()  # the sample gives this Item one citation; take it away
        block = self.block("placed directly under the Subject")
        self.assertEqual(block["cases"], [])

    def test_the_label_follows_the_users_multi_item_citation_format(self):
        user = get_user_model().objects.create_user("fmt", password="x-long-pass-123")
        from diary.models import UserSettings

        UserSettings.objects.create(user=user, multi_citation_format="paren_decimal")
        block = self.block("general offer", user)
        self.assertEqual([c["label"] for c in block["cases"]], ["(1)", "(2)", "(3)"])

    def test_a_nested_item_still_shows_its_own_citation(self):
        subject = Subject.objects.get(name=SAMPLE_PREFIX + "Contract Law")
        nested = next(b for b in reading.build_reading(subject, None)["blocks"] if b["kind"] == "item" and b["is_nested"])
        self.assertEqual(nested["citation"], "Sample v. Nested (2010) 1 SCC 1")
        self.assertEqual(nested["cases"], [])


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
        real_item = Item.objects.create(profile=main_profile(), topic=real_topic, text="<p>Mine</p>")
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

    def setUp(self):
        self.client.cookies["quill_in_context"] = "0"  # last-used view: single pages

    def test_index_lists_only_own_profile(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("subjects"))
        self.assertContains(resp, "Alpha Subject")
        self.assertNotContains(resp, "Beta Subject")
        self.assertEqual(resp.context["subject_total"], 1)
        self.assertEqual(resp.context["item_total"], 1)
        self.assertEqual(resp.context["other_subjects"], [])

    def test_other_profile_sees_its_own_counts(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("subjects"))
        self.assertContains(resp, "Beta Subject")
        self.assertNotContains(resp, "Alpha Subject")
        self.assertEqual(resp.context["item_total"], 2)
        self.assertEqual([s.name for s in resp.context["other_subjects"]], ["Beta Other"])

    def test_other_subjects_scoped(self):
        self.client.force_login(self.user_a)
        self.assertNotContains(self.client.get(reverse("subjects")), "Beta Other")
        self.client.force_login(self.user_b)
        self.assertContains(self.client.get(reverse("subjects")), "Beta Other")

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
