"""Memo export file names (T5.1, R-FN-7): defaults, placeholders, segments, sanitising, header."""

import datetime
import random
from types import SimpleNamespace

from django.test import SimpleTestCase

from fees.exports.filenames import (
    DEFAULT_PATTERN,
    PLACEHOLDERS,
    content_disposition,
    memo_export_filename,
    validate_pattern,
)

TODAY = datetime.date(2026, 8, 9)


def make_memo(
    number="2026-27/5",
    matter="Matter",
    short="",
    seq=5,
    firm="Firm X",
    group="Group Y",
    date=datetime.date(2026, 7, 15),
    client="Client Z",
):
    return SimpleNamespace(
        memo_number=number,
        seq=seq,
        date=date,
        client=client,
        matter=SimpleNamespace(name=matter, short_name=short),
        firm=SimpleNamespace(name=firm),
        group=SimpleNamespace(name=group),
    )


def make_settings(pattern="", owner="Ziyad Madon"):
    return SimpleNamespace(memo_filename_pattern=pattern, export_owner_name=owner)


def name(memo=None, pattern="", owner="Ziyad Madon"):
    return memo_export_filename(memo or make_memo(), make_settings(pattern, owner), today=TODAY)


class DefaultOutputTests(SimpleTestCase):
    """R-FN-5: the five defaults are identical to the original."""

    def test_with_slash(self):
        self.assertEqual(name(), "Memo 5 of 2026-27 Ziyad Madon (Matter).docx")

    def test_without_slash(self):
        self.assertEqual(name(make_memo(number="ABC-7")), "Memo ABC-7 Ziyad Madon (Matter).docx")

    def test_slash_in_matter(self):
        memo = make_memo(number="2026-27/1", matter="A/B Matter", seq=1)
        self.assertEqual(name(memo), "Memo 1 of 2026-27 Ziyad Madon (A-B Matter).docx")

    def test_short_name(self):
        memo = make_memo(number="2026-27/1", matter="Brandwings India Pvt Ltd", short="Brandwings", seq=1)
        self.assertEqual(name(memo), "Memo 1 of 2026-27 Ziyad Madon (Brandwings).docx")

    def test_draft(self):
        memo = make_memo(number=None, seq=0)
        self.assertEqual(name(memo), "Memo 0 Ziyad Madon (Matter).docx")

    def test_blank_pattern_is_default(self):
        self.assertEqual(name(pattern="   "), name(pattern=DEFAULT_PATTERN))

    def test_several_slashes(self):
        self.assertEqual(name(make_memo(number="A/B/7")), "Memo 7 of A-B Ziyad Madon (Matter).docx")


class OriginalUnitTests(SimpleTestCase):
    """The three unit tests of exportService.test.ts re-run through the new function."""

    def test_matches_required_format(self):
        memo = make_memo(number="2026-27/1", matter="Varian Arbitration", seq=1)
        self.assertEqual(name(memo), "Memo 1 of 2026-27 Ziyad Madon (Varian Arbitration).docx")

    def test_sanitises_slashes_in_matter(self):
        memo = make_memo(number="2026-27/1", matter="A/B Matter", seq=1)
        self.assertEqual(name(memo), "Memo 1 of 2026-27 Ziyad Madon (A-B Matter).docx")

    def test_short_name_used(self):
        memo = make_memo(number="2026-27/1", matter="Brandwings India Pvt Ltd", short="Brandwings", seq=1)
        self.assertEqual(name(memo), "Memo 1 of 2026-27 Ziyad Madon (Brandwings).docx")


class Property20Tests(SimpleTestCase):
    """Property 20, as a seeded loop of random matter names."""

    ALPHABET = "abcXYZ019 /\\:*?\"<>|-_.()&"

    def test_property_20(self):
        rng = random.Random(20)
        cases = 0
        while cases < 200:
            raw = "".join(rng.choice(self.ALPHABET) for _ in range(rng.randint(1, 40)))
            matter = raw.strip()
            if not (1 <= len(matter) <= 150):
                continue
            cases += 1
            seq = rng.randint(1, 999)
            memo = make_memo(number="2026-27/%d" % seq, matter=matter, seq=seq)
            sanitized = "".join("-" if c in '/\\:*?"<>|' else c for c in matter).strip()
            expected = "Memo %d of 2026-27 Ziyad Madon (%s).docx" % (seq, sanitized)
            self.assertEqual(name(memo), expected, repr(matter))


class PlaceholderTests(SimpleTestCase):
    def test_each_placeholder(self):
        memo = make_memo(short="Short", matter="Full Name")
        expected = {
            "memo_no": "5",
            "fy": "2026-27",
            "number_raw": "2026-27-5",
            "owner": "Ziyad Madon",
            "matter": "Short",
            "matter_name": "Full Name",
            "short_name": "Short",
            "firm": "Firm X",
            "group": "Group Y",
            "date": "15.07.2026",
            "date_iso": "2026-07-15",
            "today": "2026-08-09",
            "client": "Client Z",
        }
        self.assertEqual(set(expected), set(PLACEHOLDERS))
        for key, value in expected.items():
            self.assertEqual(name(memo, "{%s}" % key), value + ".docx", key)

    def test_matter_without_short_name(self):
        self.assertEqual(name(make_memo(matter="Full"), "{matter}"), "Full.docx")

    def test_no_date_is_empty(self):
        memo = make_memo(date=None)
        self.assertEqual(name(memo, "A{date}"), "A.docx")


class OptionalSegmentTests(SimpleTestCase):
    def test_kept_when_all_filled(self):
        self.assertEqual(name(pattern="{memo_no}[ of {fy}]"), "5 of 2026-27.docx")

    def test_dropped_when_any_empty(self):
        memo = make_memo(number="ABC-7", short="")
        self.assertEqual(name(memo, "{memo_no}[ ({short_name}) {fy}]"), "ABC-7.docx")

    def test_dropped_with_brackets(self):
        self.assertNotIn("[", name(make_memo(number="ABC-7"), "X[ of {fy}]"))
        self.assertEqual(name(make_memo(number="ABC-7"), "X[ of {fy}]"), "X.docx")

    def test_blank_owner_drops_one_space(self):
        self.assertEqual(name(owner=""), "Memo 5 of 2026-27 (Matter).docx")

    def test_blank_owner_at_start(self):
        self.assertEqual(name(pattern="{owner} {matter}", owner=""), "Matter.docx")


class SanitisingTests(SimpleTestCase):
    def test_each_illegal_character_in_value(self):
        for ch in '/\\:*?"<>|':
            memo = make_memo(matter="a%sb" % ch)
            self.assertEqual(name(memo, "{matter}"), "a-b.docx", ch)

    def test_each_illegal_character_in_literal(self):
        for ch in '/\\:*?"<>|':
            self.assertEqual(name(pattern="a%sb" % ch), "a-b.docx", ch)

    def test_control_characters_removed(self):
        memo = make_memo(matter="a\x00b\x1fc\x7fd\ne")
        self.assertEqual(name(memo, "{matter}"), "abcde.docx")

    def test_owner_is_sanitised(self):
        self.assertEqual(name(pattern="{owner}", owner="A/B"), "A-B.docx")

    def test_no_path_separator_possible(self):
        out = name(pattern="../..\\{matter}/x", memo=make_memo(matter="../etc"))
        self.assertNotIn("/", out)
        self.assertNotIn("\\", out)
        self.assertFalse(out.startswith("."))


class LengthAndExtensionTests(SimpleTestCase):
    def test_stem_cut_at_150(self):
        out = name(make_memo(matter="m" * 300), "{matter}")
        self.assertEqual(out, "m" * 150 + ".docx")
        self.assertLessEqual(len(out), 155)

    def test_cut_then_trimmed(self):
        out = name(make_memo(matter="m" * 149 + " tail"), "{matter}")
        self.assertEqual(out, "m" * 149 + ".docx")

    def test_typed_extension_removed(self):
        self.assertEqual(name(pattern="Memo {memo_no}.DOCX"), "Memo 5.docx")
        self.assertEqual(name(pattern="Memo {memo_no}.docx"), "Memo 5.docx")

    def test_trailing_dots_and_spaces_removed(self):
        self.assertEqual(name(pattern="Memo {memo_no}. . "), "Memo 5.docx")

    def test_always_ends_with_docx(self):
        for pattern in ("", "x", "{matter}", "[{fy}]"):
            self.assertTrue(name(pattern=pattern).endswith(".docx"))


class FallbackAndValidationTests(SimpleTestCase):
    DEFAULT = "Memo 5 of 2026-27 Ziyad Madon (Matter).docx"

    def test_unknown_placeholder_rejected_and_falls_back(self):
        self.assertTrue(validate_pattern("{nope}"))
        self.assertEqual(name(pattern="{nope}"), self.DEFAULT)

    def test_unbalanced_rejected(self):
        for pattern in ("{memo_no", "memo_no}", "[abc", "abc]", "[a[b]]", "{a{memo_no}}"):
            self.assertTrue(validate_pattern(pattern), pattern)

    def test_too_long_rejected(self):
        self.assertTrue(validate_pattern("x" * 201))
        self.assertEqual(validate_pattern("x" * 200), [])

    def test_valid_and_blank(self):
        self.assertEqual(validate_pattern(DEFAULT_PATTERN), [])
        self.assertEqual(validate_pattern(""), [])
        self.assertEqual(validate_pattern(None), [])
        self.assertEqual(validate_pattern("   "), [])

    def test_blank_falls_back(self):
        self.assertEqual(name(pattern=""), self.DEFAULT)

    def test_empty_stem_falls_back(self):
        self.assertEqual(name(pattern="{short_name}"), self.DEFAULT)
        self.assertEqual(name(pattern="..."), self.DEFAULT)
        self.assertEqual(name(pattern=".docx"), self.DEFAULT)

    def test_pattern_override_for_preview(self):
        settings = make_settings("{firm}")
        out = memo_export_filename(make_memo(), settings, pattern="{group}", today=TODAY)
        self.assertEqual(out, "Group Y.docx")


class ContentDispositionTests(SimpleTestCase):
    def test_ascii_name(self):
        self.assertEqual(
            content_disposition("Memo 5.docx"),
            "attachment; filename=\"Memo 5.docx\"; filename*=UTF-8''Memo%205.docx",
        )

    def test_non_ascii_fallback_and_encoding(self):
        header = content_disposition("Outstanding\u2014Firm Summary.xlsx")
        self.assertIn('filename="Outstanding_Firm Summary.xlsx"', header)
        self.assertIn("filename*=UTF-8''Outstanding%E2%80%94Firm%20Summary.xlsx", header)

    def test_quote_and_percent_in_fallback(self):
        header = content_disposition('a"b%c.docx')
        self.assertIn('filename="a_b_c.docx"', header)
        self.assertIn("a%22b%25c.docx", header)

    def test_no_raw_non_ascii_in_header(self):
        header = content_disposition("M\u00e9mo \u20b9.docx")
        header.encode("ascii")
