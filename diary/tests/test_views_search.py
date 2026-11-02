from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile, User
from diary.models import Case, Item, Note, Subject, Topic
from diary.tests.helpers import join_main, main_profile

PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False)
class SearchViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reader = join_main(User.objects.create_user("rita", password=PASSWORD))
        cls.editor = join_main(User.objects.create_user("edna", password=PASSWORD), "editor")
        cls.nobody = User.objects.create_user("nina", password=PASSWORD)
        cls.profile = main_profile()
        cls.subject = Subject.objects.create(profile=cls.profile, name="Contracts", landing_position=1)
        cls.topic = Topic.objects.create(profile=cls.profile, subject=cls.subject, name="Remedies")
        cls.item = Item.objects.create(profile=cls.profile, topic=cls.topic, text="<p>Specific performance granted</p>")
        cls.cited = Item.objects.create(profile=cls.profile, topic=cls.topic, text="<p>Damages</p>")
        Case.objects.create(profile=cls.profile, item=cls.cited, citation="(2018) 9 SCC 49", comment="")

    def get(self, **params):
        self.client.force_login(self.reader)
        return self.client.get(reverse("search"), params)

    def test_login_required(self):
        resp = self.client.get(reverse("search"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("login")))

    def test_reader_and_editor_can_search(self):
        for user in (self.reader, self.editor):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("search"), {"q": "damages"}).status_code, 200)

    def test_user_without_profile_gets_403(self):
        self.client.force_login(self.nobody)
        self.assertEqual(self.client.get(reverse("search")).status_code, 403)

    def test_empty_page_shows_help(self):
        resp = self.get()
        self.assertContains(resp, "search-help")
        self.assertNotContains(resp, "No results")

    def test_query_shows_count_and_highlight(self):
        resp = self.get(q="performance")
        self.assertContains(resp, "1 result<")
        self.assertContains(resp, "<mark>performance</mark>")

    def test_no_results_echoes_query(self):
        self.assertContains(self.get(q="zzzqqq"), "No results for")

    def test_html_in_text_is_escaped(self):
        Item.objects.create(profile=self.profile, topic=self.topic, text="<p>a &lt;script&gt;alert(1)&lt;/script&gt; b</p>")
        resp = self.get(q="alert")
        self.assertNotContains(resp, "<script>alert")
        self.assertContains(resp, "&lt;script&gt;")

    def test_query_is_escaped_in_the_box_and_message(self):
        resp = self.get(q='"><script>x</script>')
        self.assertNotContains(resp, "<script>x")

    def test_citation_search_end_to_end(self):
        resp = self.get(q="2018 9 SCC 49")
        self.assertContains(resp, "<mark>")
        self.assertContains(resp, "n-item-%d" % self.cited.pk)

    def test_filters_in_url(self):
        resp = self.get(q="", citations="1")
        self.assertContains(resp, "1 result<")
        self.assertContains(resp, "checked")
        Item.objects.filter(pk=self.item.pk).update(needs_review=True)
        resp = self.get(review="1")
        self.assertContains(resp, "1 result<")
        self.assertContains(resp, "For review")

    def test_subject_filter_and_foreign_subject_ignored(self):
        other = Profile.objects.create(program="diary", name="Second")
        foreign = Subject.objects.create(profile=other, name="Foreign", landing_position=1)
        resp = self.get(q="damages", subject=foreign.pk)
        self.assertContains(resp, "1 result<")
        self.assertNotContains(resp, "Foreign")
        resp = self.get(q="damages", subject=self.subject.pk)
        self.assertContains(resp, "1 result<")

    def test_unicode_digit_params_do_not_crash(self):
        for params in ({"subject": "\u00b2"}, {"limit": "\u00b2"}, {"q": "damages", "subject": "\u0663", "limit": "\uff11"}):
            self.assertEqual(self.get(**params).status_code, 200)
        self.assertEqual(self.get(q="damages", limit="\u00b2").status_code, 200)

    def test_review_list_unicode_subject_does_not_crash(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("review_list"), {"subject": "\u00b2"}).status_code, 200)

    def test_subject_level_note_link_target_exists(self):
        note = Note.objects.create(profile=self.profile, subject=self.subject, text="<p>Ostrich remark</p>")
        resp = self.get(q="ostrich")
        # A Note hit opens the Note itself (Milestone 5), so the link must land on the Note's own anchor.
        self.assertContains(resp, "#n-note-%d" % note.pk)
        page = self.client.get(reverse("read_subject", args=[self.subject.pk]))
        self.assertContains(page, 'id="n-note-%d"' % note.pk)
        self.assertContains(page, 'id="n-subject-%d"' % self.subject.pk)

    def test_show_more_link_keeps_params(self):
        for i in range(55):
            Item.objects.create(profile=self.profile, topic=self.topic, text="<p>bulk %d</p>" % i)
        resp = self.get(q="bulk", review="")
        self.assertContains(resp, "Show more")
        self.assertContains(resp, "limit=100")
        self.assertContains(resp, "q=bulk")
        self.assertNotContains(self.get(q="bulk", limit=100), "Show more")

    def test_header_box_on_reading_page_not_on_search_page(self):
        self.client.force_login(self.reader)
        reading_page = self.client.get(reverse("read_subject", args=[self.subject.pk]))
        self.assertContains(reading_page, 'class="nav-search"')
        self.assertNotContains(self.client.get(reverse("search")), 'class="nav-search"')

    def test_result_link_target_exists_on_reading_page(self):
        resp = self.get(q="damages")
        self.assertContains(resp, 'href="%s#n-item-%d"' % (reverse("read_subject", args=[self.subject.pk]), self.cited.pk))
        page = self.client.get(reverse("read_subject", args=[self.subject.pk]))
        self.assertContains(page, 'id="n-item-%d"' % self.cited.pk)
