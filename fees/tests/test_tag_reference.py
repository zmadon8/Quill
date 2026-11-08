"""The downloadable Word tag reference (item 2.5): the generator, its metadata and the download."""
import io
import xml.dom.minidom
import zipfile

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from fees.exports import tag_reference
from fees.exports.placeholders import FLAG_TAGS, TAG_DOCS, TEXT_TAGS
from fees.pages import DOCX_TYPE
from fees.tests.test_view_permissions import PermissionBase


def document_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml_bytes = archive.read("word/document.xml")
    dom = xml.dom.minidom.parseString(xml_bytes)
    return "".join(node.firstChild.data for node in dom.getElementsByTagName("w:t") if node.firstChild)


class TagDocsTests(SimpleTestCase):
    def test_every_accepted_tag_is_documented(self):
        documented = set(TAG_DOCS) | {tag_reference.names_for(key)[1] for key in TAG_DOCS}
        for name in sorted(TEXT_TAGS | FLAG_TAGS):
            self.assertIn(name, documented, name)

    def test_every_documented_key_is_a_real_tag(self):
        for key in TAG_DOCS:
            long_name, short_name = tag_reference.names_for(key)
            pool = FLAG_TAGS if key.startswith("SHOW_") else TEXT_TAGS
            self.assertIn(short_name, pool, key)
            if long_name is not None:
                self.assertIn(long_name, pool, key)

    def test_each_entry_has_a_description_and_an_example(self):
        for key, (description, example) in TAG_DOCS.items():
            self.assertTrue(description.strip(), key)
            self.assertTrue(example.strip(), key)

    def test_the_groups_list_every_key_exactly_once(self):
        listed = [key for _heading, _intro, keys in tag_reference.GROUPS for key in keys]
        self.assertEqual(sorted(listed), sorted(TAG_DOCS))
        self.assertEqual(len(listed), len(set(listed)))


class BuildTagReferenceTests(SimpleTestCase):
    def setUp(self):
        self.data = tag_reference.build_tag_reference()
        self.text = document_text(self.data)

    def test_it_is_a_zip_with_the_docx_parts(self):
        with zipfile.ZipFile(io.BytesIO(self.data)) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
        self.assertLessEqual({"[Content_Types].xml", "_rels/.rels", "word/document.xml"}, names)

    def test_it_names_every_tag_long_and_short(self):
        for key in TAG_DOCS:
            long_name, short_name = tag_reference.names_for(key)
            flag = key.startswith("SHOW_")
            prefix = "{{#" if flag else "{{"
            self.assertIn(prefix + short_name + "}}", self.text, key)
            if long_name is not None:
                self.assertIn(prefix + long_name + "}}", self.text, key)

    def test_it_has_the_four_column_headings_and_the_descriptions(self):
        for heading in ("Long name", "Short name", "What it fills in", "Example"):
            self.assertIn(heading, self.text)
        self.assertIn("Total fees in words", self.text)
        self.assertIn("{{L16W}}", self.text)

    def test_it_has_no_em_dash(self):
        self.assertNotIn(chr(0x2014), self.text)


@override_settings(SECURE_SSL_REDIRECT=False)
class TagReferenceDownloadTests(PermissionBase):
    def test_a_reader_gets_a_valid_docx(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse("fees_template_tags_download"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], DOCX_TYPE)
        self.assertIn(".docx", response["Content-Disposition"])
        self.assertIn("{{L24}}", document_text(response.content))

    def test_the_settings_page_links_to_it(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse("fees_settings"))
        self.assertContains(response, reverse("fees_template_tags_download"))
