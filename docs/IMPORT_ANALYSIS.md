
# Import Analysis of "Case Law Diary.docx"

This note explains what is actually inside your Word file, so the import into the Judgment Diary can be planned on facts and not guesses. Every number below was produced by the read-only script `tools/analyze_docx.py` (run `python3 tools/analyze_docx.py` from the project folder to see the same figures). The Word file itself was only read, never changed.

## 1. The short version

- The file has **1,506 paragraphs**. 1,495 carry text and 11 are blank.
- There are **no tables, no images and no footnotes** (the footnote part exists inside the file, but it holds zero real footnotes and nothing in the text points to one). This matches what you told me.
- There are **no "Sections"** anywhere, as you expected.
- The real **Subject count is 41**, which matches your "about 41" (see section 3).
- The structure is regular and can be read reliably from Word's own list formats. About **73% of item lines (693 of 952)** can be split safely into Text and Citation. The other **259 lines** will be imported whole and flagged for your review. Nothing is ever rewritten.

## 2. How the levels are recognised

Word stores every list entry at the same indent depth here (all 1,495 numbered paragraphs say "level 0"), so depth cannot be used. What differs is the **list format** of each paragraph. That is what the importer will use:

| Level in the Diary | Word style | How it is numbered | Count |
|---|---|---|---|
| Subject | Heading 1 | I., II., III. (capital Roman) | 11 headings |
| Topic | Heading 2 | A., B., C. (capital letters) | 209 |
| Sub-topic | List Paragraph | 1., 2., 3. (plain numbers) | 323 |
| Item | List Paragraph | (i), (ii), (iii) (small Roman) | 950 |
| Other (see below) | List Paragraph | (a), (b) (small letters) | 2 |
| Blank lines | Normal | none | 11 |

Total with text: 11 + 209 + 323 + 950 + 2 = 1,495.

What this tells us:

1. **Sub-topics are the "1, 2, 3" lines**, as you said. A Topic that has Sub-topics has exactly one 1-2-3 list (76 Topics do). The other 133 Topics have no Sub-topics, and their Items sit directly under the Topic.
2. **Items are the "(i), (ii), (iii)" lines.** Each group of Items is its own separate Word list (457 of them), so the numbering restarts at (i) under each Sub-topic or Topic. The importer therefore starts a new group of Items whenever the list changes.
3. **There are no Nested Items and no bullets.** All 950 Items are at one single depth. The design still allows Nested Items and bullets for future use, but the first import will create none.
4. In every Topic that has Sub-topics, the Sub-topics come first. No Item sits before the first Sub-topic. No Topic is empty.
5. No Topic name is repeated inside one Subject.

## 3. Subject count: reconciled with "about 41"

- Heading 1 lines in the file: **11** (Arbitration, Contracts, Evidence, Jurisprudence, Limitation, Miscellaneous, Procedure, Transfer of Property, Testamentary, Writ Petitions, Interesting Cases).
- Excluding Miscellaneous: **10** Subjects.
- Topics under Miscellaneous (these become "Other Acts" Subjects): **31**.
- **10 + 31 = 41 Subjects.** Nothing sits directly under "Miscellaneous" itself; it only contains Topics.

So the number you remembered is exactly right. The 31 Other Acts Subjects will be marked "not shown on the landing page" (show_on_landing = No), as in the specification.

## 4. Counts per Subject

### 4.1 The 10 main Subjects

| Subject | Topics | Sub-topics | Items | Other | Blank |
|---|---:|---:|---:|---:|---:|
| Arbitration | 32 | 49 | 157 | 0 | 1 |
| Contracts | 17 | 32 | 93 | 0 | 1 |
| Evidence | 17 | 15 | 50 | 0 | 1 |
| Jurisprudence | 19 | 33 | 112 | 0 | 1 |
| Limitation | 20 | 12 | 64 | 0 | 1 |
| Procedure | 39 | 72 | 202 | 2 | 2 |
| Transfer of Property | 4 | 3 | 7 | 0 | 1 |
| Testamentary | 11 | 0 | 19 | 0 | 1 |
| Writ Petitions | 14 | 10 | 34 | 0 | 1 |
| Interesting Cases | 5 | 0 | 15 | 0 | 0 |
| **Subtotal** | **178** | **226** | **753** | **2** | **10** |

### 4.2 Miscellaneous (31 Topics that become Other Acts Subjects)

Miscellaneous as a whole: 31 Topics, 97 Sub-topics, 197 Items, 1 blank line.

In the new system each of these Topics becomes a Subject, so "Topics" in the table below are what the system will call Sub-topics and Items under that Subject (the Other Acts Subjects have no Topics of their own in the file; their Sub-topics and Items hang directly under the Subject; see Question 1).

| Other Acts Subject | Sub-topics | Items |
|---|---:|---:|
| Administrative Law | 3 | 7 |
| Advocates | 3 | 3 |
| Arguments | 0 | 1 |
| Auction | 3 | 4 |
| Banks & Financial Institutions | 2 | 3 |
| BMC Act | 2 | 6 |
| Co-operative Societies | 4 | 8 |
| Companies Act | 15 | 31 |
| Contempt of Court | 14 | 32 |
| Elections | 1 | 1 |
| Family Court | 1 | 1 |
| Income Tax | 0 | 1 |
| Insolvency and Bankruptcy Code | 14 | 26 |
| Intellectual Property | 1 | 2 |
| Interest | 3 | 8 |
| Land Acquisition | 2 | 2 |
| Money Lenders Act | 0 | 2 |
| MSME Act | 2 | 4 |
| Negotiable Instruments Act | 0 | 3 |
| Partnership Act | 5 | 6 |
| Power of Attorney | 0 | 2 |
| Public Premises Act | 0 | 1 |
| Redevelopment | 5 | 5 |
| Registration Act | 0 | 4 |
| SARFAESI Act | 6 | 12 |
| School Tribunal | 0 | 2 |
| Slum Act | 0 | 1 |
| Small Causes Court & Rent Act | 4 | 6 |
| Stamp Act | 3 | 4 |
| Tender | 2 | 7 |
| Valuation | 2 | 2 |
| **Total** | **97** | **197** |

Grand totals across the file: 41 Subjects, 178 Topics under the 10 main Subjects, 323 Sub-topics, 950 Items, 2 "(a)/(b)" lines.

## 5. Messy patterns found, with counts, examples and proposed rules

The golden rules for the importer:

1. **Never rewrite or correct anything.** Every paragraph is saved exactly as it appears in the file in a field called `original_line`. This includes odd spacing, curly quotes and typos.
2. **Split a line into Text and Citation only when it is unambiguous.**
3. **Anything doubtful is imported whole**, marked `needs_review = Yes`, with a short `review_note` saying why. You can then fix it in the screen at your own pace.

Counts below are numbers of Item lines (952 lines = the 950 "(i)" Items plus the 2 "(a)/(b)" lines). A line can fall under more than one pattern, so the counts overlap.

| # | Pattern | Count | Verbatim example | Proposed rule |
|---|---|---:|---|---|
| 1 | Several citations in one line, marked (i), (ii) | 38 | `Leave & License not arbitrable - (i) Central Warehousing Corp. v Fortpoint Automotive [(2010) 1 MahLJ 658(FB)] ; (ii) Bafna Motors [2022 SCC OnLine Bom 994]` | Import whole, needs_review. Note: "(i)" typed inside the line, not a Word list entry. |
| 2 | Unbalanced brackets (an opening `[` or `(` without its closing one, or the reverse) | 49 | `Limited scope - Goqii Technologies [(2025) 2 SCC 192` and `Arbitrator can implead third parties - (i) Cardinal (Bom HC, Chagla], (ii) ASF Buildtech [2025 SCC OnLine SC 1016]` | Import whole, needs_review, note "brackets do not match". |
| 3 | More than one " - " in a line | 85 | `Incorporation of arbitration agreement by reference - General reference to an earlier contract insufficient, but to a standard form of contract sufficient. Purchase Order - Inox Wind [(2018) 2 SCC 519 @ para 18]` | Import whole, needs_review. We cannot tell which dash separates Text from Citation. |
| 4 | No " - " at all | 78 | `Associate Builders` and `Incorporation by reference to standard form agreement - (2019) 5 SCC 192` (the second has a dash but no `[ ]` brackets, so it falls under pattern 12) | Lines with no dash are imported whole, needs_review. Often these are only a case name, or only a citation. |
| 5 | Whole line inside square brackets (a remark) | 2 | `[Question of whether 2 Indian parties can contract out of Part I of Arbitration Act not decided in Sasan Power [(2016) 10 SCC 813]]` and `[(2019) SCC OnLine Bom 1244]` | Import whole, needs_review, note "whole line is a bracketed remark". The brackets stay. |
| 6 | Inline flag `[NO LONGER GOOD LAW]` | 1 | `Issue of Limitation of the claim can be decided by the arbitrator, though court can decide when clearly barred by limitation - BSNL v. Nortel Networks (2021) 5 SCC 738 @ paras 40-47 & 53 [NO LONGER GOOD LAW]` | Preserved exactly, as it sits in the line. The importer never removes it. Import whole with needs_review, note "contains a flag". Later the system can offer a proper "No longer good law" marker, but the original text stays. No other capital-letter flags exist. |
| 7 | Heading-like lines ending in a colon | 0 among Items; **6 Topics** and **13 Sub-topics** end in a colon | Topic: `Non-signatories / 3rd Parties:` | Keep the colon exactly as typed; it is only part of the name. No review needed. |
| 8 | Sub-topics that contain " - " or an unbalanced bracket | 18 contain " - " (31 Sub-topics in all need a look) | (shown in the Sub-topic list when the script is run) | Import the Sub-topic name whole; needs_review. A Sub-topic is a heading and is never split. |
| 9 | Semicolon between citations | 142 lines have a semicolon (many are normal sentence punctuation) | `Exclusive Jurisdiction clause must be honoured - Emkay Global [(2018) 9 SCC 49] ; Indus Mobile [(2017) 7 SCC 678 @ paras 2-4 & 19]` | A single dash plus balanced brackets is still split at the dash; the whole right-hand side, with all its citations, becomes the Citation. Semicolons are not split in the first version. |
| 10 | Curly quotes | 26 | `Can’t bind non-signatory without establishing his intention to consent - Reckitt Benckiser [(2019) 7 SCC 62]` | Stored as is. Straight quotes (46 lines) are also left as is. Searching will treat both kinds as equal so you find either. |
| 11 | Ampersands (&) | 105 | `L&T Finance Ltd v. Manoj Pathak [2020 SCC OnLine 177]` | Stored as is. The pages must display "&" correctly (a normal Django concern). |
| 12 | Right side after the dash does not look like a citation | 26 | `Mahyco Monsanto v. Nuziveedu Seeds [Bom HC - Comm Arb Pet No. 312 of 2019]` | Import whole, needs_review. (This one also hides a second dash inside the bracket.) |
| 13 | Double spaces | 16 | `... [(2018) 15 SCC 678]  ; (iii) Rashid Raza ...` | Kept exactly. A line with double spaces is not auto-split (6 lines are held back only for this reason). |
| 14 | Leading or trailing spaces | 1 | the long `Cannot dismiss a Suit when a party erred...` line | Kept in original_line; imported whole. |
| 15 | Very long lines (over 400 characters) | 12 | `Attachment before judgment in S. 9 - Essar House [(2022) 20 SCC 178] Nimbus Communications ...` | Import whole, needs_review (long, several citations, likely mixed content). |
| 16 | Very short lines (under 12 characters) | 1 | `NN Global` | Import whole, needs_review. |
| 17 | Blank paragraphs | 11 | none to show | Skipped. They carry no text. They are listed in the report so nothing is lost silently. |
| 18 | A Sub-topic directly after a Sub-topic (no Items between) | 2 | `Without Reasons` (under `Leaving question of Law Open`) and `Solicitors` (under `Professional Liability`) | Imported as two Sub-topics in order; flagged for review because it may be a two-line heading. |
| 19 | A group of Items that restarts inside the same Topic or Sub-topic | 3 | e.g. under `Unlawful Subletting / Eviction` | Document order is kept. The Items stay under the same parent; needs_review note "list restarted". |
| 20 | "(a)", "(b)" lines sitting between a "1." Sub-topic and its Items | 2 | `Ex Parte / Without Notice` and `Determining Jurisdiction` (under `Clause 12: Leave to Sue`, Topic `Letters Patent & OS Rules`) | See Question 3. Until you decide, they are imported as Sub-topics with needs_review. |

Not found at all: Sections, bullets, nested Items, tables, images, footnotes, headings with their own sub-numbering, Heading 2 lines without numbering, and Items deeper than level 0.

### The rule for splitting Text and Citation

An Item line is split into **Text** (before the dash) and **Citation** (after it) only when ALL of these hold:

- there is exactly one " - " in the line;
- both sides are non-empty;
- square and round brackets balance;
- there is no typed "(ii)" marker and no bracketed remark or flag;
- no double spaces and no leading or trailing spaces;
- the right-hand side contains a bracketed citation or something that clearly looks like a year and report name.

Result on your file: **693 lines split cleanly, 259 imported whole with needs_review = Yes.** The 259 break down (a line can have several reasons; the first matching reason is counted):

| Reason | Lines |
|---|---:|
| No " - " separator | 72 |
| More than one " - " | 70 |
| Unbalanced brackets | 49 |
| Several citations marked (i), (ii) | 32 |
| Right side does not look like a citation | 26 |
| Double spaces | 6 |
| Whole line in brackets | 2 |
| Carries a flag | 1 |
| Leading or trailing spaces | 1 |

The review screen would let you correct these one at a time, or sort them by reason. Reviewing about 260 lines is a manageable job, and the application stays fully usable while you do it.

## 6. How the import will be checked

**Dry run.** Before anything is saved, the importer produces a preview file (and an on-screen page). It lists, without touching the database: the 41 Subjects, how many Topics, Sub-topics and Items each has, how many lines are clean, how many need review (with the reason), and the first few lines of each Topic so you can see that it looks right. You approve, and only then is the real import done. Running the import twice does not create duplicates.

**Reconciliation report.** After the import, a report confirms nothing was lost or invented:

1. Counts per level per Subject from the file against the counts in the database. They must match exactly (for example, 41 Subjects, 178 + 0 Topics under main Subjects, 323 Sub-topics, 950 Items and 2 "(a)/(b)" lines, 1,495 text paragraphs).
2. A **full-text comparison**: all text is rebuilt from the database in the original order and compared line by line with the Word file. Any difference is listed. The target is zero differences.
3. A list of every line flagged needs_review with its reason.

## 7. Questions for the owner

1. **Other Acts Subjects and Topics.** In Miscellaneous the file has Topic, then Sub-topic, then Items. When a Topic becomes an Other Acts Subject, it has no Topic level left. Should the Sub-topics (the 1, 2, 3 lines) of an Other Act appear directly under that Act, with Items directly under the Act when there is no Sub-topic (for example Income Tax has 0 Sub-topics and 1 Item)? This is how I plan it, unless you want a single default Topic named "General" under each Act. [Answer: Yes]
2. **Lines that are only a case name or only a citation** (for example `Associate Builders`, or `Incorporation by reference to standard form agreement - (2019) 5 SCC 192`). Are these a "Text with no Citation" and a "Citation with no Text", or are they unfinished notes you want to look at one by one? I have assumed the second and flagged them. [Answer: When in doubt, put as 'Text with no Citation', and flag for my later review]
3. **The two "(a)/(b)" lines** (`Ex Parte / Without Notice`, `Determining Jurisdiction`). They look like small headings inside Sub-topic "Clause 12: Leave to Sue", with Items under each. Should they become Sub-topics of their own, or a lower heading inside that Sub-topic? There are only 2, so I can also leave them as flagged Sub-topics. [Answer: These should be Sections]
4. **Lines with several citations marked (i), (ii).** There are 38. Do you want the system to keep them as one Item with the long citation (my plan for now), or later split each (i), (ii) into separate Items? [Answer: Keep them as one long citation, and flag for review]
5. **"[NO LONGER GOOD LAW]".** Only one line has it. Should future versions show it as a coloured badge (while the original wording stays in the text)? Are there other flags you use or plan to use? [Answer: I do not need any coloured badge. Keep the wording in the text.]
6. **Search wording.** Should a search treat straight and curly quotes as the same, and "&" and "and" as the same? I propose yes for quotes and no for "&". [Answer: Ok]
7. **Blank paragraphs.** The 11 blank lines are to be skipped. Please confirm they hold no meaning (for example marking the end of a group). [Answer: Ok]
8. **Sub-topics that end in a colon** (13) and **Topics that end in a colon** (6). I keep the colon exactly. Is that acceptable? [Answer: Remove the colons]
9. **Two Sub-topics in a row** (`Leaving question of Law Open` / `Without Reasons`, and `Professional Liability` / `Solicitors`). Are these two separate Sub-topics, or one heading broken over two lines? [Answer: These are separate sub-topics, some of which may not have any items at present]
