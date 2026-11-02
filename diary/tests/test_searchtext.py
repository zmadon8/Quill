"""Pure tests for diary/searchtext.py (no Django). CITATIONS are real citation strings from the owner's
Case Law Diary.docx, collected with the pure importer (diary/importer/docx_reader.py + plan.py)."""
import random
import time
import unittest

from diary import searchtext as st

# Real citations of the owner's Diary (a sample of 45 of the 693 imported).
CITATIONS = [
    'AIR 2026 SC 2041',
    'Akash Impex v. MCGM [(2014) 1 MahLJ 498] @ paras 13-14',
    'Andhra Pradesh Power Generation Corp [(2026) 3 SCC 491] @ para 15-16',
    'Anil Kak [(2008)7 SCC 695 ; Neelkanth 2018 SCC OnLine Bom 5970 @ para 244]',
    'Anil Kumar Srivastava v. State of U.P. [(2004) 8 SCC 671] @ Paras 11-13',
    'ArcellorMittal [(2019) 2 SCC 1]',
    'Arjun Singh [AIR 1964 SC 993 @ Para 14]',
    'Arunima Baruah v. Union of India [(2007) 6 SCC 120] @ para 12',
    'B. Santoshamma v. D. Sarala [2020 SCC OnLine SC 756 @ para 72]',
    'B.R. Enterprises v. State of U.P [(1999) 9 SCC 700] @ Para 57',
    'Bengal Chemists [(2018) 3 SCC 41]',
    'Best Sellers [(2012) 6 SCC 792]',
    'Bhagwandas Fatechand Daswani v. HPA International [(2000) 2 SCC 13] @ Para 3',
    'Celir LLP v Bafna Motors 2023 SCC OnLine SC 1209 @ para 82, 88, 105',
    'Chalasani [(2024) 10 SCC 303] @ 28-41 ; IFB Agro [(2023) 4 SCC 209] @ paras 21-24',
    'Chiranjilal Shrilal Goenka [(1993) 2 SCC 507] @ para 18, Hindustan Zinc [(2019) 17 SCC 82] @ para 18 (Nariman, J)',
    'DDA v/s Skipper [(1996) 4 SCC 622]',
    'Deccan Paper Mills [2020 SCC OnLine 655] @ paras 22-3',
    'Emkay Global [(2018) 9 SCC 49] ; Indus Mobile [(2017) 7 SCC 678 @ paras 2-4 & 19]',
    'Hari Shankar Singhania v Gaur Hari Singhania [(2006) 4 SCC 658] @ para 42-53',
    'Hemedra Rasiklal Ghia (FB) [2008 SCC OnLine Bom 1017 @ paras 61, 62, 86, 87]',
    'Himadri Chemicals [(2007) 8 SCC 110 @ para 14]',
    'Indapur Dairy and Milk [2019 SCC OnLine Bom 1678]',
    'Kashinath Sankarappa Wani [AIR 1958 SC 437] – 3 Judges',
    'Kharda Co. [AIR 1962 SC 1810] @ para 30',
    'Mahendra Pratap Singh (deceased) and another vs. Smt. Padam Kumari Devi [AIR 1993 All 143]',
    'National Insurance Co. v/s Pranay Sethi [(2017) 16 SCC 680 (5J)]; UT of Ladakh [2023 INSC 804] @ para 35',
    'Pila Pahan [(2026) 7 SCC 180] @ para 28.1 & 28.16',
    'Pipe Arts [(2008) 6 MahLJ 280 DB @ Para 11]',
    'Rama Narang [(2006) 11 SCC 114]',
    'Rama Shankar Singh [AIR 1970 SC 716]',
    'Ramdas v Kalawati [2021 SCC OnLine Bom 245 @ para 16]',
    'Reliance Eminent Trading and Commercial Pvt Ltd v DDA [2026 INSC 436]',
    'Ssangyong v. NHAI [2019 SCC OnLine SC 677] (Nariman, J.)',
    'Swastik v. Gammon [2018 SCC OnLine NCLT 9730 @ paras 6.5 & 7]',
    'Taherbhai Abdulbhai [(2005) 1 MahLJ 566 @ para 7]',
    'Tarapore & Co v. Cochin Shipyard [(1984) 2 SCC 680]',
    'Tippanna v. Ghanashyam [AIR 2004 Kar 446]',
    'Totalal vs. The State [AIR 1963 Raj 6] – Rajasthan HC, 1 judge',
    'Umesh Goel [(2016) 11 SCC 313]',
    'UoI v Jahangir Byramjee Jeejeebhoy [2024 SCC OnLine SC 489] @ para 35',
    'Usha Rectifier Corporation v. CCE [(2011) 11 SCC 571] @ para 10',
    'Variavan Saraswathi v Eachampi Thevi [(1993) Supp (2) SCC 201] @ para 6',
    'Vibhor Garg v Neha [(2025) 10 SCC 128] @ paras 50-52',
    'Vilayati Ram Mittal [2017 SCC OnLine Bom 8479 @ para 27] (DB)',
]


def hit(fields, query):
    return st.match_fields(fields, st.parse_query(query))


class NormaliseTests(unittest.TestCase):
    def test_punctuation_and_case(self):
        self.assertEqual(st.normalise("(2018) 9 SCC 49"), "2018 9 scc 49")
        self.assertEqual(st.normalise("  A--b..C  "), "a b c")

    def test_empty_and_punctuation_only(self):
        self.assertEqual(st.normalise(""), "")
        self.assertEqual(st.normalise(None), "")
        self.assertEqual(st.normalise("()[] - ..."), "")

    def test_ampersand_is_a_letter(self):
        self.assertEqual(st.normalise("L&T Finance"), "l&t finance")
        self.assertEqual(st.normalise("Tarapore & Co"), "tarapore & co")

    def test_curly_and_straight_quotes_are_alike(self):
        self.assertEqual(st.normalise("Smith's"), st.normalise("Smith\u2019s"))

    def test_underscore_is_a_separator(self):
        self.assertEqual(st.normalise("a_b"), "a b")

    def test_idx_map_basic(self):
        norm, idx_map = st.normalise_with_map("(2018) 9 SCC 49")
        self.assertEqual(norm, "2018 9 scc 49")
        self.assertEqual(len(idx_map), len(norm))
        self.assertEqual(idx_map[0], 1)  # "2"
        self.assertEqual(idx_map[4], 5)  # the collapsed space starts at ")"
        self.assertEqual(idx_map[-1], 14)

    def test_idx_map_points_at_same_letter(self):
        for text in CITATIONS:
            norm, idx_map = st.normalise_with_map(text)
            self.assertEqual(norm, st.normalise(text))
            self.assertEqual(len(idx_map), len(norm))
            for i, ch in enumerate(norm):
                if ch != " ":
                    self.assertEqual(text[idx_map[i]].lower(), ch)
                else:
                    self.assertFalse(text[idx_map[i]].isalnum())
            self.assertEqual(idx_map, sorted(idx_map))

    def test_collapsed_space_maps_to_start_of_run(self):
        norm, idx_map = st.normalise_with_map("ab ... cd")
        self.assertEqual(norm, "ab cd")
        self.assertEqual(idx_map[2], 2)

    def test_leading_and_trailing_separators_dropped(self):
        norm, idx_map = st.normalise_with_map("  [x]  ")
        self.assertEqual((norm, idx_map), ("x", [3]))

    def test_lower_that_changes_length(self):
        text = "\u0130stanbul v. State"
        norm, idx_map = st.normalise_with_map(text)
        self.assertEqual(len(idx_map), len(norm))
        self.assertTrue(norm.endswith(" v state"))
        self.assertEqual(idx_map[0], 0)
        self.assertEqual(idx_map[1], 0)  # the combining dot belongs to the same original letter
        self.assertEqual(text[idx_map[-1]], "e")
        # a match late in the text still maps to the right place
        spans = hit([("f", text)], "state")["f"]
        self.assertEqual([text[s:e] for s, e in spans], ["State"])


class ParseQueryTests(unittest.TestCase):
    def test_words(self):
        self.assertEqual(st.parse_query("2018 9 SCC"), [st.Term("2018", False), st.Term("9", False), st.Term("scc", False)])

    def test_punctuated_word_splits(self):
        self.assertEqual([t.text for t in st.parse_query("(2018)9")], ["2018", "9"])

    def test_phrase_straight_and_curly(self):
        for q in ('"scc 49"', "\u201cscc 49\u201d"):
            self.assertEqual(st.parse_query(q), [st.Term("scc 49", True)])

    def test_phrase_and_words(self):
        terms = st.parse_query('arbitr "scc 49" Bom')
        self.assertEqual([(t.text, t.phrase) for t in terms], [("arbitr", False), ("scc 49", True), ("bom", False)])

    def test_unterminated_quote_runs_to_end(self):
        self.assertEqual(st.parse_query('x "scc 49'), [st.Term("x", False), st.Term("scc 49", True)])

    def test_empty_and_punctuation_only(self):
        for q in ("", "   ", "()", '""', '"..."', None):
            self.assertEqual(st.parse_query(q), [])


class MatchTests(unittest.TestCase):
    def test_punctuation_insensitive_citation(self):
        self.assertIsNotNone(hit([("c", "(2018) 9 SCC 49")], "2018 9 SCC 49"))

    def test_case_insensitive(self):
        self.assertIsNotNone(hit([("c", "Arbitration Act")], "ARBITRATION"))

    def test_partial_word(self):
        self.assertIsNotNone(hit([("c", "Arbitration Act")], "arbitr"))
        self.assertIsNotNone(hit([("c", "Arbitration Act")], "tion act"))

    def test_curly_vs_straight(self):
        self.assertIsNotNone(hit([("c", "Smith\u2019s case")], "Smith's"))
        self.assertIsNotNone(hit([("c", "Smith's case")], "Smith\u2019s"))

    def test_ampersand_not_and(self):
        self.assertIsNone(hit([("c", "L&T Finance")], "L and T"))
        self.assertIsNone(hit([("c", "Land T")], "l&t"))
        self.assertIsNone(hit([("c", "Tarapore and Co")], "Tarapore & Co"))
        self.assertIsNone(hit([("c", "Tarapore & Co")], "Tarapore and Co"))
        self.assertIsNotNone(hit([("c", "Tarapore & Co")], "tarapore & co"))

    def test_phrase_is_whole_words_in_sequence(self):
        self.assertIsNotNone(hit([("c", "(2018) 9 SCC 49")], '"scc 49"'))
        self.assertIsNone(hit([("c", "(2018) 9 SCC 490")], '"scc 49"'))
        self.assertIsNotNone(hit([("c", "(2018) 9 SCC 490")], "scc 49"))  # unquoted is a partial match
        self.assertIsNone(hit([("c", "9 SCC 49")], '"49 scc"'))
        self.assertIsNone(hit([("c", "xscc 49")], '"scc 49"'))

    def test_phrase_does_not_span_fields(self):
        fields = [("a", "ends with scc"), ("b", "49 starts")]
        self.assertIsNone(hit(fields, '"scc 49"'))
        self.assertIsNotNone(hit(fields, "scc 49"))  # but two words may be in two fields

    def test_multi_word_and_across_fields(self):
        fields = [("citation", "(2018) 9 SCC 49"), ("comment", "Arbitration agreement")]
        result = hit(fields, "scc agreement")
        self.assertEqual(sorted(result), ["citation", "comment"])
        self.assertIsNone(hit(fields, "scc missing"))

    def test_empty_and_punctuation_only_queries(self):
        self.assertEqual(hit([("a", "x")], ""), {})
        self.assertEqual(hit([("a", "x")], "()"), {})
        self.assertEqual(st.match_fields([], []), {})

    def test_no_fields_no_match(self):
        self.assertIsNone(hit([], "x"))
        self.assertIsNone(hit([("a", "")], "x"))

    def test_highlight_maps_back_to_original(self):
        text = "(2018) 9 SCC 49"
        spans = hit([("c", text)], '"2018 9 scc 49"')["c"]
        self.assertEqual(spans, [(1, 15)])
        self.assertEqual(text[spans[0][0]:spans[0][1]], "2018) 9 SCC 49")

    def test_words_of_a_query_that_sit_together_highlight_as_one(self):
        text = "(2018) 9 SCC 49"
        spans = hit([("c", text)], "2018 9 scc 49")["c"]
        self.assertEqual([text[s:e] for s, e in spans], ["2018) 9 SCC 49"])

    def test_highlight_partial_word(self):
        text = "The Arbitration Act"
        spans = hit([("c", text)], "arbitr")["c"]
        self.assertEqual([text[s:e] for s, e in spans], ["Arbitr"])

    def test_highlight_every_occurrence_and_merge(self):
        text = "scc scc"
        spans = hit([("c", text)], "scc")["c"]
        self.assertEqual(spans, [(0, 7)])  # neighbours separated by one space are one highlight
        spans = hit([("c", "scc x scc")], "scc")["c"]
        self.assertEqual(spans, [(0, 3), (6, 9)])
        spans = hit([("c", "abcd")], "ab bc")["c"]
        self.assertEqual(spans, [(0, 3)])  # overlapping matches merge

    def test_every_real_citation_finds_itself(self):
        for text in CITATIONS:
            self.assertIsNotNone(hit([("c", text)], text), text)
            words = st.normalise(text).split(" ")
            self.assertIsNotNone(hit([("c", text)], " ".join(words)), text)
            quoted = hit([("c", text)], '"%s"' % " ".join(words))
            self.assertIsNotNone(quoted, text)
            self.assertEqual(len(quoted["c"]), 1, text)

    def test_real_citation_forms(self):
        self.assertIsNotNone(hit([("c", "Emkay Global [(2018) 9 SCC 49] ; Indus Mobile [(2017) 7 SCC 678 @ paras 2-4 & 19]")], "2018 9 SCC 49"))
        self.assertIsNotNone(hit([("c", "AIR 2026 SC 2041")], "air 2026 sc"))
        self.assertIsNotNone(hit([("c", "Ramdas v Kalawati [2021 SCC OnLine Bom 245 @ para 16]")], '"scc online bom 245"'))
        self.assertIsNone(hit([("c", "Ramdas v Kalawati [2021 SCC OnLine Bom 245 @ para 16]")], '"scc bom"'))
        self.assertIsNotNone(hit([("c", "Tarapore & Co v. Cochin Shipyard [(1984) 2 SCC 680]")], "tarapore & co"))
        self.assertIsNotNone(hit([("c", "Pila Pahan [(2026) 7 SCC 180] @ para 28.1 & 28.16")], '"28 1 & 28 16"'))
        # an en dash is only punctuation
        self.assertIsNotNone(hit([("c", "Totalal vs. The State [AIR 1963 Raj 6] \u2013 Rajasthan HC, 1 judge")], "raj 6 rajasthan"))

    def test_contains_whole_query(self):
        fields = [("a", "(2018) 9 SCC 49"), ("b", "other")]
        self.assertTrue(st.contains_whole_query(fields, st.parse_query("2018 9 scc")))
        self.assertFalse(st.contains_whole_query(fields, st.parse_query("scc 2018")))


class SnippetTests(unittest.TestCase):
    def text(self, segments):
        return "".join(t for t, _ in segments)

    def test_short_text_is_whole_without_ellipsis(self):
        segs = st.snippet("see (2018) 9 SCC 49 here", [(5, 19)])
        self.assertEqual(segs, [("see (", False), ("2018) 9 SCC 49", True), (" here", False)])

    def test_window_and_ellipses(self):
        text = "word " * 100 + "needle" + " word" * 100
        start = text.index("needle")
        segs = st.snippet(text, [(start, start + 6)], width=30)
        self.assertEqual(segs[0], ("\u2026", False))
        self.assertEqual(segs[-1], ("\u2026", False))
        self.assertEqual([t for t, h in segs if h], ["needle"])
        plain = self.text(segs).strip("\u2026")
        self.assertLessEqual(len(plain), 6 + 2 * 30)
        self.assertGreater(len(plain), 6 + 2 * 15)

    def test_cuts_on_word_boundaries(self):
        text = "alpha " * 40 + "needle" + " omega" * 40
        start = text.index("needle")
        segs = st.snippet(text, [(start, start + 6)], width=33)
        middle = self.text(segs).strip("\u2026")
        for word in middle.split():
            self.assertIn(word, ("alpha", "needle", "omega"))

    def test_no_ellipsis_at_start_when_match_is_near_start(self):
        text = "needle " + "x " * 200
        segs = st.snippet(text, [(0, 6)], width=20)
        self.assertEqual(segs[0], ("needle", True))
        self.assertEqual(segs[-1], ("\u2026", False))

    def test_no_spans_shows_beginning(self):
        text = "lorem ipsum " * 50
        segs = st.snippet(text, [], width=20)
        self.assertFalse(any(h for _t, h in segs))
        self.assertEqual(segs[-1], ("\u2026", False))
        self.assertTrue(text.startswith(segs[0][0]))
        self.assertLess(len(self.text(segs)), 60)

    def test_empty_text(self):
        self.assertEqual(st.snippet("", []), [("", False)])

    def test_several_highlights_inside_window(self):
        segs = st.snippet("scc and scc", [(0, 3), (8, 11)])
        self.assertEqual(segs, [("scc", True), (" and ", False), ("scc", True)])

    def test_text_is_not_altered_so_caller_can_escape(self):
        segs = st.snippet("a <b> & c", [(2, 5)])
        self.assertEqual(segs, [("a ", False), ("<b>", True), (" & c", False)])


class SpeedTests(unittest.TestCase):
    def test_five_thousand_records_under_a_second(self):
        rng = random.Random(4)
        words = ["arbitration", "Section", "9", "(2018)", "SCC", "AIR", "Bom", "v.", "State", "of", "&", "agreement",
                 "[2019", "OnLine", "Smith\u2019s", "court", "held", "that", "the", "petition", "is", "maintainable"]
        records = []
        for _ in range(5000):
            body = " ".join(rng.choice(words) for _ in range(40))
            comment = " ".join(rng.choice(words) for _ in range(15))
            records.append([("text", body), ("citation", rng.choice(CITATIONS)), ("comment", comment)])
        terms = st.parse_query("2018 9 scc 49")
        started = time.perf_counter()
        found = sum(1 for fields in records if st.match_fields(fields, terms) is not None)
        elapsed = time.perf_counter() - started
        print("\nsearchtext: 5,000 records (3 fields each) matched in %.3f s (%d hits)" % (elapsed, found))
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()
