"""Word export tests (T5.2, T5.2a): placeholder map, tag merge, zip limits, upload/download, signature.

Ports ``exportService.test.ts`` (the map), ``templateTags.test.ts`` (the merge regex) and
``shortTagTemplates.test.ts`` (the short-tag acceptance fixture). Adds the zip-limit tests (design 8.1),
the signature validation tests (R-SET-8) and the signature embedding acceptance tests (design 8.4).
"""

import datetime
import io
import re
import xml.dom.minidom
import zipfile
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase, TestCase, tag

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError, status_for
from fees.exports import docx_zip, images, template_prep, word
from fees.exports.placeholders import build_placeholder_map, is_known_tag
from fees.models import FeesSettings, Firm, Group, Matter, WordTemplate
from fees.services import memos, word_template
from fees.tests import docx_support as ds
from fees.tests.memory import assert_peak_under

FIXTURE = Path(__file__).parent / "fixtures" / "Template 2-11-2026 (short tags).docx"


def sample_memo(**over):
    memo = {
        "date": datetime.date(2026, 7, 15),
        "memo_number": "2026-27/1",
        "addressee_line1": "Acme Legal",
        "addressee_line2": "Mumbai",
        "matter_name": "Acme v Beta",
        "matter_short_name": None,
        "court_name": "High Court",
        "plaintiff_name": "Acme",
        "plaintiff_type": "Plaintiff",
        "defendant_name": "",
        "defendant_type": "",
        "client": "Acme",
        "num_appearances": 2,
        "fees_per_appearance": Decimal("5000"),
        "fees_appearances": Decimal("10000"),
        "dates_of_appearances": "1 Jan",
        "num_conferences": 1,
        "fees_per_conference": Decimal("3000"),
        "fees_conferences": Decimal("3000"),
        "dates_of_conferences": "2 Jan",
        "misc_drafting_description": "Drafting",
        "fees_misc_drafting": Decimal("1000"),
        "total_fees": Decimal("14000"),
    }
    memo.update(over)
    return memo


# ---------------------------------------------------------------------------
# Placeholder map (exportService.test.ts)
# ---------------------------------------------------------------------------


class PlaceholderMapTests(SimpleTestCase):
    def test_long_and_short_aliases_agree(self):
        mapping = build_placeholder_map(sample_memo())
        self.assertEqual(mapping["LINE_2_MEMO_NUMBER"], "2026-27/1")
        self.assertEqual(mapping["L2"], "2026-27/1")
        self.assertEqual(mapping["L16"], "2")
        self.assertEqual(mapping["L16W"], "2 Appearances")
        self.assertEqual(mapping["L19W"], "1 Conference")
        self.assertIs(mapping["IF_APP"], True)
        self.assertIs(mapping["SHOW_APPEARANCES"], True)

    def test_flags_follow_the_data(self):
        mapping = build_placeholder_map(
            sample_memo(num_appearances=0, fees_per_appearance=Decimal("0"), misc_drafting_description="",
                        fees_misc_drafting=Decimal("0"))
        )
        self.assertIs(mapping["IF_APP"], False)
        self.assertIs(mapping["IF_MISC"], False)
        self.assertIs(mapping["IF_DEF"], False)
        self.assertIs(mapping["IF_PL"], True)
        self.assertEqual(mapping["L16"], "")

    def test_short_name_wins_for_matter(self):
        mapping = build_placeholder_map(sample_memo(matter_short_name="Acme"))
        self.assertEqual(mapping["L7"], "Acme")

    def test_total_in_words_and_money(self):
        mapping = build_placeholder_map(sample_memo())
        self.assertIn("14,000", mapping["L24"])
        self.assertTrue(mapping["L24A"])

    def test_five_memo_tags_come_from_settings(self):
        settings = {
            "memo_default_name": "A. Name",
            "memo_default_designation": "Advocate",
            "memo_default_address": "Line 1\nLine 2",
            "memo_default_bank_details": "Bank X",
            "memo_default_pan": "ABCDE1234F",
        }
        mapping = build_placeholder_map(sample_memo(), settings)
        pairs = [("MEMO_NAME", "M1", "A. Name"), ("MEMO_DESIGNATION", "M2", "Advocate"),
                 ("MEMO_ADDRESS", "M3", "Line 1\nLine 2"), ("MEMO_BANK_DETAILS", "M4", "Bank X"),
                 ("MEMO_PAN", "M5", "ABCDE1234F")]
        for long_name, short, value in pairs:
            self.assertEqual(mapping[long_name], value)
            self.assertEqual(mapping[short], value)

    def test_blank_settings_give_empty_strings(self):
        mapping = build_placeholder_map(sample_memo(), None)
        self.assertEqual(mapping["M1"], "")
        self.assertEqual(mapping["MEMO_PAN"], "")

    def test_signature_tags_are_in_map_and_accepted(self):
        mapping = build_placeholder_map(sample_memo())
        self.assertEqual(mapping["MEMO_SIGNATURE"], "")
        self.assertEqual(mapping["MSIG"], "")
        for name in ("MEMO_SIGNATURE", "MSIG", "MEMO_NAME", "M5"):
            self.assertTrue(is_known_tag(name))

    def test_payment_and_internal_lines_are_not_in_the_map(self):
        mapping = build_placeholder_map(sample_memo())
        for key in mapping:
            self.assertNotIn("PAYMENT", key)
            self.assertNotIn("BANK_ACCOUNT", key)
        for n in (3, 4, 25, 26, 27, 28, 29, 30):
            self.assertNotIn(f"L{n}", mapping)
        self.assertFalse(is_known_tag("LINE_3_INTERNAL"))
        self.assertFalse(is_known_tag("PAYMENT_DETAILS"))


# ---------------------------------------------------------------------------
# Tag merge (templateTags.test.ts)
# ---------------------------------------------------------------------------


class TagMergeTests(SimpleTestCase):
    def test_tag_split_across_runs_is_merged(self):
        xml = "<w:r><w:t>{{LINE_16</w:t></w:r><w:r><w:t>_NUM_APPEARANCES}}</w:t></w:r>"
        self.assertIn("{{L16}}", template_prep.convert_template_xml(xml))

    def test_braces_split_across_runs(self):
        xml = "<w:r><w:t>{</w:t></w:r><w:r><w:t>{L2}</w:t></w:r><w:r><w:t>}</w:t></w:r>"
        self.assertIn("{{L2}}", template_prep.convert_template_xml(xml))

    def test_flags_are_shortened_with_prefix(self):
        out = template_prep.convert_template_xml("{{#SHOW_APPEARANCES}}x{{/SHOW_APPEARANCES}}")
        self.assertEqual(out, "{{#IF_APP}}x{{/IF_APP}}")

    def test_plural_word_folds_into_l16w(self):
        xml = "<w:t>{{LINE_16_NUM_APPEARANCES}}</w:t></w:r><w:r><w:t> Appearances</w:t>"
        out = template_prep.convert_template_xml(xml)
        self.assertIn("{{L16W}}", out)
        self.assertNotIn("Appearances", out)

    def test_conference_word_folds(self):
        out = template_prep.convert_template_xml("{{L19}} Conferences")
        self.assertEqual(out, "{{L19W}}")

    def test_memo_tags_pass_through(self):
        out = template_prep.convert_template_xml("{{MEMO_NAME}}{{ M1 }}{{MEMO_SIGNATURE}}")
        self.assertIn("{{MEMO_NAME}}", out)
        self.assertIn("{{MEMO_SIGNATURE}}", out)

    def test_hostile_input_is_fast(self):
        xml = "{" + "<a>" * 3000 + "{" + "<" * 3000
        template_prep.convert_template_xml(xml)

    def test_find_tags_trims_and_keeps_prefix(self):
        tags = template_prep.find_tags("{{ L2 }}{{#IF_APP}}{{/IF_APP}}")
        self.assertEqual(tags, {"L2", "#IF_APP", "/IF_APP"})


# ---------------------------------------------------------------------------
# Short-tag template acceptance (shortTagTemplates.test.ts)
# ---------------------------------------------------------------------------


class ShortTagFixtureTests(SimpleTestCase):
    def test_fixture_is_accepted_and_renders_without_leftover_tags(self):
        data = FIXTURE.read_bytes()
        prepared, tags = template_prep.prepare(data)
        self.assertIn("L2", tags)
        self.assertIn("#IF_APP", tags)
        mapping = build_placeholder_map(sample_memo())
        with word.render(prepared, mapping) as out:
            parts = ds.read_zip(out)
        document = parts["word/document.xml"].decode()
        self.assertNotIn("{{", document)
        self.assertIn("2026-27/1", document)
        xml.dom.minidom.parseString(parts["word/document.xml"])
        self.assertIn("word/media/image1.png", parts)

    def test_false_flags_drop_their_rows(self):
        prepared, _ = template_prep.prepare(FIXTURE.read_bytes())
        mapping = build_placeholder_map(
            sample_memo(num_conferences=0, fees_per_conference=Decimal("0"), dates_of_conferences="")
        )
        with word.render(prepared, mapping) as out:
            document = ds.read_zip(out)["word/document.xml"].decode()
        self.assertNotIn("2 Jan", document)
        xml.dom.minidom.parseString(document.encode())


# ---------------------------------------------------------------------------
# Renderer behaviour and zip limits (design 8.1)
# ---------------------------------------------------------------------------


class RenderTests(SimpleTestCase):
    def render(self, document, mapping, signature=None, **kw):
        prepared, _ = template_prep.prepare(ds.build_docx(document, **kw))
        with word.render(prepared, mapping, signature) as out:
            return ds.read_zip(out)

    def test_values_are_escaped_and_newlines_become_breaks(self):
        parts = self.render(ds.document_xml(ds.paragraph("{{M3}}")), {"M3": "A & B <c>\nD"})
        text = parts["word/document.xml"].decode()
        self.assertIn("A &amp; B &lt;c&gt;", text)
        self.assertIn("<w:br/>", text)
        xml.dom.minidom.parseString(text.encode())

    def test_unmapped_tag_renders_nothing(self):
        parts = self.render(ds.document_xml(ds.paragraph("a{{L2}}b")), {})
        self.assertIn(">ab<", parts["word/document.xml"].decode())

    def test_table_row_with_false_flag_is_dropped(self):
        row = lambda t: f"<w:tr><w:tc>{ds.paragraph(t)}</w:tc></w:tr>"  # noqa: E731
        body = "<w:tbl>" + row("{{#IF_APP}}first") + row("second{{/IF_APP}}") + row("keep") + "</w:tbl>"
        for flag, expect in ((False, False), (True, True)):
            parts = self.render(ds.document_xml(body), {"IF_APP": flag})
            text = parts["word/document.xml"].decode()
            self.assertEqual("first" in text, expect)
            self.assertEqual("second" in text, expect)
            self.assertIn("keep", text)

    def test_too_many_entries_refused(self):
        extra = {f"word/p{i}.bin": b"x" for i in range(docx_zip.MAX_ENTRIES + 5)}
        with self.assertRaises(FeesError) as ctx:
            template_prep.prepare(ds.build_docx(ds.document_xml(ds.paragraph("a")), extra))
        self.assertEqual(ctx.exception.code, "INVALID_TEMPLATE")

    def test_expansion_over_20mb_refused_by_bytes_read(self):
        # A highly compressible 21 MB part in a small file; refused by the bytes actually read.
        extra = {"word/big.bin": b"\0" * (21 * 1024 * 1024)}
        data = ds.build_docx(ds.document_xml(ds.paragraph("a")), extra)
        self.assertLess(len(data), docx_zip.MAX_TEMPLATE_BYTES)
        with self.assertRaises(FeesError) as ctx:
            template_prep.prepare(data)
        self.assertEqual(ctx.exception.code, "INVALID_TEMPLATE")

    def test_oversize_upload_refused_before_opening(self):
        with self.assertRaises(FeesError) as ctx:
            template_prep.prepare(b"PK" + b"\0" * (docx_zip.MAX_TEMPLATE_BYTES + 1))
        self.assertIn("2 MB", ctx.exception.message)

    def test_not_a_zip_and_missing_document_refused(self):
        with self.assertRaises(FeesError):
            template_prep.prepare(b"not a zip")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("hello.txt", "x")
        with self.assertRaises(FeesError):
            template_prep.prepare(buffer.getvalue())

    def test_unknown_tag_refused_and_listed(self):
        with self.assertRaises(FeesError) as ctx:
            template_prep.prepare(ds.build_docx(ds.document_xml(ds.paragraph("{{NOPE}} {{L2}}"))))
        self.assertEqual(ctx.exception.details["unknown_tags"], ["NOPE"])

    def test_declared_size_forgery_still_bounded(self):
        # Declared sizes come from the central directory; a part over the XML cap is refused by reading.
        big = "<w:t>" + "a" * (docx_zip.MAX_XML_PART_BYTES + 10) + "</w:t>"
        data = ds.build_docx(big)
        self.assertLess(len(data), docx_zip.MAX_TEMPLATE_BYTES)
        with self.assertRaises(FeesError):
            template_prep.prepare(data)


# ---------------------------------------------------------------------------
# Signature embedding (T5.2a, design 8.4)
# ---------------------------------------------------------------------------


def make_signature(data=None):
    data = data or ds.png_bytes(400, 100)
    content_type, extension, width, height = images.inspect_image(data)
    return word.Signature(content_type, extension, data, width, height)


class SignatureEmbeddingTests(SimpleTestCase):
    DOC = ds.document_xml(ds.paragraph("Yours, {{MEMO_SIGNATURE}} done"), ds.paragraph("{{M1}}"))

    def render(self, signature, **kw):
        prepared, _ = template_prep.prepare(ds.build_docx(self.DOC, **kw))
        with word.render(prepared, {"M1": "Name"}, signature) as out:
            return ds.read_zip(out)

    def test_png_is_embedded_with_relationship_and_drawing(self):
        sig = make_signature()
        parts = self.render(sig)
        media = [n for n in parts if n.startswith("word/media/")]
        self.assertEqual(len(media), 1)
        self.assertEqual(parts[media[0]], sig.data)
        rels = parts["word/_rels/document.xml.rels"].decode()
        self.assertIn(f'Target="{media[0][len("word/"):]}"', rels)
        self.assertIn("relationships/image", rels)
        document = parts["word/document.xml"].decode()
        self.assertIn("<w:drawing>", document)
        self.assertIn('r:embed="rIdMemoSignature"', document)
        self.assertNotIn("{{", document)
        self.assertLess(document.index("Yours,"), document.index("<w:drawing>"))
        self.assertLess(document.index("<w:drawing>"), document.index("done"))
        xml.dom.minidom.parseString(parts["word/document.xml"])
        xml.dom.minidom.parseString(parts["word/_rels/document.xml.rels"])
        types = parts["[Content_Types].xml"].decode()
        self.assertIn('Extension="png"', types)
        xml.dom.minidom.parseString(parts["[Content_Types].xml"])

    def test_picture_is_scaled_to_fit(self):
        cx, cy = make_signature(ds.png_bytes(4000, 1000)).extent()
        self.assertLessEqual(cx, 6 * 360000)
        self.assertLessEqual(cy, 25 * 36000)
        small_cx, small_cy = make_signature(ds.png_bytes(40, 20)).extent()
        self.assertEqual((small_cx, small_cy), (40 * 9525, 20 * 9525))

    def test_jpeg_is_embedded(self):
        sig = make_signature(ds.jpeg_bytes())
        parts = self.render(sig)
        self.assertTrue(any(n.endswith(".jpeg") for n in parts if n.startswith("word/media/")))
        self.assertIn('Extension="jpeg"', parts["[Content_Types].xml"].decode())

    def test_no_signature_removes_tag_and_adds_no_media(self):
        parts = self.render(None)
        self.assertFalse([n for n in parts if n.startswith("word/media/")])
        document = parts["word/document.xml"].decode()
        self.assertNotIn("w:drawing", document)
        self.assertNotIn("{{", document)
        self.assertNotIn("MEMO_SIGNATURE", document)
        xml.dom.minidom.parseString(parts["word/document.xml"])

    def test_signature_without_tag_adds_nothing(self):
        prepared, _ = template_prep.prepare(ds.build_docx(ds.document_xml(ds.paragraph("plain"))))
        with word.render(prepared, {}, make_signature()) as out:
            parts = ds.read_zip(out)
        self.assertFalse([n for n in parts if n.startswith("word/media/")])
        self.assertNotIn("rIdMemoSignature", parts["word/_rels/document.xml.rels"].decode())

    def test_missing_rels_part_is_created(self):
        parts = self.render(make_signature(), rels=None)
        self.assertIn("rIdMemoSignature", parts["word/_rels/document.xml.rels"].decode())

    def test_existing_default_content_type_is_not_duplicated(self):
        types = ds.CONTENT_TYPES.replace(
            "<Default Extension=\"xml\"", '<Default Extension="png" ContentType="image/png"/><Default Extension="xml"'
        )
        parts = self.render(make_signature(), content_types=types)
        self.assertEqual(parts["[Content_Types].xml"].decode().count('Extension="png"'), 1)

    def test_media_name_does_not_collide(self):
        parts = self.render(make_signature(), extra={"word/media/memo_signature.png": b"old"})
        self.assertEqual(parts["word/media/memo_signature.png"], b"old")
        self.assertEqual(len([n for n in parts if n.startswith("word/media/")]), 2)

    def test_tag_twice_embeds_two_drawings_one_media_part(self):
        doc = ds.document_xml(ds.paragraph("{{MSIG}}"), ds.paragraph("{{MEMO_SIGNATURE}}"))
        prepared, _ = template_prep.prepare(ds.build_docx(doc))
        with word.render(prepared, {}, make_signature()) as out:
            parts = ds.read_zip(out)
        self.assertEqual(parts["word/document.xml"].decode().count("<w:drawing>"), 2)
        self.assertEqual(len([n for n in parts if n.startswith("word/media/")]), 1)

    def test_signature_tag_in_header_is_removed_not_embedded(self):
        header = f'<w:hdr xmlns:w="{ds.W_NS}">{ds.paragraph("{{MSIG}}")}</w:hdr>'
        parts = self.render(make_signature(), extra={"word/header1.xml": header})
        self.assertNotIn("{{", parts["word/header1.xml"].decode())
        self.assertNotIn("w:drawing", parts["word/header1.xml"].decode())


# ---------------------------------------------------------------------------
# Image header checks
# ---------------------------------------------------------------------------


class ImageInspectTests(SimpleTestCase):
    def test_png_and_jpeg_sizes(self):
        self.assertEqual(images.inspect_image(ds.png_bytes(12, 7)), ("image/png", "png", 12, 7))
        self.assertEqual(images.inspect_image(ds.jpeg_bytes(30, 15)), ("image/jpeg", "jpeg", 30, 15))

    def test_garbage_and_truncated_are_none(self):
        self.assertIsNone(images.inspect_image(b"hello world, not an image at all"))
        self.assertIsNone(images.inspect_image(ds.png_bytes()[:20]))
        self.assertIsNone(images.inspect_image(b"\xff\xd8\xff"))
        self.assertIsNone(images.inspect_image(b""))

    def test_absurd_dimensions_are_none(self):
        self.assertIsNone(images.inspect_image(ds.png_bytes(30000, 10)))


# ---------------------------------------------------------------------------
# Upload / download service
# ---------------------------------------------------------------------------


def fees_profile(name="Word-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def data_version(profile):
    return FeesSettings.objects.filter(profile=profile).values_list("data_version", flat=True).first()


def seed_memo(profile, **over):
    firm = Firm.objects.create(profile=profile, name="Firm")
    group = Group.objects.create(profile=profile, firm=firm, name="Group")
    matter = Matter.objects.create(profile=profile, firm=firm, group=group, name="Matter")
    data = dict(date="2026-07-15", matter_id=matter.pk, addressee_line1="Acme Legal",
                num_appearances=2, fees_per_appearance=5000)
    data.update(over)
    return memos.create_memo(profile, data)


class TemplateServiceTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_info_before_upload(self):
        info = word_template.get_template_info(self.profile)
        self.assertFalse(info["has_template"])
        self.assertFalse(info["has_signature"])

    def test_upload_download_and_replace(self):
        data = FIXTURE.read_bytes()
        info = word_template.upload_template(self.profile, "My Template.docx", data)
        self.assertTrue(info["has_template"])
        self.assertEqual(info["filename"], "My Template.docx")
        self.assertIn("L2", info["tags"])
        name, back = word_template.download_template(self.profile)
        self.assertEqual((name, back), ("My Template.docx", data))
        other = ds.build_docx(ds.document_xml(ds.paragraph("{{L2}}")))
        word_template.upload_template(self.profile, "two.docx", other)
        self.assertEqual(word_template.download_template(self.profile), ("two.docx", other))
        self.assertEqual(WordTemplate.objects.filter(profile=self.profile).count(), 1)

    def test_upload_bumps_data_version_once(self):
        word_template.upload_template(self.profile, "a.docx", FIXTURE.read_bytes())
        first = data_version(self.profile)
        word_template.upload_template(self.profile, "b.docx", FIXTURE.read_bytes())
        self.assertEqual(data_version(self.profile), first + 1)
        word_template.get_template_info(self.profile)
        word_template.download_template(self.profile)
        self.assertEqual(data_version(self.profile), first + 1)

    def test_bad_name_and_bad_file_refused_and_nothing_stored(self):
        for name, data in (("a.txt", FIXTURE.read_bytes()), ("a.docx", b"junk")):
            with self.assertRaises(FeesError) as ctx:
                word_template.upload_template(self.profile, name, data)
            self.assertEqual(ctx.exception.code, "INVALID_TEMPLATE")
        self.assertFalse(word_template.get_template_info(self.profile)["has_template"])

    def test_download_without_template(self):
        with self.assertRaises(FeesError) as ctx:
            word_template.download_template(self.profile)
        self.assertEqual(ctx.exception.code, "NO_TEMPLATE")

    def test_other_profile_is_isolated(self):
        word_template.upload_template(self.profile, "a.docx", FIXTURE.read_bytes())
        other = fees_profile("Other")
        self.assertFalse(word_template.get_template_info(other)["has_template"])
        with self.assertRaises(FeesError):
            word_template.download_template(other)


class SignatureServiceTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_error_codes_and_statuses(self):
        self.assertEqual(status_for("INVALID_SIGNATURE"), 422)
        self.assertEqual(status_for("SIGNATURE_NOT_FOUND"), 404)
        self.assertEqual(FeesError("INVALID_SIGNATURE").status, 422)
        self.assertNotEqual(FeesError("SIGNATURE_NOT_FOUND").message, "SIGNATURE_NOT_FOUND")

    def test_upload_download_replace(self):
        png = ds.png_bytes()
        info = word_template.upload_signature(self.profile, "sig.png", "image/png", png)
        self.assertTrue(info["has_signature"])
        self.assertEqual(info["signature_content_type"], "image/png")
        self.assertEqual(word_template.download_signature(self.profile), ("sig.png", "image/png", png))
        jpg = ds.jpeg_bytes()
        word_template.upload_signature(self.profile, "me.JPG", "image/jpg", jpg)
        self.assertEqual(word_template.download_signature(self.profile), ("me.JPG", "image/jpeg", jpg))

    def test_jpeg_extension_and_neutral_type_accepted(self):
        word_template.upload_signature(self.profile, "x.jpeg", "application/octet-stream", ds.jpeg_bytes())
        word_template.upload_signature(self.profile, "x.png", "", ds.png_bytes())

    def test_upload_bumps_data_version_once(self):
        word_template.upload_signature(self.profile, "s.png", "image/png", ds.png_bytes())
        first = data_version(self.profile)
        word_template.upload_signature(self.profile, "s.png", "image/png", ds.png_bytes())
        self.assertEqual(data_version(self.profile), first + 1)

    def assert_refused(self, name, content_type, data):
        with self.assertRaises(FeesError) as ctx:
            word_template.upload_signature(self.profile, name, content_type, data)
        self.assertEqual(ctx.exception.code, "INVALID_SIGNATURE")
        self.assertEqual(ctx.exception.status, 422)
        self.assertFalse(word_template.get_template_info(self.profile)["has_signature"])

    def test_wrong_type_refused(self):
        self.assert_refused("sig.gif", "image/gif", ds.png_bytes())
        self.assert_refused("sig.png", "image/gif", ds.png_bytes())
        self.assert_refused("sig", "image/png", ds.png_bytes())
        self.assert_refused("sig.pdf", "application/pdf", b"%PDF-1.4")

    def test_over_2mb_refused_before_the_image_is_opened(self):
        big = ds.png_bytes() + b"\0" * word_template.MAX_SIGNATURE_BYTES
        original = images.inspect_image
        images.inspect_image = lambda data: self.fail("image was opened")
        try:
            self.assert_refused("sig.png", "image/png", big)
        finally:
            images.inspect_image = original

    def test_exactly_2mb_is_accepted_when_valid(self):
        data = ds.png_bytes()
        data += b"\0" * (word_template.MAX_SIGNATURE_BYTES - len(data))
        word_template.upload_signature(self.profile, "sig.png", "image/png", data)

    def test_empty_corrupt_and_mismatched_refused(self):
        self.assert_refused("sig.png", "image/png", b"")
        self.assert_refused("sig.png", "image/png", b"not really a png file at all....")
        self.assert_refused("sig.png", "image/png", ds.jpeg_bytes())
        self.assert_refused("sig.jpg", "image/jpeg", ds.png_bytes())

    def test_download_without_signature(self):
        with self.assertRaises(FeesError) as ctx:
            word_template.download_signature(self.profile)
        self.assertEqual(ctx.exception.code, "SIGNATURE_NOT_FOUND")
        self.assertEqual(ctx.exception.status, 404)

    def test_signature_survives_template_replace_and_vice_versa(self):
        word_template.upload_signature(self.profile, "s.png", "image/png", ds.png_bytes())
        word_template.upload_template(self.profile, "t.docx", FIXTURE.read_bytes())
        info = word_template.get_template_info(self.profile)
        self.assertTrue(info["has_signature"])
        self.assertTrue(info["has_template"])


class RenderMemoTests(TestCase):
    TEMPLATE = ds.build_docx(
        ds.document_xml(ds.paragraph("{{L2}} {{M1}}"), ds.paragraph("{{MEMO_SIGNATURE}}"))
    )

    def setUp(self):
        self.profile = fees_profile()
        self.memo = seed_memo(self.profile)
        FeesSettings.objects.update_or_create(
            profile=self.profile, defaults={"memo_default_name": "Z. Madon"}
        )
        word_template.upload_template(self.profile, "t.docx", self.TEMPLATE)

    def memo_id(self):
        return self.memo.pk

    def test_render_with_png_signature(self):
        png = ds.png_bytes(200, 60)
        word_template.upload_signature(self.profile, "s.png", "image/png", png)
        name, out = word_template.render_memo_docx(self.profile, self.memo_id())
        with out:
            parts = ds.read_zip(out)
        self.assertTrue(name.endswith(".docx"))
        media = [n for n in parts if n.startswith("word/media/")]
        self.assertEqual([parts[n] for n in media], [png])
        self.assertIn("relationships/image", parts["word/_rels/document.xml.rels"].decode())
        document = parts["word/document.xml"].decode()
        self.assertEqual(document.count("<w:drawing>"), 1)
        self.assertIn("Z. Madon", document)
        self.assertNotIn("{{", document)

    def test_render_without_signature_is_valid_and_has_no_media(self):
        name, out = word_template.render_memo_docx(self.profile, self.memo_id())
        with out:
            parts = ds.read_zip(out)
        self.assertFalse([n for n in parts if n.startswith("word/media/")])
        document = parts["word/document.xml"].decode()
        self.assertNotIn("w:drawing", document)
        self.assertNotIn("{{", document)
        xml.dom.minidom.parseString(parts["word/document.xml"])
        self.assertTrue(re.search(r"\.docx$", name))

    def test_render_is_read_only(self):
        before = data_version(self.profile)
        word_template.render_memo_docx(self.profile, self.memo_id())[1].close()
        self.assertEqual(data_version(self.profile), before)

    def test_render_without_template(self):
        other = fees_profile("NoTemplate")
        with self.assertRaises(FeesError) as ctx:
            word_template.render_memo_docx(other, 1)
        self.assertEqual(ctx.exception.code, "NO_TEMPLATE")

    def test_render_missing_memo(self):
        with self.assertRaises(FeesError) as ctx:
            word_template.render_memo_docx(self.profile, 999999)
        self.assertEqual(ctx.exception.code, "MEMO_NOT_FOUND")


@tag("memory")
class WordMemoryTests(TestCase):
    def test_render_with_signature_under_2_mb(self):
        prepared, _tags = template_prep.prepare(FIXTURE.read_bytes())
        mapping = build_placeholder_map(sample_memo())
        sig = make_signature(ds.png_bytes(600, 200))
        with assert_peak_under(self, 2):
            out = word.render(prepared, mapping, sig)
            out.close()

    def test_prepare_under_2_mb(self):
        data = FIXTURE.read_bytes()
        with assert_peak_under(self, 2):
            template_prep.prepare(data)
