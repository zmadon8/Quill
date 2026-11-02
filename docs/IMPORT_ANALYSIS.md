
# Import Analysis of "Case Law Diary.docx"

This note explains what is actually inside your Word file, so the import into the Judgment Diary (into one chosen profile, `docs/DESIGN.md` section 3.5) can be planned on facts and not guesses. Every number below was produced by the read-only script `tools/analyze_docx.py` (run `python3 tools/analyze_docx.py` from the project folder to see the same figures). The Word file itself was only read, never changed.

## 1. The short version

- The file has **1,506 paragraphs**. 1,495 carry text and 11 are blank.
- There are **no tables, no images and no footnotes** (the footnote part exists inside the file, but it holds zero real footnotes and nothing in the text points to one). This matches what you told me.
- There are **2 lines that become "Sections"**: the small-letter (a)/(b) lines `Ex Parte / Without Notice` and `Determining Jurisdiction` (your decision, section 7, I3), flagged for review (I10). They are numbered with their own Section format (default (a), (b)) and restart the Item numbering (D9, D13). There are no other Sections.
- The real **Subject count is 41**, which matches your "about 41" (see section 3).
- The structure is regular and can be read reliably from Word's own list formats. About **73% of the 950 Item lines (693 of 950)** can be split safely into Text and Citation. The other **257 lines** will be imported whole, as Text with no Citation, and flagged for your review. Two of the 693 split lines are also flagged because Word's list restarts there (pattern 19), so **259 Items** are flagged and 691 are clean. The 2 Sections are also flagged for your review, so **261 records** (259 Items + 2 Sections) carry a review marker after import. Nothing is ever rewritten.

## 2. How the levels are recognised

Word stores every list entry at the same indent depth here (all 1,495 numbered paragraphs say "level 0"), so depth cannot be used. What differs is the **list format** of each paragraph. That is what the importer will use:

| Level in the Diary | Word style | How it is numbered | Count |
|---|---|---|---|
| Subject | Heading 1 | I., II., III. (capital Roman) | 11 headings |
| Topic | Heading 2 | A., B., C. (capital letters) | 209 |
| Sub-topic | List Paragraph | 1., 2., 3. (plain numbers) | 323 |
| Item | List Paragraph | (i), (ii), (iii) (small Roman) | 950 |
| Section | List Paragraph | (a), (b) (small letters) | 2 |
| Blank lines | Normal | none | 11 |

Total with text: 11 + 209 + 323 + 950 + 2 = 1,495. (The 209 Heading 2 lines are 178 Topics of the main Subjects plus 31 Other Subjects, which become Subjects.)

What this tells us:

1. **Sub-topics are the "1, 2, 3" lines**, as you said. A Topic that has Sub-topics has exactly one 1-2-3 list (76 Topics do). The other 133 Topics have no Sub-topics, and their Items sit directly under the Topic.
2. **Items are the "(i), (ii), (iii)" lines.** Each group of Items is its own separate Word list (457 of them), so the numbering restarts at (i) under each Sub-topic or Topic. The importer therefore starts a new group of Items whenever the list changes.
3. **There are no Nested Items and no bullets.** All 950 Items are at one single depth. The design still allows Nested Items and bullets for future use, but the first import will create none.
4. In every Topic that has Sub-topics, the Sub-topics come first. No Item sits before the first Sub-topic. No Topic is empty.
5. No Topic name is repeated inside one Subject.

## 3. Subject count: reconciled with "about 41"

- Heading 1 lines in the file: **11** (Arbitration, Contracts, Evidence, Jurisprudence, Limitation, Miscellaneous, Procedure, Transfer of Property, Testamentary, Writ Petitions, Interesting Cases).
- Excluding Miscellaneous: **10** Subjects.
- Topics under Miscellaneous (these become "Other Subjects" Subjects): **31**.
- **10 + 31 = 41 Subjects.** Nothing sits directly under "Miscellaneous" itself; it only contains Topics.

So the number you remembered is exactly right. The 31 Other Subjects will be marked "not shown on the landing page" (show_on_landing = No), as in the specification.

## 4. Counts per Subject

### 4.1 The 10 main Subjects

| Subject | Topics | Sub-topics | Items | Sections | Blank |
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

### 4.2 Miscellaneous (31 Topics that become Other Subjects)

Miscellaneous as a whole: 31 Topics, 97 Sub-topics, 197 Items, 1 blank line.

In the new system each of these Topics becomes a Subject, so "Topics" in the table below are what the system will call Sub-topics and Items under that Subject (the Other Subjects have no Topics of their own in the file; their Sub-topics and Items hang directly under the Subject; see Question 1).

| Other Subject | Sub-topics | Items |
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

Grand totals across the file (these are the reconciliation targets): 41 Subjects, 178 Topics under the 10 main Subjects, 323 Sub-topics, 950 Items, 2 Sections, 1,495 text paragraphs, 11 blanks skipped.

## 5. Messy patterns found, with counts, examples and proposed rules

The golden rules for the importer:

1. **Never rewrite or correct anything.** Every paragraph is saved exactly as it appears in the file in a field called `original_line`. This includes odd spacing, curly quotes and typos. The one exception, on your instruction (I8), is that the 19 trailing colons on Topic and Sub-topic names are not stored in the name; the original line still has them, and every case is reported.
2. **Split a line into Text and Citation only when it is unambiguous.**
3. **Anything doubtful is imported whole**, marked `needs_review = Yes`, with a short `review_note` saying why. You can then fix it in the screen at your own pace.

Counts below were produced by the script over 952 lines, which is the 950 "(i)" Items plus the 2 "(a)/(b)" lines. Because the 2 "(a)/(b)" lines are now Sections, they are not Items and are no longer counted as Item lines; where they affected a count, the corrected figure is given. A line can fall under more than one pattern, so the counts overlap.

| # | Pattern | Count | Verbatim example | Proposed rule |
|---|---|---:|---|---|
| 1 | Several citations in one line, marked (i), (ii) | 38 | `Leave & License not arbitrable - (i) Central Warehousing Corp. v Fortpoint Automotive [(2010) 1 MahLJ 658(FB)] ; (ii) Bafna Motors [2022 SCC OnLine Bom 994]` | Import whole as one long Citation or Text as the split rule decides (decided, I4), needs_review. Note: "(i)" typed inside the line, not a Word list entry. |
| 2 | Unbalanced brackets (an opening `[` or `(` without its closing one, or the reverse) | 49 | `Limited scope - Goqii Technologies [(2025) 2 SCC 192` and `Arbitrator can implead third parties - (i) Cardinal (Bom HC, Chagla], (ii) ASF Buildtech [2025 SCC OnLine SC 1016]` | Import whole, needs_review, note "brackets do not match". |
| 3 | More than one " - " in a line | 85 | `Incorporation of arbitration agreement by reference - General reference to an earlier contract insufficient, but to a standard form of contract sufficient. Purchase Order - Inox Wind [(2018) 2 SCC 519 @ para 18]` | Import whole, needs_review. We cannot tell which dash separates Text from Citation. |
| 4 | No " - " at all | 76 (78 in the script, minus the 2 Sections) | `Associate Builders` and `Incorporation by reference to standard form agreement - (2019) 5 SCC 192` (the second has a dash but no `[ ]` brackets, so it falls under pattern 12) | Decided (I2): in doubt, store the whole line as **Text with no Citation** and mark needs_review. Often these are only a case name, or only a citation. |
| 5 | Whole line inside square brackets (a remark) | 2 | `[Question of whether 2 Indian parties can contract out of Part I of Arbitration Act not decided in Sasan Power [(2016) 10 SCC 813]]` and `[(2019) SCC OnLine Bom 1244]` | Import whole, needs_review, note "whole line is a bracketed remark". The brackets stay. |
| 6 | Inline flag `[NO LONGER GOOD LAW]` | 1 | `Issue of Limitation of the claim can be decided by the arbitrator, though court can decide when clearly barred by limitation - BSNL v. Nortel Networks (2021) 5 SCC 738 @ paras 40-47 & 53 [NO LONGER GOOD LAW]` | Preserved exactly, as it sits in the line. The importer never removes it. Import whole with needs_review, note "contains a flag". Decided (I5): no coloured badge is wanted; the wording stays in the text. No other capital-letter flags exist. |
| 7 | Heading-like lines ending in a colon | 0 among Items; **6 Topics** and **13 Sub-topics** end in a colon | Topic: `Non-signatories / 3rd Parties:` | **Decided (I8): remove the trailing colon.** The stored name has no colon; the exact Word text stays in `original_line`; all 19 changes (6 + 13) are listed in the reconciliation report. This is a deliberate, reported exception to "never alter". No review needed. |
| 8 | Sub-topics that contain " - " or an unbalanced bracket | 18 contain " - " (the script's figure of 31 Sub-topics "needing a look" also counts the 13 colon endings, which are now handled by the colon rule) | (shown in the Sub-topic list when the script is run) | Import the Sub-topic name whole; needs_review. A Sub-topic is a heading and is never split. |
| 9 | Semicolon between citations | 142 lines have a semicolon (many are normal sentence punctuation) | `Exclusive Jurisdiction clause must be honoured - Emkay Global [(2018) 9 SCC 49] ; Indus Mobile [(2017) 7 SCC 678 @ paras 2-4 & 19]` | A single dash plus balanced brackets is still split at the dash; the whole right-hand side, with all its citations, becomes the Citation. Semicolons are not split in the first version. |
| 10 | Curly quotes | 26 | `Can’t bind non-signatory without establishing his intention to consent - Reckitt Benckiser [(2019) 7 SCC 62]` | Stored as is. Straight quotes (46 lines) are also left as is. Searching will treat both kinds as equal so you find either. |
| 11 | Ampersands (&) | 105 | `L&T Finance Ltd v. Manoj Pathak [2020 SCC OnLine 177]` | Stored as is. The pages must display "&" correctly (a normal Django concern). |
| 12 | Right side after the dash does not look like a citation | 26 | `Mahyco Monsanto v. Nuziveedu Seeds [Bom HC - Comm Arb Pet No. 312 of 2019]` | Import whole, needs_review. (This one also hides a second dash inside the bracket.) |
| 13 | Double spaces | 16 | `... [(2018) 15 SCC 678]  ; (iii) Rashid Raza ...` | Kept exactly. A line with double spaces is not auto-split (6 lines are held back only for this reason). |
| 14 | Leading or trailing spaces | 1 | the long `Cannot dismiss a Suit when a party erred...` line | Kept in original_line; imported whole. |
| 15 | Very long lines (over 400 characters) | 12 | `Attachment before judgment in S. 9 - Essar House [(2022) 20 SCC 178] Nimbus Communications ...` | Import whole, needs_review (long, several citations, likely mixed content). |
| 16 | Very short lines (under 12 characters) | 1 | `NN Global` | Import whole, needs_review. |
| 17 | Blank paragraphs | 11 | none to show | Skipped. They carry no text. They are listed in the report so nothing is lost silently. |
| 18 | A Sub-topic directly after a Sub-topic (no Items between) | 2 | `Without Reasons` (under `Leaving question of Law Open`) and `Solicitors` (under `Professional Liability`) | Decided (I9): two separate Sub-topics in order. Not flagged; a Sub-topic may have no Items at present. |
| 19 | A group of Items that restarts inside the same Topic or Sub-topic | 3 | e.g. under `Unlawful Subletting / Eviction` | Document order is kept. The Items stay under the same parent. **Built as:** the importer finds 2 such restarts (`para-1033` and `para-1356`; the third in the script's count is the normal restart after Section (b)). They are **flagged** `needs_review = Yes` with the note "Word list restarted here; the Diary numbers this group continuously.", as originally agreed (default D-a, pending your confirmation). This takes the totals to 259 flagged Items and 261 review-marked records. |
| 20 | "(a)", "(b)" lines sitting between a "1." Sub-topic and its Items | 2 | `Ex Parte / Without Notice` and `Determining Jurisdiction` (under `Clause 12: Leave to Sue`, Topic `Letters Patent & OS Rules`) | Decided (I3, I10): imported as **Sections** (not Sub-topics, not counted as Items), flagged for review. See section 5.1 for how Items after them are numbered. |

Not found at all: any other Sections, bullets, nested Items, tables, images, footnotes, headings with their own sub-numbering, Heading 2 lines without numbering, and Items deeper than level 0.

### The rule for splitting Text and Citation

An Item line is split into **Text** (before the dash) and **Citation** (after it) only when ALL of these hold:

- there is exactly one " - " in the line;
- both sides are non-empty;
- square and round brackets balance;
- there is no typed "(ii)" marker and no bracketed remark or flag;
- no double spaces and no leading or trailing spaces;
- the right-hand side contains a bracketed citation or something that clearly looks like a year and report name.

Result on your file: **693 Items split cleanly, 257 imported whole (as Text with no Citation) with needs_review = Yes; 2 of the 693 are also flagged for a Word list restart (pattern 19), so 691 are clean and 259 flagged.** (The script reported 259 of 952 lines; the 2 extra are the (a)/(b) lines, which are now Sections.) The per-reason table below covers the **257 whole-line Items**, then adds the 2 list restarts. The 2 Sections are flagged separately (reason: imported from a small-letter (a)/(b) list; confirm these are Sections), which makes **261 review-marked records in all** (259 Items + 2 Sections). The 257 break down (a line can have several reasons; the first matching reason is counted):

| Reason | Lines |
|---|---:|
| No " - " separator | 70 |
| More than one " - " | 70 |
| Unbalanced brackets | 49 |
| Several citations marked (i), (ii) | 32 |
| Right side does not look like a citation | 26 |
| Double spaces | 6 |
| Whole line in brackets | 2 |
| Carries a flag | 1 |
| Leading or trailing spaces | 1 |
| **Total imported whole (Items)** | **257** |
| Split Items flagged because Word's list restarted (pattern 19, `para-1033`, `para-1356`) | 2 |
| **Flagged Items** | **259** |
| Sections flagged (separate from the Items above) | 2 |
| **All review-marked records at import** | **261** |
| Split Items whose Citation had bold/underline in Word (flagged, default D-c) | 0 |

**Update (round 6, 10d: Multi-Items are merged into Items).** Every Item now holds its citations as Cases. A line that splits cleanly at its single " - " gives the Item text plus one Case (a) holding the citation; on the real file that is **693 Cases** (691 clean lines plus 2 flagged list-restart lines that are still split), and the 257 whole-line Items get no Case. The 32 typed (i), (ii) lines are unchanged: still imported whole, with no Case, flagged for review. The other figures are unchanged (41 Subjects, 178 Topics, 323 Sub-topics, 2 Sections, 950 Items of which 691 clean and 259 flagged, 261 marked for review). The reconciliation report has a new row "Citations (Cases, one per split line)".

Every one of these lines is stored whole in the Text field with an empty Citation, so no characters are moved or lost. The review screen would let you correct these one at a time, or sort them by reason. Reviewing about 260 lines is a manageable job, and the application stays fully usable while you do it.

### 5.1 Sections and the numbering of the Items after them

The file has this shape (Topic `Letters Patent & OS Rules`, Sub-topic `Clause 12: Leave to Sue`):

```
1. Clause 12: Leave to Sue          (Sub-topic)
   (a) Ex Parte / Without Notice    (Word list: small letters)
       (i)  Ordinarily ex parte ...         (Word list A)
       (ii) No need for prior notice ...
   (b) Determining Jurisdiction
       (i)  Must assume that the assertions ...   (a different Word list, B: restarts at (i))
       ... 10 Items in all
```

That is 2 Sections and 12 Items (2 under the first Section, 10 under the second; an earlier version of this note said 8, which the importer found to be wrong), with no Item before the first Section.

How the importer builds it: the two small-letter lines become **Sections**; they are not counted as Items and not Sub-topics. A Section has no children, so it sits in the Sub-topic's shared order, at the position where it appears, and the Items that follow it (until the next Section, Sub-topic or Topic) are ordinary Items of the same Sub-topic placed after it. Membership is by position only. Both Sections are imported with **needs_review = Yes** and the note "imported from a small-letter (a)/(b) list; confirm these are Sections" (your decision I10).

How it will be numbered in the Diary (decision D9): Sections have their own numbering format, default (a), (b), (c) (owner decision D13), and each Section restarts the Item numbering at (1). The Items are shown as (1), (2), ... in the Diary (D13), while the Word file uses (i), (ii), ... (the importer recognises Items by that). The Sub-topic reads: Section (a) `Ex Parte / Without Notice`, Items (1) and (2); Section (b) `Determining Jurisdiction`, Items (1) to (10). The grouping and counts under the two Sections match Word's own lists (compared by Word's list ids 439 and 563), so those two need no renumbering note. **There are two other places where numbering does differ:** Word restarts a list inside one Sub-topic at `para-1033` (a second list, id 369, after an earlier group, id 368) and at `para-1356` (list 560 after list 483). Word shows (i) again there; the Diary numbers the whole run continuously, (1), (2), (3). Those two Items are flagged (pattern 19, default D-a, pending your confirmation).

## 6. How the import will be checked

**Dry run.** Before anything is saved, the importer produces a preview file (and an on-screen page). It lists, without touching the database: the 41 Subjects, how many Topics, Sub-topics and Items each has, how many lines are clean, how many need review (with the reason; the two Sections are listed as flagged, with their reason), and the first few lines of each Topic so you can see that it looks right. You approve, and only then is the real import done. Running the import twice does not create duplicates.

**Reconciliation report.** After the import, a report confirms nothing was lost or invented:

1. Counts per level per Subject from the file against the counts in the database. They must match exactly (for example, 41 Subjects, 178 Topics under main Subjects, 323 Sub-topics, 2 Sections (both flagged), 950 Items, 1,495 text paragraphs, 11 blank paragraphs skipped; 691 clean and 259 flagged Items). The completeness equation must hold: planned records + skipped headings + blank paragraphs + problem paragraphs = all paragraphs (1,494 + 1 + 11 + 0 = 1,506).
2. A **full-text comparison**: all text is rebuilt from the database in the original order and compared line by line with the Word file. Any difference is listed. The target is zero unexpected differences. The only expected differences are the **19 names with the trailing colon removed** (I8), which are listed with the original beside the stored name. The Item counts under the two Sections are checked against Word's own list groups (by list id) and are expected to agree; the two list restarts of pattern 19 are the known exceptions and are flagged. Formatting is compared too: every Item Text is compared with the file as text plus bold/italic/underline spans, so a lost or shifted b/i/u run is reported.
3. The list of the 19 colon removals.
4. A list of every record flagged needs_review with its reason: 259 Items and 2 Sections, 261 in all.

## 7. Decisions

The owner's answers, kept verbatim in `[Answer: ...]`. Numbered as before (the Design document refers to them as I1 to I9).

1. **Other Subjects and Topics** (called "Other Acts" when you answered; the name was changed by decision D8). Sub-topics and Items sit directly under the Subject (no default "General" Topic). [Answer: Yes] **Decision: direct, as planned.**
2. **Lines that are only a case name or only a citation** (for example `Associate Builders`). [Answer: When in doubt, put as 'Text with no Citation', and flag for my later review] **Decision:** any doubtful line is stored whole as Text with no Citation and marked needs_review with a reason.
3. **The two "(a)/(b)" lines** (`Ex Parte / Without Notice`, `Determining Jurisdiction`). [Answer: These should be Sections] **Decision:** Sections (section 5.1).
4. **Lines with several citations marked (i), (ii).** There are 38. [Answer: Keep them as one long citation, and flag for review] **Decision:** one Item, flagged.
5. **"[NO LONGER GOOD LAW]".** [Answer: I do not need any coloured badge. Keep the wording in the text.] **Decision:** wording stays; no badge.
6. **Search wording.** [Answer: Ok] **Decision:** straight and curly quotes alike; "&" is not the same as "and".
7. **Blank paragraphs.** [Answer: Ok] **Decision:** the 11 blank lines are skipped and listed in the report.
8. **Sub-topics (13) and Topics (6) that end in a colon.** [Answer: Remove the colons] **Decision:** colons removed from the stored name; original kept in `original_line`; all 19 listed in the reconciliation report.
9. **Two Sub-topics in a row.** [Answer: These are separate sub-topics, some of which may not have any items at present] **Decision:** separate Sub-topics, not flagged.

10. **Flagging the two Sections** (this answers the earlier question N2). [Answer: Ok, flag them for my review.] **Decision:** both Sections are imported with needs_review = Yes and a review note.

### Questions raised by these decisions, now closed

- **N1. Numbering after a Section.** [Answer: Your modification is correct. Perhaps, instead, give 'Sections' their own numbering system as well, and restart the numbering of items within them.] **Closed by decision D9** (`docs/DESIGN.md` sections 4 and 14): Sections have their own numbering and each restarts the Items at (1) in the Diary (the Word file shows (i)).
- **N2. Review flag on the Sections.** [Answer: Ok, flag them for my review.] **Closed by decision I10** (item 10 above).

Note on names: the owner's later instruction to rename "Other Acts" to "Other Subjects" is decision D8 (`docs/DESIGN.md` section 14).
