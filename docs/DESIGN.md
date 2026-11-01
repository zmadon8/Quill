# Judgment Diary: Design

Status: design only. No application code exists yet. Nothing here has been built, and the Word file has not been changed.

This document turns your specification into a buildable design. Parts addressed to you are in plain language. Technical parts are kept so a developer (or Kiro in a later phase) can build without guessing. The facts about your Word file come from `docs/IMPORT_ANALYSIS.md`.

## 0. The governing principle

**Data reliability comes first.** Nothing is altered, merged, dropped or "corrected" silently, whether at import, editing, conversion, restore or export. When the system is unsure, it keeps the original and flags it for you. Every other decision below follows from this.

## 1. What your Word file told us (confirmed)

Your instructions and the analysis agree:

- Each **Heading 1** is a **Subject**, except **Miscellaneous**. Miscellaneous contains the Other Acts: each Topic inside it is really a Subject and is treated as an **Other Act**.
- **Sub-topics** are the numbered lists 1, 2, 3.
- **Items** (and Nested Items later) are numbered (i), (ii), (iii).
- There are **no Sections** and **no footnotes** at present. The design still supports Sections for the future. Footnotes are not part of the model.
- Real counts: 41 Subjects (10 main plus 31 Other Acts), 178 Topics under the 10 main Subjects, 323 Sub-topics, 950 Items, no Nested Items, no bullets.

## 2. Hierarchy

```
Subject            (Heading 1 in Word; "Other Acts" Subjects live in the Other Acts group)
  Topic            A, B, C
    Sub-topic      1, 2, 3
      Item / Nested Item     (i), (ii), (iii)   (one shared run)
      Section                bold header, no number
      Note                   cross-reference
```

Rules from the specification:

1. An **Item** is one proposition of law: rich text plus one single-line **Citation**.
2. A **Nested Item** is an Item that has Items beneath it. It has its own text and Citation and is numbered like an Item. Items beneath it show **bullets only**.
3. A **Section** is a bold header line between Items. It has no number, no children, and never interrupts numbering.
4. A **Multi-Item** is an Item with several citations in one line, shown as (a), (b), (c). Each is a **Case** with its own Citation and an optional rich-text comment.
5. Items may sit at any level: directly under a Subject, Topic, Sub-topic or Nested Item.
6. A container shows its **own Items, Sections and Nested Items first** (one shared order), then its **Notes**, then its **child headings**.
7. Numbering is **generated from position and never stored** (section 5).

### 2.1 Other Acts: no Topic level (proposal, see open question 1)

An Other Act has no Topics after import: the file goes Topic, Sub-topic, Item, and the Topic became the Subject. So the model must let an Other Act hold Sub-topics and Items directly.

The design allows this in the simplest way:

- A **Sub-topic's parent** is either a **Topic** or a **Subject** (exactly one of the two, enforced by the database).
- **Items, Sections, Notes** already allow a Subject as parent.
- Rule: a Subject holds **either Topics or direct Sub-topics, not both**. The app refuses to mix them and explains why. This keeps numbering unambiguous.
- Example: Income Tax (0 Sub-topics, 1 Item) shows its Item directly under the Subject. Companies Act (15 Sub-topics, 31 Items) shows Sub-topics 1 to 15 directly under the Act, with any Items that sit before them shown first.

Alternative: create a hidden-looking default Topic called "General" inside each Other Act. This makes every Subject look the same, but adds a Topic that is not in your file and shows an "A. General" heading you never wrote. I recommend the direct approach and need your confirmation.

### 2.2 One level of nesting

Nested Items go **one level deep only** (a Nested Item contains plain Items, which show bullets; an Item inside a Nested Item cannot itself be Nested or Multi). Your file has none, and this confirms the simple reading of the specification. If you ever need deeper nesting, it is a deliberate later change (open question).

## 3. Data model

Every record in every table carries:

| Field | Meaning |
|---|---|
| `id` | Permanent number, **never reused**, even after permanent deletion (database sequence, never reset; deleted rows are never renumbered) |
| `created_at`, `updated_at` | Set automatically |
| `deleted_at` | Empty normally; filled when moved to Trash |
| `version` | Whole number, goes up by one on every change; used to detect clashes (section 9.2) |
| `created_by`, `updated_by` | Which user |

### 3.1 Parents: separate columns, not "parent_type / parent_id"

The specification sketched a generic `parent_type` plus `parent_id`. A generic pair cannot be protected by the database, so a record could point at something that does not exist. The design instead uses **separate optional links plus a check rule that exactly one is filled**:

| Table | Possible parents (exactly one set) |
|---|---|
| Subtopic | `topic_id` or `subject_id` |
| Section | `subject_id`, `topic_id`, `subtopic_id` |
| Item | `subject_id`, `topic_id`, `subtopic_id`, `parent_item_id` (a Nested Item) |
| Note | `subject_id`, `topic_id`, `subtopic_id`, `item_id`, `section_id` |

The database check is: "exactly one parent column is not empty". Linked records are protected by foreign keys, so nothing can point to a missing record. The screens and numbering still behave as if there were a generic parent.

### 3.2 Tables

**Subject**: `name`, `position`, `show_on_landing` (Yes/No), plus `landing_position` and `other_acts_position` so both lists reorder independently.
- Name must not be empty.
- **Name is unique among non-deleted Subjects**, case-insensitive. (A partial unique index: unique where `deleted_at` is empty.)
- Restore conflict: if a deleted Subject is restored and a live Subject now has its name, the app does not guess. It asks you to enter a new name for the restored one (rename-on-restore), then restores. The same prompt applies if you restore a Topic whose name now duplicates a sibling (Topic names are also unique within their Subject, as the file has no repeats).

**Topic**: `subject_id`, `name`, `position`. Name required.

**Subtopic**: `topic_id` or `subject_id` (see 3.1), `name`, `position`.

**Section**: parent (3.1), `name`, `position`.

**Item**:
- parent (3.1), `kind` (plain, multi, nested), `text` (rich), `text_plain` (derived), `citation` (single-line plain text), `flag` (none, overruled, doubted, other), `flag_text`, `needs_review`, `review_note`, `position`.
- `original_line` (the exact Word paragraph, set at import, never edited) and `import_ref` (where it came from: paragraph number in the file). Both are empty for items you create by hand.
- Rules in the database: a Nested Item's children must be plain Items (one level); a Multi-Item has no `citation` of its own because its Cases hold the citations.

**Case**: `item_id`, `citation`, `comment` (rich, optional), `position`. Only allowed under a Multi-Item.

**Note**: parent (3.1), `text` (rich), `position`.

**NoteLink**: `note_id`, and exactly one target column: `subject_id`, `topic_id`, `subtopic_id`, `section_id`, `item_id` (a Nested Item is an Item). Links are never removed by the system, not even when the target is in Trash.

**UserSettings**: `user_id`, `opening_page`, `opening_subject_id`, and the number formats for Topics, Sub-topics, Items, Nested Items and Multi-Item citations.

**User**: login name, password (stored only as a secure hash), `is_admin`, `is_active`.

**VersionHistory** (new, one table for all record types): `record_type`, `record_id`, `version`, `snapshot` (the full record contents as of that version, including its parent and position), `changed_at`, `changed_by`, `change_kind` (create, edit, move, reorder, delete, restore, convert, import). Details in section 9.

**BackupLog**: when each automatic backup ran, its size, whether it succeeded, and whether the off-site copy succeeded.

### 3.3 Rich text

Rich text is stored as **sanitised HTML limited to `p`, `br`, `b`, `i`, `u`** (strong and em are converted to b and i). Everything else is removed on save, including pasted styles, links, fonts, colours and scripts. This removal is the only change ever made to pasted text, and it is the specified one. A plain-text copy is stored beside every rich field for searching.

The Citation is a **plain single-line field**. It is shown and exported in italics by the display, not stored as formatting. Line breaks are not accepted in it.

Imported text has no formatting in the analysis findings that needs preserving beyond what Word runs carry. The importer reads bold, italic and underline runs and keeps them as b, i, u. If a run has other formatting (colour, size), that formatting is dropped and the line is flagged in the dry-run report, never silently.

### 3.4 Soft delete and IDs

Deleting sets `deleted_at`. Nothing is physically removed except by the "Delete permanently" action in Trash. Because IDs come from a database sequence and are not recycled, an old ID (in a link, a history entry or a backup) never ends up pointing at a different record.

## 4. Numbering (generated, never stored)

Numbers are computed whenever a page or export is built, from the order of records, so moving or inserting something renumbers automatically with no stale numbers.

1. **Topics**: A, B, C within a Subject.
2. **Sub-topics**: 1, 2, 3 within a Topic (or within a Subject for Other Acts).
3. **Items and Nested Items**: one shared run (i), (ii), (iii) within their parent. **Sections are not counted** and do not break the run. **Notes are not counted.**
4. **Items inside a Nested Item**: bullets, no numbers.
5. Every level **restarts under its parent**.
6. **Multi-Item citations**: (a), (b), (c) inside the item.

Formats come from Settings (section 6.11). Format choices: A,B,C; a,b,c; 1,2,3; I,II,III; i,ii,iii; (i); (a); (1); bullet; none.

**Counting past the end of the alphabet.** Letters continue the way spreadsheets do: a to z, then aa, ab, ac... az, ba, and so on (A to Z, AA, AB for capitals). This never fails.

**Large Roman numerals.** Standard Roman numerals are used up to 3,999 (more than enough). Beyond that, the app shows ordinary numbers instead of inventing symbols. A Roman-numeral run of (xl) or (xlix) is normal and handled. In your file the biggest single run is far smaller, but the code must be correct anyway.

Numbers appear in two places only: on screen and in the Word export. Searching and backups use records and positions, not numbers, so a format change never changes data. (Citing "Topic C" in a conversation always matches what you see on screen at that moment.)

## 5. Screens

### 5.1 Landing page (4.1)
- Shows Subjects with `show_on_landing = Yes` as tiles, in your chosen order.
- A fixed tile **Other Acts** opens a list of Subjects with `show_on_landing = No`, also reorderable.
- Each Subject has a switch (Yes/No) to move it between the two lists.
- The app opens on the page chosen in Settings.
- After import: 10 Subjects on the landing page and 31 under Other Acts.

### 5.2 Subject contents (4.2)
- Topics are listed as a table of contents (TOC). Clicking a Topic shows its Sub-topics. For Other Acts the Sub-topics are listed directly.
- No TOC entries for Nested Items or Sections.
- Three buttons: **View whole Subject**, **View this Topic**, **View this Sub-topic**.
- The TOC can stay visible at the side while reading.
- **View whole Subject renders the entire Subject in one page with no lazy loading.** This is so that the browser's own find (Ctrl or Cmd + F) works across everything. Largest Subject: Procedure at 202 Items, which is light for one page. This stays safe up to several thousand Items.

### 5.3 Reading view (4.3)
- Item: text, then " - ", then the Citation in italics. A Multi-Item: description, then the citations on the same line, each preceded by (a), (b), separated by " ; ", with a Case comment following its citation.
- Items with a flag are **red** with the flag text. Items marked "For review" show an **amber** marker.
- Notes show a link icon and "See also: Subject > Topic > ..." and are clickable.
- Order inside any container: Items, Sections and Nested Items (one shared order), then Notes, then child headings.

### 5.4 Edit mode (4.4)
- One toggle switches edit mode on. Reading is the default so nothing changes by accident.
- In edit mode: edit, delete, move up/down buttons, drag-to-reorder, "move via tree" (pick a new place from a tree), add Item / Nested Item / Section / child heading, rename anything.
- Drag handles use SortableJS; **move up/down buttons always exist too**, because dragging is poor on phones and for some users.
- Rules refuse impossible moves (for example moving a Topic under an Item) and say why.

### 5.5 Item editor (4.5)
- Rich text with Bold, Italic, Underline buttons and Ctrl+B, Ctrl+I, Ctrl+U.
- Separate single-line **Citation** box.
- Flag selector (none, overruled, doubted, other plus short text).
- **For review** switch with an optional note.
- For Multi-Items: a Cases list (add, remove, reorder cases, each with a Citation and optional comment).
- **Change to** button for conversion (section 7).
- Shows **created** and **last edited** times and who.
- Shows **History** (section 9).
- Paste from Word keeps only bold, italic, underline.
- For imported items, a read-only panel shows the **original Word line** so you can compare it with what you see.

### 5.6 Delete and Trash (4.6)
- Delete only sets `deleted_at`.
- Deleting a heading (Subject, Topic, Sub-topic) moves its entire contents to Trash with it, as one "batch" (shared `delete_batch` identifier). Restoring the heading restores exactly that batch together. Items deleted separately earlier stay in Trash.
- Trash screen: each entry with its full path and a Restore button.
- **Permanent delete** is available only from Trash and needs a second confirmation that names what will be lost.
- Restore edge cases: if the original parent is itself in Trash, Restore offers to restore the parent chain too; Subject-name clashes follow the rename-on-restore prompt (section 3.2).

### 5.7 Undo (4.7)
- Undo works for the current session after edit, delete, move or reorder. It is built from version history (section 9), so Undo of a move puts the record back to its previous parent and position.
- Undo never touches changes made by someone else, and warns if the record has since changed.

### 5.8 Back button (4.8)
Always visible, returns to the previous page; sensible fallback to Home.

### 5.9 Split screen (4.9)
Two independent panes side by side, each with its own location. Only on wide screens (about 1100 pixels and above). On narrower screens the option is hidden. Last milestone (7), so it can be refined without risk to the core.

### 5.10 Shortcuts (4.10)
- Ctrl+Option+G opens Global Search; Ctrl+Option+H goes Home (Ctrl+Alt on Windows).
- Cmd+G and Cmd+H are deliberately not used, as the browser needs them.
- A visible **Search** button and **Home** button appear on every page.

### 5.11 Settings (4.11)
Per user:
- **Opening page**: Home, Other Acts, Global Search, last page viewed, or a chosen Subject.
- **Number formats** for Topics, Sub-topics, Items, Nested Items and Multi-Item citations, each with a live preview. Changing formats changes display and Word export only, never the stored data.

### 5.12 Phone (4.12)
- One column, no sideways scrolling, text at least 16 px, tap targets at least 44 px.
- TOC becomes a full-width list or a slide-over opened by a **Contents** button.
- A sticky breadcrumb shows where you are. Home, Search and Back stay reachable.
- Touch editing uses the move up/down buttons rather than dragging.
- Written mobile-first so the phone layout is the base and wider screens add to it.

### 5.13 Other screens
- **Review list**: every item marked For review across all Subjects, with path and note.
- **Trash**, **History**, **Backups**, **Users (Admin only)**, **Import report** (during import only).

## 6. Conversions: Item, Multi-Item, Nested Item (4.13)

Any of the three can become either of the other two. The record **keeps its ID**. A **preview is shown before every conversion** (before and after side by side), the change is recorded in history, and **Undo and history restore** bring the old form back exactly.

| From | To | What happens |
|---|---|---|
| Item | Multi | The text stays. The Citation becomes Case (a). |
| Multi | Item | The Case citations (and comments) are joined into one single-line Citation: `(a) ... ; (b) ...`. |
| Item | Nested | Text and Citation stay. It simply may now have Items beneath. |
| Multi | Nested | Text stays. Each Case becomes an Item beneath it (citation becomes that Item's Citation; comment becomes that Item's text). |
| Nested | Item or Multi | You choose: **(a)** keep the Items beneath, moved to sit directly after it (nothing lost); or **(b)** fold each child into a Case: child's text becomes the comment, child's Citation becomes the Case citation; the Nested Item's own Citation becomes Case (a). |

**Warnings and refusals (these are the resolved design points):**

1. **Multi to Item joins rich-text comments into a plain single line.** That loses bold/italic/underline and line breaks in comments. The preview shows exactly the resulting text and a clear warning "formatting and line breaks in comments will be lost". The old form stays in history for restore. Nothing proceeds without your confirmation.
2. **Nested to Multi/Item option (b), "folding", is refused** and option (a) is offered instead when any child: is a Multi-Item or Nested Item, has more than one Case, has a flag or For-review marker, has a Note, or when the Nested Item has Sections beside its children. (Folding would lose structure, so the app declines rather than guess.)
3. Because only one level of nesting exists (2.2), a Nested Item with Nested children cannot arise.
4. Converting to Nested for a Multi with comments: each comment becomes the child's text with its formatting preserved (rich text to rich text, no loss).
5. A conversion that would put something in an illegal place is refused with an explanation.

## 7. Notes and cross-references

- A Note can sit at any level or on an Item, has its own rich text, and has one or more links to Subjects, Topics, Sub-topics, Sections or Items (including Nested Items).
- Click a link to jump to the target. The target shows **"Linked from: <path>"**, so links are visible at both ends.
- If a target is in Trash, the Note shows **"target deleted"**. The link is kept, and works again if the target is restored.
- **Links are never silently removed.** Permanent deletion of a target that has incoming links is refused until you decide what to do with each Note (shown in a list).
- Notes are searchable.
- **Ordering:** a Note appears after the Items/Sections/Nested Items of its parent and before child headings (assumption, open question 5). A Note on an Item shows directly beneath that Item.
- Word export prints a Note as "See also: Subject > Topic > ...".

## 8. Import from Word (spec section 8)

One-time, supervised. Based fully on `docs/IMPORT_ANALYSIS.md`. The tool reads the docx and never modifies it.

### 8.1 Recognising levels
Word shows every list entry at depth 0, so levels are recognised by **list format**, not indent:

| Word | Becomes |
|---|---|
| Heading 1, capital Roman (I., II.) | Subject (except Miscellaneous) |
| Heading 1 "Miscellaneous" | Not a Subject. Its Heading 2 Topics become **Other Acts Subjects** with show_on_landing = No |
| Heading 2, capital letters (A., B.) | Topic (under the 10 main Subjects) |
| List Paragraph, plain numbers (1., 2.) | Sub-topic |
| List Paragraph, small Roman ((i), (ii)) | Item |
| List Paragraph, small letters ((a), (b)) | The 2 odd lines: imported as flagged Sub-topics (open question 3) |
| Blank paragraph | Skipped, but counted and listed in the report |

A new Item group starts whenever the Word list changes, so numbering restarts as in the file.

### 8.2 Exactness
- Every paragraph is stored whole in `original_line`, including odd spacing, curly quotes, ampersands and typos. Text is saved as typed.
- Bold, italic, underline runs are kept as b, i, u.
- A line is split into Text and Citation **only when unambiguous** (exactly one " - ", both sides non-empty, brackets balanced, no typed "(ii)" marker, no bracketed remark or flag, no double or edge spaces, right side looks like a citation). Expected: **693 split, 259 imported whole** and marked For review with a reason.
- Inline words like `[NO LONGER GOOD LAW]` stay in the text exactly as written. The system never removes them.
- Sub-topics and Topics are never split. A trailing colon stays.
- The 38 lines with typed (i), (ii) citations stay as one Item, flagged (open question 4).

### 8.3 Dry run and reconciliation
1. **Dry run**: a preview (page and downloadable file) shows counts per Subject and level, clean versus flagged with reasons, and the first lines of each Topic. Nothing is saved. You approve before the real import.
2. **Real import** is wrapped in a single database transaction: it fully succeeds or leaves nothing. Running it twice does not duplicate (each record carries its `import_ref`).
3. **Reconciliation report** after import:
   - counts per level and Subject versus the file (expected: 41 Subjects, 178 Topics under main Subjects, 323 Sub-topics, 950 Items plus 2 odd lines, 1,495 text paragraphs, 11 blanks skipped);
   - a **full-text round trip**: rebuild text from the database in order and compare with the Word file line by line; target is zero differences;
   - the list of every flagged line and why.
4. A backup is taken immediately before and after import.
5. The imported data is marked in history as `import`, so it can be seen what came from Word.

## 9. Reliability

### 9.1 Version history (all record types) and Undo
- Every create, edit, move, reorder, delete, restore and conversion writes a full snapshot to VersionHistory, for **every** record type (not only Items).
- Items keep **at least the last 20 versions**, viewable and restorable. The design keeps **all** versions by default (text is small: even 10,000 versions is a few megabytes), pruned only if you ask.
- **Restore a version** creates a new version (history is never rewritten).
- **Undo** is a shortcut to "restore previous version of the thing I just changed", grouped per action (a drag that moved one item is one undo; a heading delete with 30 children is one undo).

### 9.2 No silent overwrites
- Each record has a `version`. The editor remembers the version it opened. On save, if the stored version is higher (someone else or another tab saved), the save is **refused** and the app shows **both versions** side by side and asks what to do (keep mine, keep theirs, or edit and save a merged text). Nothing is overwritten without a choice.
- This applies to moves and deletes too.

### 9.3 Backups
- **Automatic daily backup**, kept at least **30 days**, downloadable from the Backups screen.
- Two kinds: the host's database backups (section 3 of the hosting guide) and the app's own **machine-readable file** (all tables, including Trash, history and settings, in one file).
- **Restore** from a backup file shows a **preview first** (counts of each record type and Subjects that would change, compared with now) and requires confirmation. A safety backup of the current state is taken before restoring.
- The in-app backup can be copied off-site (see the hosting guide).
- "Backup" button on the export screen produces the same file on demand.

### 9.4 Validation
- Required names on Subject and Topic (and Sub-topic and Section).
- Duplicate Subject names refused (among live Subjects).
- IDs never reused.
- Created and last-edited times stored and shown in the editor.
- Bad input never produces a half-saved record (every save is a transaction).

### 9.5 Security
- Password login (passwords stored as secure hashes, never readable). Failed attempts are rate-limited.
- An **Admin** can create, edit, disable and delete accounts. Only Admin sees the Users screen.
- The site only works over https. Session cookies are secure. Standard protection against forged requests is on.
- Rich text is sanitised on the server (not only in the browser) so pasted content cannot run scripts.
- Search and all queries use parameter binding (no injected SQL).
- No data lives on the server's disk: the database is a managed, persistent service (hosting guide).

## 10. Search (spec section 5)

- **Scope**: the whole database including Other Acts: headings, Item text, Citations, Cases, comments and Notes. **Trash excluded**.
- **Case-insensitive; partial words; quoted phrases exact.**
- **Punctuation-insensitive**: every searchable field has a second column holding a **normalised** copy: lower-case, punctuation and brackets turned to spaces, repeated spaces collapsed, curly quotes treated as straight. So `2018 9 SCC 49` finds `(2018) 9 SCC 49`. "&" is kept distinct from "and" (proposal, open question 6; easy to change).
- **Technique**: PostgreSQL full-text search for words and phrases, plus **trigram indexes** (pg_trgm) on the normalised column for partial words. Quoted phrases search the normalised text exactly.
- **Filters**: Subject, Citations only, For review only.
- **Results** show the full path, a highlighted snippet, and the total count. Clicking opens the record **in context, scrolled to the item** and briefly highlighted.
- **Speed**: the whole database is about 950 Items; the target is under 1 second for about 2,000. With indexes this is expected to be tens of milliseconds. It will be measured with test data of 5,000 Items.
- The Search box on every page leads to the separate Search page. Within-page search is the browser's own Ctrl/Cmd + F (which works because of 5.2).

## 11. Flags and review markers (spec section 6)

- **Flag** (overruled, doubted, other plus short text): shown red. It is a separate field. Imported text stays exactly as in Word, so `[NO LONGER GOOD LAW]` stays inside the text and the flag field is left empty until you decide (open question 5 in the import analysis).
- **For review**: amber marker plus optional note. One click to set or clear in the reading view. Appears in the Review list, as a search filter, and is **omitted from the Word export unless you include it** (export option).
- Imported "needs review" lines use this same marker, with the reason as the note.

## 12. Word export (spec section 9)

Whole database or a single Subject. Mapping:

| Diary | Word |
|---|---|
| Contents page | Lists every Subject; table of contents field |
| Subject | Heading 1, each on its own page, name in the page header |
| Topic | Heading 2, lettered per Settings |
| Sub-topic | Bold numbered line |
| Items and Nested Items | Numbered, one shared run |
| Sections | Bold, unnumbered |
| Items in a Nested Item | Bullets |
| Citation | Italic, preceded by " - " |
| Multi-Item | Description, then (a), (b) citations on the same line, comments after each |
| Note | "See also: Subject > Topic > ..." |
| Rich text | b, i, u kept |
| Items under a heading | Precede its child headings |

Details:
- **Other Acts** is a Subject at Heading 1 in a whole-database export. Its grouped Subjects are Heading 2, their Topics Heading 3 (Other Acts have no Topics at first, so Sub-topics follow directly), then the same as above. This matches how your original Word file is organised.
- **Single-Subject export of an Other Act**: it is exported as the Subject at **Heading 1 alone** (as every Subject is), without the "Other Acts" wrapper. This is my reading; please confirm (open question 3).
- Numbers follow **Settings** formats at the moment of export.
- Excludes Trash. Shows the **export date and record count** (so you can check against the screen).
- For Review markers appear only if you tick "include review markers".
- A separate **Backup** button gives the machine-readable restore file (not Word).
- **Round trip check** (milestone 6): export, then compare against the Word original: apart from deliberate formatting, text must match line for line.

## 13. Platform and proposed stack

**Important: this is a proposal only.** Your specification says this is one module of a combined web app with an entry screen that chooses between programs. That app is not confirmed to exist here, and I do not know what the other programs are. The stack below is my recommendation for a standalone build that can be fitted into a combined app later. If a combined app already exists, its technology wins and this section must be revisited.

| Concern | Proposal | Why |
|---|---|---|
| Framework | Django (Python) | Built-in login, admin accounts, forms, security defaults and database migrations |
| Database | PostgreSQL | Reliable, real full-text and trigram search, transactions |
| Pages | Server-rendered, with HTMX and small amounts of JavaScript | Few moving parts; easier to keep reliable than a large front-end framework |
| Rich text editor | TipTap, restricted to p, br, b, i, u | Matches the allowed formats exactly |
| Drag reorder | SortableJS, plus move up/down buttons | Buttons guarantee phone use |
| Word import/export | python-docx | Reads and writes .docx |
| Search | PostgreSQL full-text plus pg_trgm on a normalised column | No extra server needed |
| Locking | Version numbers (optimistic concurrency) | Section 9.2 |

If the combined app uses a different technology, the data rules in sections 2 to 4 and 8 to 12 still apply unchanged.

## 14. Open questions for the owner

Plain language. Please answer what you can. For each, my default (what I will do if you do not answer) is stated.

**About the combined app and structure**

1. **The combined app.** Does the entry screen with other programs already exist? What are the other programs, and what technology are they built in? *Default: build the Judgment Diary as a standalone app that can be plugged in later.*
2. **Other Acts structure.** Each Other Act (such as Companies Act) has no Topics after import. Shall Sub-topics (1, 2, 3) and Items sit directly under the Act, or shall each Act get a default Topic named "General"? *Default: directly under the Act (section 2.1). An Act then holds either Topics or Sub-topics, not both.*
3. **Exporting one Other Act on its own.** Should it come out with the Act as Heading 1 (like any Subject) rather than inside an "Other Acts" Heading 1? *Default: Heading 1 alone.*
4. **Nesting depth.** Is one level of Nested Items enough? *Default: yes.*
5. **Notes ordering.** Notes sit after the Items of their parent and before the child headings. Right? *Default: yes.*

**Behaviour**

6. **Restoring a deleted Subject whose name is now taken.** The app will ask you for a new name at that moment. Acceptable? *Default: yes.*
7. **Edit history length.** At least 20 versions are required. I plan to keep all. Fine? *Default: keep all.*

**From the import analysis** (full wording is in `docs/IMPORT_ANALYSIS.md`, section 7; numbered there, not repeated here):

8. Import Q1: Other Acts and the Topic level (same as question 2 above).
9. Import Q2: lines that are only a case name or only a citation.
10. Import Q3: the two "(a)/(b)" lines.
11. Import Q4: the 38 lines with several typed (i), (ii) citations.
12. Import Q5: `[NO LONGER GOOD LAW]` and other possible flags.
13. Import Q6: search wording for quotes and "&".
14. Import Q7: confirm the 11 blank lines carry no meaning.
15. Import Q8: trailing colons on 6 Topics and 13 Sub-topics.
16. Import Q9: the two Sub-topics in a row.

Confirmed by you in this phase (no longer open): each Heading 1 is a Subject; Miscellaneous holds Other Acts; Sub-topics are 1, 2, 3; Items are (i), (ii), (iii); no Sections now; no footnotes.
