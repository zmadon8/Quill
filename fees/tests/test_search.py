"""Global search read-service tests for the Fee Register (T3.5, R-RD-7, brief 6.8).

Fresh Django tests for ``fees.services.search.search`` (the reference TS has no
search test; flows.test.ts covers none). They cover: a query under two
characters returns nothing; firm / matter / memo matches carry the right kind,
title and subtitle; firms come before matters come before memos; the overall
limit of twenty; a memo matched by a party name (plaintiff / defendant /
client); a draft memo titled "(draft)"; memo ordering by financial year then
seq descending; profile isolation; and the Q6 wildcard escaping (a literal "%"
or "_" in the data is matched literally and a "%" or "_" in the query does NOT
behave as a wildcard). A query-count bound (three queries) guards against an
N+1 regression.

Everything is scoped to a ``Profile(program="fees")``. Firms / matters are
seeded directly; memos are created via ``memos.create_memo`` which copies the
party-name snapshot fields (plaintiff_name / defendant_name / client) from its
input, mirroring ``test_outstanding.py`` / ``test_ledger.py``.
"""
from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import Firm, Group, Matter
from fees.services import memos, search


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def seed_firm(profile, firm_name="Firm", group_name="P"):
    firm = Firm.objects.create(profile=profile, name=firm_name)
    group = Group.objects.create(profile=profile, firm=firm, name=group_name)
    return firm, group


def seed_matter(profile, firm, group, matter_name="Matter"):
    return Matter.objects.create(
        profile=profile, firm=firm, group=group, name=matter_name
    )


def make_memo(profile, matter, date="2026-07-15", **parties):
    data = dict(
        date=date,
        matter_id=matter.pk,
        addressee_line1="A",
        num_appearances=0,
        fees_per_appearance=0,
        num_conferences=0,
        fees_per_conference=0,
        fees_misc_drafting=100,
    )
    data.update(parties)
    return memos.create_memo(profile, data)


class SearchQueryLengthTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        seed_firm(self.profile, "Acme Legal")

    def test_blank_query_returns_empty(self):
        self.assertEqual(search.search(self.profile, ""), [])
        self.assertEqual(search.search(self.profile, "   "), [])

    def test_single_character_returns_empty(self):
        # "A" matches "Acme Legal" as a substring but is under two characters.
        self.assertEqual(search.search(self.profile, "A"), [])
        self.assertEqual(search.search(self.profile, " a "), [])

    def test_two_characters_searches(self):
        results = search.search(self.profile, "Ac")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], "firm")


class SearchResultShapeTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm, self.group = seed_firm(self.profile, "Zenith Partners")
        self.matter = seed_matter(
            self.profile, self.firm, self.group, "Zenith v State"
        )

    def test_firm_match_shape(self):
        results = search.search(self.profile, "Zenith Partners")
        firm = next(r for r in results if r["kind"] == "firm")
        self.assertEqual(firm["id"], self.firm.pk)
        self.assertEqual(firm["title"], "Zenith Partners")
        self.assertEqual(firm["subtitle"], "Firm")

    def test_matter_match_shape_includes_firm_name(self):
        results = search.search(self.profile, "Zenith v State")
        matter = next(r for r in results if r["kind"] == "matter")
        self.assertEqual(matter["id"], self.matter.pk)
        self.assertEqual(matter["title"], "Zenith v State")
        self.assertEqual(matter["subtitle"], "Matter \u00b7 Zenith Partners")

    def test_memo_match_shape_includes_matter_and_firm(self):
        memo = make_memo(self.profile, self.matter)
        results = search.search(self.profile, memo.memo_number)
        row = next(r for r in results if r["kind"] == "memo")
        self.assertEqual(row["id"], memo.pk)
        self.assertEqual(row["title"], memo.memo_number)
        self.assertEqual(
            row["subtitle"], "Memo \u00b7 Zenith v State \u00b7 Zenith Partners"
        )

    def test_case_insensitive(self):
        results = search.search(self.profile, "zenith partners")
        self.assertTrue(any(r["kind"] == "firm" for r in results))


class SearchRankingTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        # All three kinds share the token "Match" so one query hits each.
        self.firm, self.group = seed_firm(self.profile, "Match Firm")
        self.matter = seed_matter(
            self.profile, self.firm, self.group, "Match Matter"
        )

    def test_firms_before_matters_before_memos(self):
        make_memo(self.profile, self.matter, client="Match Client")
        results = search.search(self.profile, "Match")
        kinds = [r["kind"] for r in results]
        self.assertEqual(kinds, ["firm", "matter", "memo"])

    def test_memo_matched_by_party_names(self):
        p = make_memo(self.profile, self.matter, plaintiff_name="Match Plaintiff")
        d = make_memo(self.profile, self.matter, defendant_name="Match Defendant")
        c = make_memo(self.profile, self.matter, client="Match Client")
        results = search.search(self.profile, "Match")
        memo_ids = {r["id"] for r in results if r["kind"] == "memo"}
        self.assertEqual(memo_ids, {p.pk, d.pk, c.pk})

    def test_draft_memo_titled_draft(self):
        draft = memos.create_memo(
            self.profile,
            dict(
                date="2026-07-15",
                matter_id=self.matter.pk,
                addressee_line1="A",
                num_appearances=0,
                fees_per_appearance=0,
                num_conferences=0,
                fees_per_conference=0,
                fees_misc_drafting=100,
                client="Match Client",
            ),
            is_draft=True,
        )
        results = search.search(self.profile, "Match")
        row = next(r for r in results if r["kind"] == "memo" and r["id"] == draft.pk)
        self.assertIsNone(draft.memo_number)
        self.assertEqual(row["title"], "(draft)")

    def test_memos_ordered_by_fy_then_seq_desc(self):
        older = make_memo(self.profile, self.matter, date="2024-07-15",
                          client="Match A")
        newer = make_memo(self.profile, self.matter, date="2026-07-15",
                          client="Match B")
        # A later seq in the same (newest) FY must sort first.
        newest_seq = make_memo(self.profile, self.matter, date="2026-08-15",
                               client="Match C")
        results = search.search(self.profile, "Match")
        memo_ids = [r["id"] for r in results if r["kind"] == "memo"]
        self.assertEqual(memo_ids, [newest_seq.pk, newer.pk, older.pk])


class SearchLimitTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_overall_limit_of_twenty(self):
        for i in range(25):
            seed_firm(self.profile, f"Match Firm {i:02d}", group_name=f"G{i}")
        results = search.search(self.profile, "Match")
        self.assertEqual(len(results), 20)
        self.assertTrue(all(r["kind"] == "firm" for r in results))

    def test_custom_limit(self):
        for i in range(5):
            seed_firm(self.profile, f"Match Firm {i:02d}", group_name=f"G{i}")
        results = search.search(self.profile, "Match", limit=3)
        self.assertEqual(len(results), 3)


class SearchIsolationTests(TestCase):
    def test_other_profile_rows_never_appear(self):
        mine = fees_profile("Mine-Fees")
        other = fees_profile("Other-Fees")
        f_mine, g_mine = seed_firm(mine, "Shared Name")
        f_other, g_other = seed_firm(other, "Shared Name")
        m_other = seed_matter(other, f_other, g_other, "Shared Matter")
        make_memo(other, m_other, client="Shared Client")

        results = search.search(mine, "Shared")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], f_mine.pk)
        self.assertEqual(results[0]["kind"], "firm")


class SearchWildcardEscapingTests(TestCase):
    """Q6: ``%`` and ``_`` in the query are matched literally, not as wildcards."""

    def setUp(self):
        self.profile = fees_profile()

    def test_percent_is_literal_not_wildcard(self):
        _firm, _group = seed_firm(self.profile, "50% Off Legal", group_name="GA")
        seed_firm(self.profile, "5000 Legal", group_name="GB")
        results = search.search(self.profile, "50%")
        names = {r["title"] for r in results}
        # A literal percent matches the firm that actually contains "50%" and
        # does NOT behave as a wildcard matching "5000 Legal".
        self.assertEqual(names, {"50% Off Legal"})

    def test_underscore_is_literal_not_wildcard(self):
        seed_firm(self.profile, "a_b Chambers", group_name="GA")
        seed_firm(self.profile, "axb Chambers", group_name="GB")
        results = search.search(self.profile, "a_b")
        names = {r["title"] for r in results}
        # A literal underscore must not match the single wildcard "x".
        self.assertEqual(names, {"a_b Chambers"})

    def test_bare_percent_query_matches_nothing_without_literal(self):
        seed_firm(self.profile, "Plain Firm", group_name="GA")
        # "%%" is two characters so it searches, but as literal percents it
        # matches no firm (none contain a percent sign).
        results = search.search(self.profile, "%%")
        self.assertEqual(results, [])


class SearchQueryCountTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm, self.group = seed_firm(self.profile, "Match Firm")
        self.matter = seed_matter(
            self.profile, self.firm, self.group, "Match Matter"
        )

    def test_three_queries(self):
        for i in range(5):
            make_memo(self.profile, self.matter, date=f"2026-0{i + 1}-15",
                      client="Match Client")
        # One query each for firms, matters and memos; select_related means the
        # matter / firm names cost no per-row query.
        with self.assertNumQueries(3):
            results = search.search(self.profile, "Match")
            self.assertTrue(len(results) >= 3)
