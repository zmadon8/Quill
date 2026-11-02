"""Plain unit tests for the alphabetical heading order (diary/sorting.py). No database."""
import random
import unittest
from types import SimpleNamespace

from diary import sorting as s


def ordered(*names):
    return [o.name for o in s.sort_headings(SimpleNamespace(name=n, pk=i) for i, n in enumerate(names, 1))]


def check(test, expected):
    """``expected`` is the right order; any shuffle of it must sort back to it."""
    for seed in range(5):
        shuffled = list(expected)
        random.Random(seed).shuffle(shuffled)
        test.assertEqual(ordered(*shuffled), list(expected))


class NormaliseTests(unittest.TestCase):
    def test_case_ignored(self):
        self.assertEqual(s.normalise("Banks & FINANCIAL"), "banks & financial")

    def test_leading_punctuation_and_space_ignored(self):
        self.assertEqual(s.normalise("  \u2018Court\u2019 "), "court\u2019")
        self.assertEqual(s.normalise('"(Quoted) name'), "quoted) name")
        self.assertEqual(s.normalise("--- dash"), "dash")

    def test_inner_space_collapsed(self):
        self.assertEqual(s.normalise("a   b\tc"), "a b c")

    def test_accents_dropped(self):
        self.assertEqual(s.normalise("R\u00e9sum\u00e9"), "resume")

    def test_empty_and_all_punctuation(self):
        self.assertEqual(s.normalise(""), "")
        self.assertEqual(s.normalise("...!"), "")
        self.assertEqual(s.normalise(None), "")


class OrderTests(unittest.TestCase):
    def test_plain_alphabetical(self):
        check(self, ["Arbitration", "Contracts", "Evidence", "Jurisprudence", "Limitation"])

    def test_capitals_ignored(self):
        self.assertEqual(ordered("banks", "Auction", "BMC Act"), ["Auction", "banks", "BMC Act"])

    def test_numbers_compared_as_numbers(self):
        check(self, ["S. 9", "S. 11", "S. 62", "S. 70", "S. 176"])
        check(self, ["Section 4: Waiver", "Section 7: Arbitration Agreement", "Section 11: Application",
                     "Section 34: Appeal from Award", "Section 36: Enforcement", "Section 45: Power to refer"])

    def test_section_4_before_45(self):
        check(self, ["Section 4", "Section 5", "Section 45", "Section 100"])

    def test_leading_quotes_and_brackets_ignored(self):
        self.assertEqual(ordered("\u2018Court\u2019", "Banks", "(Zed)", "Contract"),
                         ["Banks", "Contract", "\u2018Court\u2019", "(Zed)"])

    def test_clause_numbers(self):
        check(self, ["Section 2", "Section 2(1)", "Section 2(1)(e): \u2018Court\u2019", "Section 2(1)(f)",
                     "Section 2(2)", "Section 2A", "Section 3"])

    def test_numbers_before_letters(self):
        check(self, ["12(5)", "Disclosures", "General"])

    def test_prefix_first(self):
        check(self, ["Section", "Section 1", "Sub-Section 6A"])

    def test_sections_plural_sorts_as_singular(self):
        # Owner round 7: Sections/Orders/Rules sort as Section/Order/Rule, by first number.
        check(self, ["Section 8", "Sections 9 & 17", "Section 10", "Section 11", "Sections 12-14", "Section 45"])
        check(self, ["Order 2 Rule 2", "Orders 3-4", "Order 11 R.12", "Order 13-A"])
        check(self, ["Rule 3A", "Rules 4-5", "Rule 10"])

    def test_plural_only_whole_words_and_key_only(self):
        self.assertEqual(s.normalise("Sections 9 & 17"), "section 9 & 17")
        self.assertEqual(s.normalise("Crosssections"), "crosssections")
        self.assertEqual(ordered("Sections 9", "Section 9"), ["Section 9", "Sections 9"])
        self.assertEqual(ordered("Sections 9")[0], "Sections 9")  # displayed name unchanged

    def test_leading_the_and_re_ignored(self):
        self.assertEqual(s.normalise("The Court"), "court")
        self.assertEqual(s.normalise("Re: Tender"), "tender")
        self.assertEqual(s.normalise("Re Tender"), "tender")
        self.assertEqual(s.normalise("In re Tender"), "in re tender")
        self.assertEqual(s.normalise("Theory"), "theory")
        self.assertEqual(s.normalise("Real"), "real")
        self.assertEqual(ordered("The Zebra", "Apple", "Re: Mango", "Banana"),
                         ["Apple", "Banana", "Re: Mango", "The Zebra"])

    def test_list_marker_ignored(self):
        self.assertEqual(s.normalise("(a): Freedom of Expression"), "freedom of expression")
        self.assertEqual(s.normalise("(iv) Fourth"), "fourth")
        self.assertEqual(s.normalise("[2]. Second"), "second")
        self.assertEqual(s.normalise("(a): The Freedom"), "freedom")
        # Conservative: bare prefixes and ordinary bracketed words are not markers.
        self.assertEqual(s.normalise("a. Thing"), "a. thing")
        self.assertEqual(s.normalise("1. Intro"), "1. intro")
        self.assertEqual(s.normalise("(Quoted) name"), "quoted) name")
        self.assertEqual(s.normalise("(mix) name"), "mix) name")

    def test_real_marker_subtopics(self):
        check(self, ["Equality", "(a): Freedom of Expression", "(g): Freedom of Trade and Commerce", "Liberty"])

    def test_leading_zero_equal_numbers_tie_break_on_name(self):
        self.assertEqual(ordered("S. 09", "S. 9"), ["S. 09", "S. 9"])


class DeterminismTests(unittest.TestCase):
    def test_same_name_different_case_is_stable(self):
        # Real: "Commercial Contracts" and "Commercial contracts" are both Sub-topics in the owner's file.
        a, b = "Commercial Contracts", "Commercial contracts"
        self.assertEqual(ordered(a, b), ordered(b, a))
        self.assertEqual(ordered(a, b), [a, b])

    def test_identical_names_ordered_by_id(self):
        rows = [SimpleNamespace(name="General", pk=pk) for pk in (7, 3, 5)]
        self.assertEqual([r.pk for r in s.sort_headings(rows)], [3, 5, 7])

    def test_name_collision_after_normalisation_uses_full_name_then_id(self):
        rows = [SimpleNamespace(name="\u2018Court\u2019", pk=1), SimpleNamespace(name="Court\u2019", pk=2),
                SimpleNamespace(name="court\u2019", pk=3)]
        # Same normalised name; the full original names then decide ("C" < "c" < the quote mark).
        self.assertEqual([r.pk for r in s.sort_headings(rows)], [2, 3, 1])
        self.assertEqual([r.pk for r in s.sort_headings(reversed(rows))], [2, 3, 1])

    def test_key_is_comparable_for_odd_names(self):
        names = ["", "...", "9", "a", "\u00e9", "\u0663 Arabic digit", "x" * 300, "1" * 40]
        self.assertEqual(len(ordered(*names)), len(names))


class RealNamesTests(unittest.TestCase):
    """Names from the owner's Case Law Diary (collected with the importer plan)."""

    SUBJECTS = ["Administrative Law", "Advocates", "Arguments", "Auction", "Banks & Financial Institutions",
                "BMC Act", "Co-operative Societies", "Companies Act", "Contempt of Court", "Elections",
                "Family Court", "Income Tax", "Insolvency and Bankruptcy Code", "Intellectual Property", "Interest",
                "Land Acquisition", "Money Lenders Act", "MSME Act", "Negotiable Instruments Act", "Partnership Act",
                "Power of Attorney", "Public Premises Act", "Redevelopment", "Registration Act", "SARFAESI Act",
                "School Tribunal", "Slum Act", "Small Causes Court & Rent Act", "Stamp Act", "Tender", "Valuation"]

    def test_other_subjects_sorted(self):
        check(self, self.SUBJECTS)

    def test_arbitration_topics(self):
        check(self, [
            "Section 2(1)(e): \u2018Court\u2019", "Section 4: Waiver", "Section 7: Arbitration Agreement",
            "Section 8: Reference to Arbitration", "Section 11: Application for Appointment of Arbitrator",
            "Section 16: Challenge to Jurisdiction", "Section 19(1): Evidence Act & CPC don't apply",
            "Section 21: Invocation of Arbitration", "Section 29A: Time Limit", "Section 30(2): Award on Agreed Terms",
            "Section 31(6): Interim Award", "Section 31(7): Interest", "Section 34: Appeal from Award",
            "Section 36: Enforcement of Award", "Section 37", "Section 45: Power to refer to arbitration",
        ])

    def test_contract_act_topics(self):
        check(self, ["S. 62: Novation, Assignment", "S. 70: Benefit of non-gratuitous act",
                     "S. 176: Right of Pledgee to sell pledged assets after notice",
                     "Ss. 59-61: Appropriation of debts"])

    def test_specific_relief_subtopics(self):
        check(self, ["Section 10: Mandatory v Discretionary", "Section 14: Determinable Contract", "Section 24",
                     "Section 25(5)", "Section 28 - Rescission of Specific Relief"])

    def test_numbered_subtopics(self):
        check(self, ["12(5)", "Disclosures", "General", "Sec 34(4)", "Section 9", "Section 11", "Section 34",
                     "Section 45", "Stage", "Sub-Section 6A"])
