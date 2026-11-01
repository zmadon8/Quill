# Judgment Diary: Design

Status: design, with the owner's answers recorded (section 14). Milestone 0 (login, backup and restore skeleton) is built; the code lives at the repository root (`config/`, `accounts/`, `backups/`, `diary/`); nothing else is built yet. The Word file has not been changed.

This document turns your specification into a buildable design. Parts addressed to you are in plain language. Technical parts are kept so a developer (or Kiro in a later phase) can build without guessing. The facts about your Word file come from `docs/IMPORT_ANALYSIS.md`.

## 0. The governing principle

**Data reliability comes first.** Nothing is altered, merged, dropped or "corrected" silently, whether at import, editing, conversion, restore or export. When the system is unsure, it keeps the original and flags it for you. Every other decision below follows from this.

## 1. What your Word file told us (confirmed)

Your instructions and the analysis agree:

- Each **Heading 1** is a **Subject**, except **Miscellaneous**. Miscellaneous contains the Other Subjects: each Topic inside it is really a Subject and is treated as an **Other Subject** (renamed from "Other Acts" by decision D8).
- **Sub-topics** are the numbered lists 1, 2, 3.
- In the Word file, **Items** are numbered (i), (ii), (iii). In the Diary, Items (and Nested Items) are numbered (1), (2), (3) by default (decision D13); the importer still recognises Items by the Word file's own (i), (ii) numbering.
- There are **no footnotes**. Footnotes are not part of the model. There are **two Sections** in the file: the two small headings `Ex Parte / Without Notice` and `Determining Jurisdiction`, which Word shows as (a) and (b) (decision I3, section 14).
- Real counts: 41 Subjects (10 main plus 31 Other Subjects), 178 Topics under the 10 main Subjects, 323 Sub-topics, 2 Sections, 950 Items, no Nested Items, no bullets. Total text paragraphs: 11 + 209 + 323 + 2 + 950 = 1,495 (209 Heading 2 lines = 178 Topics + 31 Other Subjects).

## 2. Hierarchy

```
Subject            (Heading 1 in Word; Other Subjects live in the Other Subjects group)
  Topic            A, B, C
    Sub-topic      1, 2, 3
      Item / Nested Item     (1), (2), (3)      (one shared run; restarts at (1) after each Section)
      Section                bold header with its own number, e.g. (a), (b)   (no children)
      Note                   cross-reference
```

Rules from the specification:

1. An **Item** is one proposition of law: rich text plus one single-line **Citation**.
2. A **Nested Item** is an Item that has Items beneath it. It has its own text and Citation and is numbered like an Item. Items beneath it show **bullets only**.
3. A **Section** is a bold header line between Items. It has its own number (its own format, section 4) and no children. It acts as a grouping header **by position**: the Items that follow it, up to the next Section, are numbered afresh from (1). A Section can be marked For review like an Item (section 11).
4. A **Multi-Item** is an Item with several citations in one line, shown as (a), (b), (c). Each is a **Case** with its own Citation and an optional rich-text comment.
5. Items may sit at any level: directly under a Subject, Topic, Sub-topic or Nested Item.
6. A container shows its **own Items, Sections and Nested Items first** (one shared order), then its **Notes**, then its **child headings**.
7. Numbering is **generated from position and never stored** (section 5).

### 2.1 Other Subjects: no Topic level (decided, D2; renamed by D8)

An Other Subject has no Topics after import: the file goes Topic, Sub-topic, Item, and the Topic became the Subject. So the model must let an Other Subject hold Sub-topics and Items directly.

The design allows this in the simplest way:

- A **Sub-topic's parent** is either a **Topic** or a **Subject** (exactly one of the two, enforced by the database).
- **Items, Sections, Notes** already allow a Subject as parent.
- Rule: a Subject holds **either Topics or direct Sub-topics, not both**. The app refuses to mix them and explains why. This keeps numbering unambiguous.
- Example: Income Tax (0 Sub-topics, 1 Item) shows its Item directly under the Subject. Companies Act (15 Sub-topics, 31 Items) shows Sub-topics 1 to 15 directly under that Subject, with any Items that sit before them shown first.

Decided: Sub-topics and Items sit directly under the Other Subject. (The alternative, a default Topic called "General", was rejected because it would show a heading you never wrote.)

### 2.2 One level of nesting

Nested Items go **one level deep only** (a Nested Item contains plain Items, which show bullets; an Item inside a Nested Item cannot itself be Nested or Multi). Your file has none, and this confirms the simple reading of the specification. One level is confirmed as enough (D4). If you ever need deeper nesting, it is a deliberate later change.

## 3. Data model

Every record in every table carries:

| Field | Meaning |
|---|---|
| `id` | Permanent number, **never reused**, even after permanent deletion (database sequence, never reset; deleted rows are never renumbered) |
| `created_at`, `updated_at` | Set automatically |
| `deleted_at` | Empty normally; filled when moved to Trash |
| `version` | Whole number, goes up by one on every change; used to detect clashes (section 9.2) |
| `created_by`, `updated_by` | Which user |
| `profile` | Which profile (data space) the record lives in (section 3.5) |

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
- Restore conflict (decided, D6): if a deleted Subject is restored and a live Subject now has its name, the app does not guess. It asks you to enter a new name for the restored one (rename-on-restore), then restores. The same prompt applies if you restore a Topic whose name now duplicates a sibling (Topic names are also unique within their Subject, as the file has no repeats).

**Topic**: `subject_id`, `name`, `position`. Name required.

**Subtopic**: `topic_id` or `subject_id` (see 3.1), `name`, `position`.

**Section**: parent (3.1), `name`, `position`, `needs_review` (Yes/No, default No), `review_note`. A Section has no children and shares one `position` sequence with the Items and Nested Items of its parent. Its number is generated, never stored (section 4). The two imported Sections are created with `needs_review = Yes` (decision I10).

**Item**:
- parent (3.1), `kind` (plain, multi, nested), `text` (rich), `text_plain` (derived), `citation` (single-line plain text), `flag` (none, overruled, doubted, other), `flag_text`, `needs_review`, `review_note`, `position`.
- `original_line` (the exact Word paragraph, set at import, never edited) and `import_ref` (where it came from: paragraph number in the file). Both are empty for items you create by hand.
- Rules in the database: a Nested Item's children must be plain Items (one level); a Multi-Item has no `citation` of its own because its Cases hold the citations.

**Case**: `item_id`, `citation`, `comment` (rich, optional), `position`. Only allowed under a Multi-Item.

**Note**: parent (3.1), `text` (rich), `position`.

**NoteLink**: `note_id`, and exactly one target column: `subject_id`, `topic_id`, `subtopic_id`, `section_id`, `item_id` (a Nested Item is an Item). Links are never removed by the system, not even when the target is in Trash.

**UserSettings**: `user_id`, `opening_page`, `opening_subject_id`, the number formats for Topics, Sub-topics, **Sections**, Items, Nested Items and Multi-Item citations, `export_custom_name` (text, default `Case Law Diary`, the program's display name; D17), `export_date_format`, and the time zone used for dates (section 5.11).

**User**: login name, password (stored only as a secure hash), `role` (Admin, Editor or Reader; default Reader; Admin is tied to `is_superuser`, exposed as `is_admin`), `is_active`. Section 9.6 has the roles.

**VersionHistory** (new, one table for all record types): `record_type`, `record_id`, `version`, `snapshot` (the full record contents as of that version, including its parent and position), `changed_at`, `changed_by`, `change_kind` (create, edit, move, reorder, delete, restore, convert, import). A Section's snapshot includes its `needs_review` and `review_note`. Details in section 9.

**BackupLog**: when each automatic backup ran, its size, whether it succeeded, and whether the off-site copy succeeded.

### 3.3 Rich text

Rich text is stored as **sanitised HTML limited to `p`, `br`, `b`, `i`, `u`** (strong and em are converted to b and i). Everything else is removed on save, including pasted styles, links, fonts, colours and scripts. This removal is the only change ever made to pasted text, and it is the specified one. A plain-text copy is stored beside every rich field for searching.

The Citation is a **plain single-line field**. It is shown and exported in italics by the display, not stored as formatting. Line breaks are not accepted in it.

Imported text has no formatting in the analysis findings that needs preserving beyond what Word runs carry. The importer reads bold, italic and underline runs and keeps them as b, i, u. If a run has other formatting (colour, size), that formatting is dropped and the line is flagged in the dry-run report, never silently.

### 3.4 Soft delete and IDs

Deleting sets `deleted_at`. Nothing is physically removed except by the "Delete permanently" action in Trash. Because IDs come from a database sequence and are not recycled, an old ID (in a link, a history entry or a backup) never ends up pointing at a different record.

### 3.5 Profiles (separate data spaces)

The owner chose option "B": a **profile** is a separate data space inside one program, like a separate notebook (for example "Madon - Case Law" and "Junior - Case Law"). Each profile has its own Subjects and Items; nothing is shared between profiles. The owner added: "Users will only have access to 1 profile per sub-progeam (such as the Judgment Doary)." So each user has at most **one** profile per program (the Case Law Diary is the program with key `diary`).

Everything below that is marked **DEFAULT** is a choice made without the owner's answer yet; it is used unless the owner says otherwise and each one is listed in the owner questions (section 14). The owner has since answered eight questions (see "Owner answers" below); the points they settled are no longer defaults.

- **Tables.** `accounts.Profile` (program key, name, `deleted_at`, timestamps) and `accounts.ProfileMembership` (user, profile, and the program copied from the profile so the database can enforce "one profile per user per program": unique on user and program). Several users may share a profile. A profile name is unique per program among profiles that are not deleted, ignoring case. (DEFAULT, P2 and P3.)
- **Profile column on diary data.** Subject, Topic, Sub-topic, Section, Item, Case, Note, Note link and Version history each carry a `profile` (protected: a profile that still has data cannot be removed). A record's profile must equal the profile of its parent; a Note link must be in the same profile as its Note and its target. The model refuses a mismatch when saving; the database cannot compare two rows, so that part is a code rule, not a database rule. A Subject name is unique per profile among live Subjects (it may be reused in another profile). (DEFAULT, P7.)
- **Who does what.** The owner chose a separate Role per profile (answer 2). Editor or Reader is stored on the user's membership in a profile, so the same person can be Editor in one profile and Reader in another. The **Admin** flag stays on the user and is suite-wide (Users, Profiles, Backups, Restore). Inside a program an Admin works with the role of their own membership in that profile (Editor or Reader), and does not see other profiles' data (answer 3, "No"). The Admin can change someone's profile and role from the Users screen. (Answers 2 and 3; P5.)
- **Managing profiles.** Admin only (answer 1). The Profiles screen on Home, next to Users and Settings, creates, renames and deletes profiles. Deleting a profile that still has data or members is refused unless explicitly confirmed, never silently. Deleted profiles are recoverable (see below).
- **A user with no profile** in a program (the owner's instruction: "If a User has 'no profile' assigned for a particular program, then simply do not show the option to enter that program. So, do not grey our 'Case Law Diary' for such a user, just don't show it at all."). The card is **not shown at all** on Home. If the user has no profile in any program, Home shows one line saying that no programs are assigned and to ask the Admin. Typing a program's address directly still answers 403 "No profile assigned - ask the Admin", so no data leaks.
- **How it is built.** The diary views use a `profile_required` decorator (`diary/views.py`) that finds the user's profile and answers 403 with the page "No profile assigned - ask the Admin" when there is none (a page, not a redirect). Every query filters on that profile, so another profile's ids give 404. The header shows "Case Law Diary &middot; Main" (the profile name in small type). Deleting a profile in use needs a ticked confirmation, removes its users' access and soft-deletes it; its rows stay in the database. `UserSettings.opening_subject` is only honoured when that Subject is live and in the user's profile (`opening_subject_for`).
- **Screens built.** The Profiles screen (Admin only) lists each profile with its users and Subjects, and has New profile, Rename and Delete. Delete soft-deletes. If the profile still has users or live Subjects, the page explains this and the Admin must tick a confirmation box; otherwise it is refused. Confirming removes the users' access to it; its rows stay in the database. On the Users screen, adding or editing a user has an optional "Case law diary profile" choice; choosing another replaces the old one, and blank removes access.
- **Recoverable deleted profiles.** Deleting a profile keeps its memberships but marks them `suspended` (they give no access and do not count towards the one-profile rule), and records who deleted it (`deleted_by`). The Profiles screen lists "Deleted profiles" (name, program, date, who, users, days left) with a Restore button (Admin only). Restore is refused, naming the users, if a member has been given another profile in that program meanwhile; if a live profile has the same name, the Admin must pick a new name first. The window is `PROFILE_RETENTION_DAYS` (default 30). The nightly cron runs `run_backup && purge_deleted_profiles`: the purge permanently deletes profiles past the window, with all their data, in one transaction, and only if a backup taken today succeeded (otherwise it refuses and logs). Each run is recorded in `PurgeLog` (counts per table), shown on the Profiles screen; it is not part of backup files.
- **Settings.** Display names (Home, Case Law Diary) stay global. Settings stay **per user** (answer 4, "Per User"). A user's opening Subject must belong to their profile. Each profile also has a **Profile settings** page (see Export name below).
- **Existing data.** A profile called "Main" in the Case Law Diary is created by the migration; all existing diary records and all existing users are put into it (answer 5, "Main"). The first Admin created later also joins "Main". The sample-data commands take `--profile` (default "Main"; loading creates it if missing; removing only acts inside that profile). Existing users keep their former role as the role of their membership.
- **Backups** stay whole-database (answer 6, "Whole database"): profiles, memberships (with roles), the deletion state of profiles and export names are in the backup file. A file made before profiles existed restores with its diary records and its users put into a "Main" profile, and the restore preview lists each profile with its users and records. Restoring or exporting a single profile is a possible later feature.
- **Owner answers (verbatim).** 1) "Admin only". 2) "Separate Role per profile". 3) "No". 4) "Per User". 5) "Main". 6) "Whole database". 7) "Is it possible to make them recoverable, for a limited number of days?" 8) "In the settings for each Profile, allow me to list what name will come for the backup - so, it may not be 'Case Law Diary Main', and the users of that Profile may decide to change it to something entirely different."
- **Recovery window (answer 7).** Yes, recoverable. Retention choice: **30 days** (default; environment variable `PROFILE_RETENTION_DAYS`, never less than 1). The Profiles screen lists Deleted profiles with days left and a Restore button (Admin only). A nightly job (`purge_deleted_profiles`) removes profiles past the window for good with all their data, in one transaction, and only if today's backup succeeded; otherwise it removes nothing and says why. Each run that does something is written to a **purge log** (`PurgeLog`: time, success, message, row counts).
- **Export name (answer 8).** Interpretation: "the backup" means the Word export files of the Milestone 6 (not the whole-database restore backup, which is not per profile). Each profile has an `export_name` (up to 100 characters). Blank means the default "<program display name> <profile name>", for example "Case Law Diary Main". The users of the profile decide it: on the Profile settings page (link in the header) an Editor of that profile can change it and a Reader can only view it; the page shows a preview of the cleaned file name. It replaces the Custom Name at the start of export file names (section 12.2); illegal characters are cleaned as there.
- **Screens.** The diary page header shows the profile name unobtrusively, "Case Law Diary · Main". Every diary page, search, import, export, Trash and History (later milestones) works inside the user's profile only; another profile's record numbers give "not found". (DEFAULT, P7 and P11.)
- **Import (Milestone 2)** imports into a chosen profile. (DEFAULT, P12.)

## 4. Numbering (generated, never stored)

Numbers are computed whenever a page or export is built, from the order of records, so moving or inserting something renumbers automatically with no stale numbers.

1. **Topics**: A, B, C within a Subject.
2. **Sub-topics**: 1, 2, 3 within a Topic (or within a Subject for Other Subjects).
3. **Sections** have their own numbering format (Settings, section 5.11). **Default (owner decision D13): (a), (b), (c)**, small letters in brackets, no full stop. The brackets keep them visibly different from Topics (A, B, C without brackets) and Sub-topics (1, 2, 3). Sections are numbered in order within their parent container (a Subject, Topic, Sub-topic or Nested Item) and **restart under each parent**.
4. **Items and Nested Items**: one shared run (1), (2), (3) within their parent (owner decision D13), **restarting at (1) after each Section**.
   - Items that come before the first Section of a container are numbered (1), (2), ... as usual.
   - Each Section restarts the Item numbering at (1) for the Items that follow it, up to the next Section (or the end of the container).
   - Nested Items count as Items in this run. Bullets inside Nested Items are unchanged.
   - **Notes are not counted** and come after the shared sequence.
   - The Section number, the Item numbers and the restart are all generated from position. Nothing is stored.
5. **Items inside a Nested Item**: bullets, no numbers.
6. Every level **restarts under its parent**.
7. **Multi-Item citations**: (a), (b), (c) inside the item.

**Worked example** (Topic `Letters Patent & OS Rules`, Sub-topic `Clause 12: Leave to Sue`; 12 Items and 2 Sections in the Word file, no Item before the first Section). The Diary shows, with the default Section format:

```
Clause 12: Leave to Sue                     (a Sub-topic; its own number comes from its position)
   (a) Ex Parte / Without Notice            (Section, flagged for review at import)
       (1) ...                              (2 Items)
       (2) ...
   (b) Determining Jurisdiction             (Section, flagged for review at import)
       (1) ...                              (10 Items, numbering restarted)
       ...
       (10) ...
```

If an Item were added before `Ex Parte / Without Notice`, it would read (1), and the Items under (a) would still start at (1). The Diary's labels differ from Word's (i), (ii) style by design (decision D13), but the grouping and the count of each run under the two Sections are the same as in Word, so those need no renumbering note. There are two other places where numbers do change: Word restarts a list inside one Sub-topic at `para-1033` (Word shows (i) after an earlier group) and at `para-1356`, and the Diary numbers each such group continuously as (1), (2), (3). These two Items are flagged For review (decision D-a).

**Moving or deleting a Section changes the numbers of Items.** The Items after a Section belong to its run by position, so removing or moving the Section merges them into the run before it (or moves the boundary). Before a move or delete the app shows a **preview** of the affected Items, before and after numbers (for example "these 10 Items will be numbered (3) to (12) instead of (1) to (10)"), and asks for confirmation. Undo works as for any other change (section 9.1). Because numbers are generated and never stored, there is nothing to repair afterwards.

Formats come from Settings (section 5.11). Format choices for Topics, Sub-topics, Items and Nested Items: A,B,C; a,b,c; 1,2,3; I,II,III; i,ii,iii; (A); (i); (a); (1); bullet; none. Sections use the same list plus one more style, **Section 1, Section 2**. Defaults: Topics A, B, C; Sub-topics 1, 2, 3; Sections (a), (b), (c); Items and Nested Items (1), (2), (3); Multi-Item citations (a), (b), (c).

**Counting past the end of the alphabet.** Letters continue the way spreadsheets do: a to z, then aa, ab, ac... az, ba, and so on (A to Z, AA, AB for capitals). This never fails.

**Large Roman numerals.** Standard Roman numerals are used up to 3,999 (more than enough). Beyond that, the app shows ordinary numbers instead of inventing symbols. A Roman-numeral run of (xl) or (xlix) is normal and handled. In your file the biggest single run is far smaller, but the code must be correct anyway.

Numbers appear in two places only: on screen and in the Word export. Searching and backups use records and positions, not numbers, so a format change never changes data. (Citing "Topic C" in a conversation always matches what you see on screen at that moment.)

## 5. Screens

### 5.1 Landing page (4.1)
- Shows Subjects with `show_on_landing = Yes` as tiles, in your chosen order.
- A fixed tile **Other Subjects** opens a list of Subjects with `show_on_landing = No`, also reorderable.
- Each Subject has a switch (Yes/No) to move it between the two lists.
- The app opens on the page chosen in Settings.
- After import: 10 Subjects on the landing page and 31 under Other Subjects.

### 5.2 Subject contents (4.2)
- Topics are listed as a table of contents (TOC). Clicking a Topic shows its Sub-topics. For Other Subjects the Sub-topics are listed directly.
- No TOC entries for Nested Items or Sections.
- ~~Three buttons (View whole Subject, View this Topic, View this Sub-topic)~~ removed by D16; the Subject name, Topics and Sub-topics in Contents open those scopes.
- The TOC can stay visible at the side while reading.
- **View whole Subject renders the entire Subject in one page with no lazy loading.** This is so that the browser's own find (Ctrl or Cmd + F) works across everything. Largest Subject: Procedure at 202 Items, which is light for one page. This stays safe up to several thousand Items.

### 5.3 Reading view (4.3)
- Item: text, then " - ", then the Citation in italics. A Multi-Item: description, then the citations on the same line, each preceded by (a), (b), separated by " ; ", with a Case comment following its citation.
- A **Section** shows as a bold header line with its number (default (a), (b)); the Items below it restart at (1) and are indented under it. A Section marked For review shows the same **amber** marker and its note.
- Items with a flag are **red** with the flag text. Items marked "For review" show an **amber** marker.
- Notes show a link icon and "See also: Subject > Topic > ..." and are clickable.
- Order inside any container: Items, Sections and Nested Items (one shared order), then Notes, then child headings.

### 5.4 Edit mode (4.4)
- One toggle switches edit mode on. Reading is the default so nothing changes by accident.
- Moving or deleting a Section first shows a preview of the Items whose numbers will change (section 4).
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
Always visible, returns to the previous page; sensible fallback to Subjects (the Subject index).

### 5.9 Split screen (4.9)
Two independent panes side by side, each with its own location. Only on wide screens (about 1100 pixels and above). On narrower screens the option is hidden. Last milestone (7), so it can be refined without risk to the core.

### 5.10 Shortcuts (4.10)
- **Both sets of shortcuts are kept** (decision D13): Alt+G opens Global Search and Alt+H goes to the suite Home (the program picker); Ctrl+Alt+G and Ctrl+Alt+H do the same. On a Mac, Option replaces Alt (Option+G, Option+H, Ctrl+Option+G, Ctrl+Option+H).
- Cmd+G and Cmd+H are deliberately not used, as the browser needs them.
- A visible **Search** button and **Subjects** button appear on every diary page; the suite **Home** link is beside the program name (decision D15).

### 5.11 Settings (4.11)
Per user:
- **Opening page** (overrides the login landing on Home, decision D15): Home, Subjects, Other Subjects, Global Search, last page viewed, or a chosen Subject.
- **Number formats** for Topics, Sub-topics, **Sections**, Items, Nested Items and Multi-Item citations, each with a live preview (the Sections preview shows a Section followed by Items restarting at (1)). Changing formats changes display and Word export only, never the stored data.
- **Custom Name** (decision D11): the text that starts every exported Word file name. Default `Case Law Diary`, following the program's display name (D17). Rules: trimmed; 1 to 60 characters; not empty after cleaning; no leading or trailing dots or spaces. Characters not allowed in file names ( \ / : * ? " < > | and control characters ) are replaced with a hyphen `-`, and repeated spaces are collapsed. A **live preview** shows the resulting file name for each export type, with a note of any replacement made (for example "':' was replaced with '-'").
- **Date format** for file names and the export date line: `YYYY-MM-DD` (default, needs owner confirmation), `DD-MM-YYYY`, or `D Month YYYY`.
- **Time zone** for "today's date" in file names: default Asia/Kolkata (default, needs owner confirmation). The server itself stores times in UTC; every time shown on a screen or in a report is in IST (round 3, item 4).

### 5.12 Phone (4.12)
- One column, no sideways scrolling, text at least 16 px, tap targets at least 44 px.
- TOC becomes a full-width list or a slide-over opened by a **Contents** button.
- A sticky breadcrumb shows where you are on judgment-list pages (decision D15). Home, Subjects, Search and Back stay reachable.
- Touch editing uses the move up/down buttons rather than dragging.
- Written mobile-first so the phone layout is the base and wider screens add to it.

### 5.13 Other screens
- **Review list**: every Item and Section marked For review across all Subjects, with path and note. A Section appears as a header row with its number and its parent path.
- **Trash**, **History**, **Backups (Admin only)**, **Users (Admin only)**, **Import report** (during import only).

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
- **Ordering:** a Note appears after the Items/Sections/Nested Items of its parent and before child headings (decided, D5). A Note on an Item shows directly beneath that Item.
- Word export prints a Note as "See also: Subject > Topic > ...".

## 8. Import from Word (spec section 8)

One-time, supervised. Based fully on `docs/IMPORT_ANALYSIS.md`. The tool reads the docx and never modifies it.

### 8.1 Recognising levels
Word shows every list entry at depth 0, so levels are recognised by **list format**, not indent:

| Word | Becomes |
|---|---|
| Heading 1, capital Roman (I., II.) | Subject (except Miscellaneous) |
| Heading 1 "Miscellaneous" | Not a Subject. Its Heading 2 Topics become **Other Subjects** with show_on_landing = No |
| Heading 2, capital letters (A., B.) | Topic (under the 10 main Subjects) |
| List Paragraph, plain numbers (1., 2.) | Sub-topic |
| List Paragraph, small Roman ((i), (ii)) | Item |
| List Paragraph, small letters ((a), (b)) | **Section** (decision I3), imported with `needs_review = Yes` (decision I10). The 2 lines are `Ex Parte / Without Notice` and `Determining Jurisdiction` |
| Blank paragraph | Skipped, but counted and listed in the report |

A new Item group starts whenever the Word list changes. The importer uses this only to detect structure; the Diary numbers Items by position (section 4), not by the Word list. Because each Section restarts the Item numbering, the generated numbers now agree with Word's own.

**Section membership.** A Section has no children (section 2). The importer creates the Section as a sibling in the shared order, directly under the same Sub-topic (or Topic or Subject) as the lines around it, at the position where it appears in the file. The Items that follow it, up to the next Section, Sub-topic or Topic, are its "members" only by position: they are ordinary Items of the same parent, placed after the Section. The importer records the Section's `import_ref` and the first Item's `import_ref` so the reconciliation can show this grouping. Each imported Section gets `needs_review = Yes` and `review_note` "imported from a small-letter (a)/(b) list; confirm these are Sections" (decision I10). If a small-letter list line ever appears where it cannot be attached to a parent, the importer stops and reports instead of guessing.

### 8.2 Exactness
- Every paragraph is stored whole in `original_line`, including odd spacing, curly quotes, ampersands and typos. Text is saved as typed.
- Bold, italic, underline runs are kept as b, i, u.
- A line is split into Text and Citation **only when unambiguous** (exactly one " - ", both sides non-empty, brackets balanced, no typed "(ii)" marker, no bracketed remark or flag, no double or edge spaces, right side looks like a citation). Expected: **693 split, 257 imported whole** (950 Items in all) and marked For review with a reason. Two of the 693 split Items are also flagged because Word's list restarts there (decision D-a), so the Items flagged in all are **259** and the clean ones **691**.
- Inline words like `[NO LONGER GOOD LAW]` stay in the text exactly as written. The system never removes them.
- Sub-topics and Topics are never split.
- **Trailing colons (decision I8, a deliberate exception to "never alter")**: the 6 Topics and 13 Sub-topics whose Word text ends with a colon are stored **without** the colon, as you instructed. The exact original text, colon included, stays in `original_line`, and the reconciliation report lists all 19 changes. The text comparison treats exactly these 19 as expected differences and reports any other difference.
- **Doubtful lines (I2)**: when in doubt (for example a line that is only a case name or only a citation, or has no " - "), the whole line is stored as Text with no Citation, marked For review with a reason.
- The 38 lines with typed (i), (ii) citations stay as one Item with one long Citation or Text as the split rule decides, flagged For review (I4).
- Two Sub-topics in a row are two separate Sub-topics; one may have no Items for now (I9). They are not flagged.

### 8.2a How it is built (Milestone 2)

- Code in `diary/importer/`: `docx_reader` (standard library only; reads runs, list formats and styles), `plan` (levels, parents, positions, the split rule, colon rule), `report` (text reports), `loader` (the only database code) and `service` (backup, import, reconcile). Command: `import_docx`. Screen: Admin only, `/import/`.
- `original_line` and `import_ref` (`para-NNNN`, the 0-based paragraph number) exist on Subject, Topic, Sub-topic, Section and Item, so each line and each colon change is traceable. Item Text keeps b, i, u runs; the Citation is plain text.
- Safety: the import refuses if the file has structural problems (including a name that is empty once its colon is removed), if the profile holds an incomplete earlier import, or if the profile holds **any live diary record** that is not from an import of this file (sample data, anything typed in). The dry run says what is in the way and how to remove it (`python manage.py remove_sample_data --profile <name>`) and never says "Ready to import" then. If every record is already there it does nothing. The Profile row is locked inside the import transaction and the state is checked again there; a partial unique index on (profile, `import_ref`) on each of the five tables stops the same paragraph being stored twice. A database refusal late in the run is rolled back and shown as a plain message.
- The import is run from the Render Shell (`python manage.py import_docx --profile <name> --import`). The screen (`/import/`, Admin only) does the dry run and the reconciliation and shows the exact command (decision D-e). A "Before import" backup is taken first (the import does not start without it) and an "After import" backup afterwards (decision D-b).
- Reconciliation compares counts per Subject, every line (rebuilt Item text is exact, not trimmed), a **run signature** (the text with its bold/italic/underline spans) of every Item Text against the file, the stored `original_line`, the listing order, the Section groupings against Word's own list groups, and the review markers. Only live records are compared; imported records in the Trash are listed separately. Differences are listed; the 19 colon removals are the only expected ones.
- Completeness: planned records + skipped headings (Miscellaneous) + blank paragraphs + problem paragraphs = every paragraph in the file (1,494 + 1 + 11 + 0 = 1,506 on the real file). It is shown in the dry run and the reconciliation, and a plan that does not add up is refused.
- Word's list restarts inside one Sub-topic set the review marker (decision D-a). Bold or underline on the citation side (which a plain Citation cannot hold) is listed line by line and sets the review marker (decision D-c). Parts of a Word line that cannot be imported (symbols, deleted text, fields) are left out, reported, and flag the Item or Section. Tabs and line breaks are kept in the text as typed.

### 8.3 Dry run and reconciliation
1. **Dry run**: a preview (page and downloadable file) shows counts per Subject and level, clean versus flagged with reasons, the two Sections listed as flagged with their reason, and the first lines of each Topic. Nothing is saved. You approve before the real import.
2. **Real import** is wrapped in a single database transaction: it fully succeeds or leaves nothing. Running it twice does not duplicate (each record carries its `import_ref`).
3. **Reconciliation report** after import:
   - counts per level and Subject versus the file (expected: 41 Subjects, 178 Topics under main Subjects, 323 Sub-topics, 2 Sections, 950 Items, 1,495 text paragraphs, 11 blanks skipped; 691 clean and 259 flagged Items (257 imported whole + 2 list restarts); 2 flagged Sections; **261 review-marked records in all = 259 Items + 2 Sections**);
   - a **full-text round trip**: rebuild text from the database in order and compare with the Word file line by line; target is zero differences;
   - the list of every flagged line and why;
   - the list of the 19 names changed by colon removal (original and stored form side by side), and a check that the count of generated Items under the two Sections (2 and 10) equals the count in Word's own lists (compared by Word's list ids 439 and 563, not by the importer's positions; (i), (ii) and (i) to (x) in Word; (1), (2) and (1) to (10) in the Diary; the first version of this document wrongly said 8, found by the importer when it read the file). The two list restarts (`para-1033`, `para-1356`) are the only places where the Diary's numbering differs from Word's; they are flagged.
4. A backup ("Before import") is taken immediately before and one ("After import") immediately after; neither is removed by the automatic clean-up.
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
- Two kinds: the host's database backups (section 3 of the hosting guide) and the app's own **machine-readable file** (all tables, including Trash, history, settings and profiles, in one file).
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
- An **Admin** can create, edit, disable and delete accounts and change anyone's role. Only Admin sees the Users screen. See section 9.6 for roles.
- The site only works over https. Session cookies are secure. Standard protection against forged requests is on.
- Rich text is sanitised on the server (not only in the browser) so pasted content cannot run scripts.
- Search and all queries use parameter binding (no injected SQL).
- No data lives on the server's disk: the database is a managed, persistent service (hosting guide).

### 9.6 Roles and permissions (decision D12)

Admin is a suite-wide flag on the account. Editor and Reader are **roles per profile** (answer 2): they are stored on the membership, so one person can be Editor in one profile and Reader in another. A new membership is a **Reader** unless the Admin picks another role.

- **Admin**: everything suite-wide, including Users, Profiles, Backups and Restore; inside a program the Admin works with the role of their own membership. Admin is the existing superuser flag; the app keeps the two in step. At least one active Admin must always exist: the last active Admin cannot be disabled, deleted or given another role, and nobody can disable or delete their own account.
- **Editor**: reads and edits the diary.
- **Reader**: reads only.

Only an Admin can change a role or a profile assignment. Code checks use `admin_required`, `editor_required` (Editor or Admin) and `reader_required` (any signed-in user) from `accounts/permissions.py`. Anyone not allowed gets a "403 forbidden" page; a signed-out visitor is sent to the login page.

Permissions for the planned features. **Everything except the Admin-only account and backup screens is a proposed default and needs owner confirmation.**

| Feature | Reader | Editor | Admin |
|---|---|---|---|
| Landing page, Subject contents, reading view, three View buttons | Yes | Yes | Yes |
| Search, own Settings (including Custom Name) | Yes | Yes | Yes |
| Review list (see flagged lines and notes) | Yes (proposed) | Yes | Yes |
| Export to Word: Current View | Yes (proposed) | Yes | Yes |
| Export to Word: Full (one file, per Subject) | No (proposed) | Yes | Yes |
| Trash list and History (view only) | No (proposed) | Yes | Yes |
| Edit mode: add, rename, move, reorder, convert, flag, Notes | No | Yes | Yes |
| Delete to Trash, Restore from Trash, Undo, restore an earlier version, conflict handling | No | Yes | Yes |
| Permanent delete from Trash | No | No (proposed) | Yes |
| Import from Word | No | No (proposed) | Yes |
| Users, Backups, Restore | No | No | Yes |
| Profiles screens (list, add, rename, delete, restore a deleted profile) and assigning a user's profile and role on the Users screen | No | No | Yes |
| Profile settings (export name): view / change | View | Change | Per own membership role |
| Open the program (needs a profile; without one the card is not shown on Home and the pages answer 403 "No profile assigned - ask the Admin") | Own profile only | Own profile only | Own profile only |

Profiles (section 3.5) narrow every row above: a role applies only inside the user's own profile (the membership's role), and the Admin does not see other profiles' data either. Backups and Restore are whole-database and show all profiles. Trash, History, search, review and export work inside the user's profile only. (Answers 2, 3 and 6.)

## 10. Search (spec section 5)

- **Scope**: the whole database including Other Subjects: headings, Item text, Citations, Cases, comments and Notes. **Trash excluded**.
- **Case-insensitive; partial words; quoted phrases exact.**
- **Punctuation-insensitive**: every searchable field has a second column holding a **normalised** copy: lower-case, punctuation and brackets turned to spaces, repeated spaces collapsed, curly quotes treated as straight. So `2018 9 SCC 49` finds `(2018) 9 SCC 49`. "&" is kept distinct from "and" (decided, I6; easy to change).
- **Technique**: PostgreSQL full-text search for words and phrases, plus **trigram indexes** (pg_trgm) on the normalised column for partial words. Quoted phrases search the normalised text exactly.
- **Filters**: Subject, Citations only, For review only (this covers flagged Items and flagged Sections). Section names are searchable like headings.
- **Results** show the full path, a highlighted snippet, and the total count. Clicking opens the record **in context, scrolled to the item** and briefly highlighted.
- **Speed**: the whole database is about 950 Items; the target is under 1 second for about 2,000. With indexes this is expected to be tens of milliseconds. It will be measured with test data of 5,000 Items.
- The Search box on every page leads to the separate Search page. Within-page search is the browser's own Ctrl/Cmd + F (which works because of 5.2).

## 11. Flags and review markers (spec section 6)

- **Flag** (overruled, doubted, other plus short text): shown red. It is a separate field. Imported text stays exactly as in Word, so `[NO LONGER GOOD LAW]` stays inside the text and the flag field is left empty. You decided no coloured badge is needed (I5).
- **For review**: amber marker plus optional note, on Items and on Sections (both have `needs_review` and `review_note`). One click to set or clear in the reading view. Appears in the Review list, as a search filter, and is **omitted from the Word export unless you include it** (export option).
- Imported "needs review" lines use this same marker, with the reason as the note. At import 261 records carry it: 259 Items (257 imported whole + 2 list restarts, decision D-a) and the 2 Sections (decision I10).

## 12. Word export (spec section 9)

There are **three types of export** (decision D10). All three follow the same mapping and the same options.

| Diary | Word |
|---|---|
| Contents page | Lists every Subject in that document; table of contents field |
| Subject | Heading 1, each on its own page, name in the page header |
| Topic | Heading 2, lettered per Settings |
| Sub-topic | Bold numbered line |
| Items and Nested Items | Numbered, one shared run that **restarts at (1) after each Section** |
| Sections | Bold header line carrying the Section number per Settings (default (a), (b)) |
| Items in a Nested Item | Bullets |
| Citation | Italic, preceded by " - " |
| Multi-Item | Description, then (a), (b) citations on the same line, comments after each |
| Note | "See also: Subject > Topic > ..." |
| Rich text | b, i, u kept |
| Items under a heading | Precede its child headings |

**Section numbering in Word.** The Section number is written as text in the bold header (so it cannot drift). The Items of each run (the Items before the first Section, then the Items after each Section) use their **own Word list instance with a restart override** (a separate numbering definition starting at 1 for each run), so Word restarts the numbers at (1) correctly after every Section. If any Word version is found to continue the numbers instead, the fallback is to write the Item numbers as text as well; this is checked in milestone 6.

### 12.1 The three types

**(i) Full, one Word document.** The whole database in one file.
- **Other Subjects** is a Subject at Heading 1. Its grouped Subjects are Heading 2, and the level where Topics would be is Heading 3 (Other Subjects have no Topics, so Sub-topics and Items follow directly), then the same as above. This matches how your original Word file is organised.
- The contents page lists all Subjects, the Other Subjects group and the Other Subjects inside it.

**(ii) Full, one Word document per Subject, delivered as one .zip download.**
- One document for each of the 10 main Subjects, plus **one single document holding all Other Subjects together**.
- In each per-Subject document the Subject is Heading 1 as usual. The Other Subjects document keeps the Heading 1 / 2 / 3 structure of type (i).
- Each document has its **own contents page, page header and count/date line**. The count is the number of records in that document.
- The zip also holds a small **manifest.txt** listing each file and its record count, and the grand total. The grand total equals the count of the Full export (type i).
- Two documents whose cleaned names are the same get " (2)", " (3)" added before the date, so nothing in the zip overwrites anything else.

**(iii) Current View.** Exports exactly what is on the screen.
- The scope is a Subject, a Topic or a Sub-topic. An Other Subject is a Subject scope; a single Other Subject exports with its name at **Heading 1 alone** (D3).
- The scope heading becomes **Heading 1** and the levels below step down. Numbering starts as on screen: a Topic keeps its on-screen letter and a Sub-topic its on-screen number (default, needs owner confirmation).
- The scope's whole subtree is exported (Trash excluded), not only the part scrolled into view.
- **Split screen**: the export applies to the **focused pane**, shown by a highlighted pane border. The button label says which pane it will export (for example "Export current view: Arbitration, Fraud").
- **Not offered** on search results, the Review list, Trash and History: the Current View button is disabled with a tooltip saying why. The Full exports and the review-marker option stay available.

### 12.2 File names

Format, space-separated: `[Custom Name] [Part] [Date].docx`

| Type | Part | Example |
|---|---|---|
| (i) Full | `Full` | `Case Law Diary Full 2026-11-01.docx` |
| (ii) per Subject | the Subject's name; the combined document is `Other Subjects` | `Case Law Diary Arbitration 2026-11-01.docx`, `Case Law Diary Other Subjects 2026-11-01.docx` |
| (ii) the zip | `Full - by Subject` | `Case Law Diary Full - by Subject 2026-11-01.zip` |
| (iii) Current View | the on-screen path, names joined by `, ` | `Case Law Diary Arbitration, Fraud 2026-11-01.docx` |

Rules:
- **Custom Name** comes from Settings (section 5.11): default `Case Law Diary` (the program's display name, D17), 1 to 60 characters. **Profiles (answer 8):** the start of the name is the profile's export name (section 3.5), default "Case Law Diary Main" (program display name and profile name), which the users of the profile may change to anything else.
- **Cleaning.** Every name that goes into a file name (Custom Name, Subject, Topic, Sub-topic) has these characters replaced by a hyphen `-`: `\ / : * ? " < > |` and control characters. Repeated spaces are collapsed to one, and leading or trailing spaces and dots are removed. The Settings preview tells you which replacements were made.
- **Date.** Today's date in the Settings date format, default `YYYY-MM-DD` (default, needs owner confirmation), in the Settings time zone (default Asia/Kolkata, default, needs owner confirmation).
- **Length (default, needs owner confirmation).** If the whole name without the extension would exceed 120 characters, the path in a Current View name is shortened: each segment is cut to 30 characters (at a word boundary if there is one after the 15th character, otherwise at the 30th), and if the name is still too long the middle segments are dropped and replaced by a single `-`, keeping the first and the last segment (for example `Arbitration, -, Fraud`). The full on-screen path is always printed in the document's page header, so nothing is lost from the document itself.
- **Same day, same name.** The app never overwrites and does not add times or counters. A second export on the same day produces the same name, and the browser adds its own (1), (2) suffix.

### 12.3 Contents, count and date

- Each document has a contents page listing the Subjects (or, for a Current View, the headings) it contains.
- Each document shows the **export date and the record count** for that document, so the count can be checked against the screen.
- Excludes Trash.

### 12.4 Options and other rules

- Numbers follow **Settings** formats at the moment of export.
- **Review markers.** For Review markers (amber) on Items **and on Sections** appear only if you tick "include review markers". The option applies to all three types.
- A separate **Backup** button gives the machine-readable restore file (not Word).
- **Round trip check** (milestone 6): export, then compare against the Word original: apart from deliberate formatting, text must match line for line.

## 13. Platform and proposed stack

**Decided (D1): build the Judgment Diary as a standalone app that can be plugged into a combined app later.** Your specification says this is one module of a combined web app, but that app is not confirmed to exist here. The stack below is for the standalone build. If a combined app later appears, its technology wins and this section must be revisited.

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

## 13a. Visual design

**Decision (owner, after reviewing four static mockups in `design/mockups/`):** Option D, "Chambers", for the whole app, with the Home page laid out like Option A, "Law Report".

- **Shell (Option D).** Warm off-white page, italic serif program name at top left, a "Home" link (the program picker) beside it, a small sans nav at right (the current page is dark with an oxblood underline), one hairline rule under the header, a large serif page title with a double rule under it, letter-spaced uppercase small labels, hairline row dividers, outlined secondary buttons and filled oxblood primary buttons.
- **Oxblood is used only for** primary actions, overruled or flagged items, and alerts. "For review" is a muted amber pill.
- **Reading pages (Option D).** Breadcrumb under the header (judgment-list pages only), Back/Subjects/Search small buttons, Contents column at left on wide screens, serif Topic headings with a rule, letter-spaced uppercase Sub-topic headings, italic Section headings, the Item number in its own hanging column, citations in italic grey, hairline dividers, Notes as "See also: link".
- **Home (Option A layout, Option D palette and type).** A centred narrow column: program name as the title, small-caps "Index of Subjects", a full-width search box that leads to Search, then Subjects as a two-column index (name at left, item count at right, hairline under each row; one column on phones). "Other Subjects" is the last entry, in italics, with its count of Other Subjects. A small meta line shows "N SUBJECTS · N ITEMS · N FOR REVIEW" instead of D's stat panels.
- **Design tokens.** All colours, font stacks and sizes are CSS custom properties in `static/css/tokens.css`. The shared header lives in `templates/base_suite.html` (blocks `program_name`, `program_switch`, `program_nav`, `toolbar`, `crumb_nav`, `content`, `extra_js`); `templates/base_suite_home.html` is the slim suite-level variant used by the Home picker and the Users screens; `templates/base.html` fills it for the Judgment Diary. Another program in the suite extends `base_suite.html` with its own name and nav.
- **Nav by role.** Subjects and Search for everyone; Backups for Admin only. Users is on the suite Home page, Admin only (D15). Review, Trash and Settings are omitted until those milestones exist.
- **Home (program picker).** `/` lists only the case law diary today (shown under its display name, D17); `/programs/` redirects to it. The suite name is undecided; "Chambers" appears only in the mockups and is not used in the app.
- **Font plan.** No web fonts are loaded (none could be downloaded). The CSS uses system serif and sans stacks. To self-host a font such as Source Serif 4, put the file in `static/fonts/` and add one `@font-face` block at the top of `static/css/tokens.css`, then name it first in `--font-serif`. Nothing else changes.
- **Accessibility.** Text is at least 16 px (reading text 18 px), tap targets at least 44 px, one column on phones with no sideways scrolling, visible focus outlines, muted text kept at AA contrast.

## 14. Decisions

All earlier open questions have been answered by the owner (N1 and N2 are closed by D9 and I10). They are recorded here with the owner's exact answers kept in `[Answer: ...]` form. Import questions are in `docs/IMPORT_ANALYSIS.md`, section 7, with the same numbering (shown below as "I1" to "I10").

**About the combined app and structure**

- **D1. The combined app.** Does the entry screen with other programs already exist? *Default: build the Judgment Diary as a standalone app that can be plugged in later.* [Answer: Yes, do the Default for now] **Decision: standalone app now.**
- **D2. Other Subjects structure** (named "Other Acts" when the owner answered; renamed by D8). Sub-topics (1, 2, 3) and Items sit directly under the Subject (no "General" Topic); an Other Subject holds either Topics or Sub-topics, not both. [Answer: Yes] **Decision: direct (section 2.1).**
- **D3. Exporting one Other Subject on its own.** Heading 1 alone. [Answer: Yes] **Decision: confirmed.**
- **D4. Nesting depth.** One level of Nested Items is enough. [Answer: Yes] **Decision: confirmed.**
- **D5. Notes ordering.** Notes after the Items of their parent and before the child headings. [Answer: Yes] **Decision: confirmed.**

**Behaviour**

- **D6. Restoring a deleted Subject whose name is now taken.** The app asks for a new name at that moment. [Answer: Yes] **Decision: rename-on-restore.**
- **D7. Edit history length.** At least 20 versions required; keep all. [Answer: Yes] **Decision: keep all history.**

**From the import analysis** (wording in `docs/IMPORT_ANALYSIS.md`, section 7):

- **I1. Other Subjects and the Topic level.** [Answer: Yes] Same as D2.
- **I2. Lines that are only a case name or only a citation.** [Answer: When in doubt, put as 'Text with no Citation', and flag for my later review] **Decision:** stored as Text with no Citation, For review with a reason.
- **I3. The two "(a)/(b)" lines.** [Answer: These should be Sections] **Decision:** they become Sections (section 8.1). Numbering consequence resolved by D9 (section 4); flagging by I10.
- **I4. Several typed (i), (ii) citations in one line.** [Answer: Keep them as one long citation, and flag for review] **Decision:** one Item, flagged.
- **I5. `[NO LONGER GOOD LAW]`.** [Answer: I do not need any coloured badge. Keep the wording in the text.] **Decision:** wording stays in the text, no badge.
- **I6. Search wording.** [Answer: Ok] **Decision:** curly and straight quotes alike; "&" distinct from "and".
- **I7. Blank paragraphs.** [Answer: Ok] **Decision:** skipped (11), listed in the report.
- **I8. Trailing colons on Topics and Sub-topics.** [Answer: Remove the colons] **Decision:** the stored name has no trailing colon; the original stays in `original_line`; all 19 changes are reported. This is a deliberate exception to the rule of never altering text, made on the owner's instruction.
- **I9. Two Sub-topics in a row.** [Answer: These are separate sub-topics, some of which may not have any items at present] **Decision:** separate Sub-topics, not flagged; empty Sub-topics are allowed.
- **I10. Flagging the two Sections.** (This answers N2.) [Answer: Ok, flag them for my review.] **Decision:** both Sections (`Ex Parte / Without Notice`, `Determining Jurisdiction`) are imported with `needs_review = Yes` and a review note. At import there are 261 review-marked records: 259 Items plus 2 Sections (the earlier figure of 259 did not include the 2 list restarts; see D-a).

Confirmed earlier: each Heading 1 is a Subject; Miscellaneous holds Other Subjects; Sub-topics are 1, 2, 3; Items are (i), (ii), (iii) in the Word file (shown as (1), (2), (3) in the Diary by D13); no footnotes.

**Decisions made after the first design** (the owner's wording kept verbatim; where the name "Other Acts" appears in a quotation it is the owner's original wording, and the name was changed by D8)

- **D8. Rename "Other Acts" to "Other Subjects".** [Answer: change the name 'Other Acts' to 'Other Subjects'.] **Decision:** renamed everywhere (documents, screens, code, tests, file names, export).
- **D9. Numbering of Sections and the Items after them.** (This answers N1, now closed.) [Answer: Your modification is correct. Perhaps, instead, give 'Sections' their own numbering system as well, and restart the numbering of items within them.] **Decision:** Sections have their own numbering format (Settings; default changed to (a), (b), (c) by D13) and each Section restarts the Item numbering at (1). Items before the first Section number as before. Section 4 has the full rules.
- **D10. Three types of Word export.** [Answer: I want three types of export to Word - (i) Full as 1 word document, (ii) Full, as separate word documents per Subject (though 'Other Subjects' will be kept together as a single subject), and (iii) Current View. The name of the word document will be as follows: [Custom Name, as modified in Settings] [(i) 'Full' if full, (ii) 'Name of Subject' if split subject wise, and (iii) 'Name of Subject, Topic, etc currently on screen', if for current view] [Today's Date].] **Decision:** section 12. The details not stated by the owner (zip delivery, manifest, file-name cleaning and length, date format, scope headings for Current View) are defaults, marked as needing owner confirmation.
- **D11. Custom Name setting.** [Answer: [Custom Name, as modified in Settings]] (part of the D10 answer). **Decision:** a per-user Settings text, default `Judgment Diary`, with the rules and live file-name preview in section 5.11.
- **D12. Three roles: Admin, Editor, Reader.** The owner asked whether the Admin can use the diary like a regular user (yes: Admin is an ordinary user plus the Users, Backups and Restore screens). The spec does not say whether other users may edit, so three roles were proposed: Admin (everything), Editor (read and edit), Reader (read only, the safe default for new accounts). [Answer: Yes, do that.] **Decision:** built in Milestone 0 (section 9.6). The permissions table in section 9.6 is a set of defaults: what Readers may export, whether Readers see the Trash, History and Review list, and that permanent delete and Import are Admin only are proposals needing owner confirmation (question 5).
- **D13. Section and Item numbering; shortcuts.** (Answers open question 1 and the shortcut question.) [Answer: "Make section headers (a) Name. Change the numbering for Items to (1), (2)... Keep both shortcuts."] **Decision:** the default Section format is (a), (b), (c) (small letter in brackets, no full stop, e.g. "(a) Name"). The default Item and Nested Item format is (1), (2), (3). Existing Settings rows still holding the old defaults are updated by a data migration; rows where a format was chosen deliberately are untouched. Multi-Item citations stay (a), (b), (c) per the spec, which now matches the Section style. The Word file's own (i), (ii) numbering is unchanged, and the importer still recognises Items by it. Both shortcut sets are kept: Alt+G / Alt+H and Ctrl+Alt+G / Ctrl+Alt+H (Option on a Mac); section 5.10.
- **D14. Visual design.** [Answer: "I like Option D. But, redesign the Home page to be formatted like Option A."] **Decision:** Option D "Chambers" everywhere, Home laid out like Option A (section 13a).
- **D15. Chambers follow-up (owner's review of PR #5).** Owner's words, item by item, with the defaults chosen:
  - (2) "Other Subjects should NOT be on the top bar." Removed from the nav; still the last entry of the Subjects index.
  - (4) "Move 'Users' to the 'Switch Program' Page - rename 'Switch Programs to 'Home'. Rename the existing 'Home' to 'Subjects'." The picker is the suite Home at `/` (URL name `home`); the Subject index is at `/subjects/` (name `subjects`); `/programs/` redirects to `/`. "Subjects" replaces "Home" in the diary nav, toolbar button, breadcrumb root, page title, Back fallback and docs. Login lands on Home; the Milestone 4 per-user Opening page setting will override this. Alt+H and Ctrl+Alt+H go to the suite Home; the in-diary button is "Subjects". Users is on Home (Admin only). Default: Backups stay in the diary nav for Admin only, because backups currently cover diary data.
  - (5) "The user name on the top row should only display the User Name, not its role." Header shows the username only; the Users screen still shows roles.
  - (6) "When in the 'Home' screen (i.e. the program picker), display the following in the top row - Users, Name of User, and Log Out." Home uses `base_suite_home.html`: Users (Admin only), name, Log out; no diary nav and no toolbar. Default: the Users screens use the same slim header, and the program name links to Home.
  - (7) "Do NOT show the directory path at all times (i.e., on the Search page, etc), only show it when viewing the Judgment lists." The breadcrumb appears only on Subject contents and the reading views; the whole element is omitted elsewhere (block `crumb_nav`). Its root reads "Subjects". Default: Other Subjects list has no breadcrumb.
  - (8) "When viewing the table of contents, allow me to expand / contract all or individual Subjects / Topics / etc." Each Topic with Sub-topics can be expanded or collapsed, plus Expand all / Collapse all. Defaults: on reading pages the current Topic is open and others closed; on the Subject contents page all open; the choice is remembered per Subject in the browser. The Subjects index is flat so it has nothing to expand.
  - (9) "When clicking on a subject for the first time, and when the program only shows the Table of Contents, format it in such a manner that it is already arranged in the Side Panel (in the same manner as if Text was open)." Subject contents uses the reading layout: Contents in the left panel, the Subject title, "View whole Subject" and a hint on the right. Default: on phones the Contents list is shown full width on that page and the Contents button is hidden.
  - (3) "In Backups, allow me to resize the column widths." Drag the column border (or focus the handle and use the arrow keys); widths are remembered per table in the browser; "Reset column widths" restores them. Tables scroll sideways inside their own box on phones.
  - (1) Excel backup and (10) Split View are answered separately; Split View stays in Milestone 7 (section 5.9).
- **D16. Header and navigation tidy-up (owner's second review of PR #5).** Owner's words, with the defaults chosen:
  - (1) "Move 'Back' to the top row." A small "&larr; Back" button (44px tap target) sits at the left of the top row, before the program name, on every signed-in page including Home, Users and Backups. Default: the separate toolbar row is removed; Subjects and Search remain in the program nav, and the breadcrumb row appears only on Subject contents and the reading views.
  - (2) "Remove the buttons for view whole subject, view, this topic, and View this Sub-Topic, as they are redundant on account of the directory view." The three buttons are gone from the reading views and the Subject contents page. Defaults: the Subject name in the breadcrumb and at the top of the Contents panel opens the whole-Subject view; Topic and Sub-topic links in Contents open those scopes; the hint reads "Choose a Topic or Sub-topic from Contents, or click the Subject name to read the whole Subject."; the phone Contents button stays.
  - (3) "Remove the 'Home' Button. Let me click the program name to go to Home." The Home link is removed; the program name is a link to Home (title and label "Go to Home"), underlined and in oxblood on hover or focus. Alt+H and Ctrl+Alt+H still go to Home.
- **D17. Renameable program and Home names (owner's second review of PR #5, items 4 and 5).** Owner's words: (4) "When on the home page, display 'Home' in place of a program name'. In Settings," (the message was cut off after "In Settings,"; the default is that nothing more is required than item 5) and (5) "In 'Home' also add a 'Settings page. In 'Settings, allow me to rename the individual sub-programs, as also the 'Home' page - for now, rename 'Judgment Diary' as 'Case Law Diary'". Defaults chosen:
  - On Home, Users and Settings the name in the top row shows the Home page name (default `Home`); inside the case law diary it shows the program name (default `Case Law Diary`, renamed from `Judgment Diary`).
  - **Settings** (URL name `settings`, `/settings/`) is a suite-level page linked next to Users on the Home top row. It is **Admin only**, because the names are shared by every user (the per-user Settings in section 5.11 are separate and come later). It lets the Admin rename the Home page and the case law diary.
  - Rules: required; surrounding and repeated spaces are removed; at most 60 characters; the Home page and each program must have different names (compared ignoring capitals).
  - Names are stored in a small table (`accounts.SuiteName`: `key`, `display_name`, created and updated times) with keys `home` and `diary`. A missing row means the built-in default, so nothing needs seeding. The table is part of every backup; an older backup file that lacks it still restores, and the names then return to the defaults.
  - **Only display names change.** The internal identifiers stay as they are: the `diary` app and modules, URL names, the repository name and the backup file format marker.
  - The names appear in the program header, the Home program list, and every page title.
  - **Export Custom Name default.** The per-user default (section 5.11, Milestones 4 and 6) was `Judgment Diary` and is now `Case Law Diary`, following the program's display name. Existing settings that still hold the old default are updated; a Custom Name a person has typed is left alone. Renaming the program later does not change Custom Names already saved.

**Open questions for the owner** (each has a default that is used unless you say otherwise)

1. **Section number style.** Answered (D13): (a), (b), (c). Other choices are in Settings, including "Section 1, Section 2".
2. **Date in file names.** Default: 2026-11-01 style (year-month-day), in Asia/Kolkata time. Other choices: 01-11-2026 or 1 November 2026.
3. **Long file names.** Default: if a Current View name would exceed 120 characters, each part is cut to 30 characters and, if still too long, middle parts are replaced by `-`. The full path is always inside the document.
4. **Current View of a Topic or Sub-topic.** Default: the Topic or Sub-topic heading becomes the top heading (Heading 1) and keeps its on-screen letter or number.
5. **What a Reader may do.** Default (section 9.6): a Reader can read, search, see the Review list and export the Current View, but cannot see Trash or History, cannot do the two Full exports, and cannot edit. Editors can do everything except permanent delete from Trash and Import, which only an Admin can do.

**Profiles: decisions and open questions** (the owner's words kept verbatim; section 3.5)

- **Owner's choice.** Profiles are separate data spaces, "B". [Answer: I meant B. Users will only have access to 1 profile per sub-progeam (such as the Judgment Doary).] **Decision:** separate data space per profile, one profile per user per program.
- Answered by the owner (see section 3.5, "Owner answers"): P1 Admin only; P4 separate Role per profile; P5 Admin cannot look into other profiles; P8 settings per user (answer 4); P9 first profile "Main"; P10 whole-database backups; P14 deleted profiles are recoverable for 30 days; export name per profile (answer 8). P6 was changed by the owner: a program with no profile is hidden, not greyed out.
- Still **DEFAULT** unless the owner says otherwise:
  1. **P2.** Profile name unique per program among live profiles, ignoring case.
  2. **P3.** One membership per user per program; several users may share a profile.
  3. **P7.** Every diary record carries its profile; a Subject name may repeat across profiles; links never cross profiles.
  4. **P11.** The diary header shows "Case Law Diary · Main".
  5. **P12.** The Milestone 2 import goes into a chosen profile.
  6. **P13.** Backup files are trusted Admin input: restore uses raw saves, so the cross-profile link check and the membership `program` copy are not re-run on file contents (uploads are Admin-only).
  7. **P15.** `check_profile` reads each parent on every save (one query per uncached parent). Acceptable for the UI; the Milestone 2 import should set parents from objects it already holds, or bulk-create after validating once.

**Questions for the owner (profiles).** The eight earlier questions are answered. New ones, each with the default that is used unless you say otherwise:

1. **Recovery window.** Default: 30 days, then the nightly job removes the profile for good (only after a successful backup). Do you want a different number of days?
2. **Who may change the export name.** Default: an Editor of the profile; a Reader can only view it. Anyone else?
3. **Export name and the Custom Name.** Default: the profile's export name replaces the personal Custom Name at the start of file names. Do you want to keep both?
4. **Header (P11).** Default: "Case Law Diary · Main", the profile name in small type. Do you want it hidden when there is only one profile?
5. **Admin without a profile.** Default: an Admin with no profile in a program does not see that program on Home either. Do you want Admins to always see every program?

**Milestone 2 review round: defaults NOT asked of the owner (apply unless the owner says otherwise).** Each is marked DEFAULT pending owner confirmation.

- **D-a. Word list restarts are flagged.** DEFAULT pending owner confirmation. This follows the originally agreed rule (IMPORT_ANALYSIS pattern 19). The two Items where a second Word list starts inside one Sub-topic (`para-1033`, `para-1356`) get `needs_review = Yes` and the note "Word list restarted here; the Diary numbers this group continuously." Totals become 259 flagged Items (257 imported whole + 2 restarts) and 261 review-marked records (259 + 2 Sections); 691 Items are clean. The earlier statement that there is "no renumbering difference" was wrong: Word shows (i) / (i),(ii) in those groups and the Diary numbers them (1),(2),(3).
- **D-b. Import backups.** DEFAULT pending owner confirmation. Backups made by the import have their own kinds, "Before import" (`pre_import`) and "After import" (`post_import`). Automatic retention pruning never removes them; an Admin deletes them on the Backups screen after a confirmation (only these two kinds can be deleted there). A failed "Before import" backup aborts the import with nothing written; a failed "After import" backup is a visible warning. The import output tells the Admin to download the "Before import" backup. Backups are stored in the same database, so they do not protect against losing that database; the off-site copy on the roadmap does.
- **D-c. Citation formatting.** DEFAULT pending owner confirmation. The Citation stays plain text shown in italics, so italics on the citation side are expected and not listed. Bold or underline (or other non-italic formatting) on the citation side is listed line by line in the dry run and reconciliation and flags the Item with the note "Citation had bold/underline in Word that a plain Citation cannot hold" (other formatting: "Citation had other formatting in Word (colour, size and so on) that a plain Citation cannot hold."). On the real file this affects 0 lines: 688 of the 693 split lines have italics only on the citation side and 5 have no formatting.
- **D-d. A profile must be empty to import into.** DEFAULT pending owner confirmation. Any live diary record that is not from an earlier import of this file blocks the import (sample data included); nothing is merged.
- **D-e. The import is run from the Render Shell.** DEFAULT pending owner confirmation. The screen performs about 2,500 saves, two backups and a reconciliation in one request, which can pass Render's 60-second request limit. The screen therefore does the dry run and the reconciliation only, and shows the exact Shell command. A command run has no such limit.

## Round 3: Case Law Diary under /caselaw/

- **Owner (item 9):** "I will be creating three sub-programs - Caselaw (i.e. this one), Fees, and Investments. Each one should ideally be housed in separate pages. So, in this case, opening Case Law Diary > Subjects will take you to /caselaw/subjects."
- **Decision (defaults, pending owner confirmation).** Every Case Law Diary page is under `/caselaw/` (`diary/urls.py` is included at `caselaw/`). Suite pages stay at the root: Home `/`, `/users/`, `/profiles/`, `/settings/`, `/login/`, `/logout/`, `/healthz/`, and `/backups/` (backups are suite level). The old root diary URLs (`/subjects/`, `/subjects/<id>/`, `/subjects/<id>/read/`, `/topics/<id>/read/`, `/subtopics/<id>/read/`, `/other-subjects/`, `/search/`, `/review/`, `/import/`, `/profile-settings/`) answer with a permanent (301) redirect to the new address, keeping the query string. No Django app namespace is used: URL names stay global, so every `{% url %}` and `reverse()` is unchanged. Backups is linked from the Home top row (Admin only) and is removed from the diary nav; the Backups screens use the suite header. The program key stays `diary` and the display name "Case Law Diary".

### Round 3: reader panel, Back/Forward, Review (items 2, 3, 5, 6, 7, 8, 12)

- **Item 2. Back and Forward.** [Answer: "The 'back' button should only take you back within this web service itself. It should not, for example, take you back to another website or even the browser landing page. Keep a forward button too. Put both buttons to the right of the program name."] **Decision (details are defaults, pending owner confirmation):** Back and Forward sit immediately right of the program name in every header (suite and program). Each browser tab keeps its own list of the site pages it has shown, in `sessionStorage` (`quill.nav`), so a new tab starts fresh. Only same-origin paths are stored or followed; the code never calls `history.back()`, so the buttons cannot leave the site. A reload or a re-displayed form (same address) adds nothing; a new page after Back drops the forward pages; the list holds 50 pages. With no earlier page Back goes to suite Home; Back is disabled only on a first page that already is Home. Forward is disabled at the end of the list. The browser's own Back and Forward are untouched and the list follows them when the page is next to the current one. Buttons are at least 44px high, with aria-labels.
- **Item 3. Width of the panel.** [Answer: "Let me adjust the width of the 'Contents' Table."] **Decision (defaults):** on screens 900px and wider the panel's right edge is a drag handle (mouse and touch) and a focusable separator (Left/Right arrows, 16px a step; Home resets). Minimum 192px, maximum 640px, default 256px. The width is kept in `localStorage` (`quill.panelwidth`). Double-click the handle or press "Reset width" to go back. Not offered on phones, where the panel slides over the page.
- **Item 5. Subjects.** [Answer: "In the Contents, replace the word 'Contents' with 'Subjects'. If I click on 'Subjects', show a list of all Subjects in the Contents view, and if I click on any Subject take me to the Topic view for that subject."] **Decision (defaults for the details):** the panel heading reads "Subjects". Clicking it swaps the panel to every Subject of the profile (main Subjects, then Other Subjects, each in its set order); each links to that Subject's contents page (its Topic tree). The current Subject is highlighted and a "‹ Topics" button returns to its Topic tree. Without JavaScript the heading is a link to the Subjects index. The phone "Contents" button is renamed "Subjects". The hint on the contents page now says "from the list".
- **Item 6. Full stops.** [Answer: "In the 'Contents' Table, add a '.' After the auto-numbered letter or number."] **Decision:** the panel shows "A. Arbitrability", "1. Fraud". Only in the panel; headings in the reading text are unchanged. Default: labels that already end in a bracket (such as "(a)") or are a bullet are left alone.
- **Item 7. Search button.** [Answer: "On the 'Subjects' page, the 'Search' button is broken over two lines, so that 'Searc' is on one line and 'h' on another. Fix that."] **Decision:** all buttons are `white-space: nowrap`, and the Search button has a minimum width and does not shrink. Checked at 390px.
- **Item 8. Review.** [Answer: "Add a feature where I can view a list items that need review."] **Decision:** the Review list already existed (section 5.12, route `review_list`) but was reachable only from the small "for review" count on the Subjects page. It is now a "Review" link in the diary nav for everyone with a profile. It lists every review-marked Item and Section of the profile with its full path, the note, a link that opens it in context, and a count. Default addition: a Subject filter (`?subject=<id>`) with a count per Subject; an unknown value shows all.
- **Item 12. Kind column.** [Answer: "In 'Review List', Expand 'KIND' a bit, so that it is in one line."] **Decision:** the Kind column does not wrap and has a minimum width; on phones the table scrolls sideways inside its own box instead of the page.
- **Item 4. Times in IST.** [Answer: "In Backup, the time mentioned in 'When' (UTC) seems to be IST. Change it from 'When' to Time, and to IST from UTC if it is in fact in IST. Similarly, with History. If possible, I would like all times to be in IST."] **Finding:** the owner is right. `TIME_ZONE` is Asia/Kolkata and `USE_TZ` is on, so times are stored in UTC in the database but every template already showed them in IST; only the labels said UTC. **Decision (defaults for the details):** the column headings are "Time (IST)" in both Backups tables and in the Permanent removal log on Profiles ("Deleted (IST)" for the deleted-profile date); the texts on the restore preview, the delete-backup page and the failed-backup banner say IST. Everything else that prints a time is converted with `timezone.localtime`: the import dry-run and reconciliation reports ("... IST"), and the time stamp in backup file names and downloaded report names (for example `judgment-diary-backup-20260106-013000-manual.json.gz` is 01:30 IST); the file name suffix is unchanged. The database and the backup file contents still hold UTC (the `created_at` inside a backup file is unchanged), because that is exact and unambiguous. A test stores a UTC time and checks that the page shows the IST wall-clock time with "IST".
- **Item 11. Delete all data in a profile.** [Answer: "Make it possible to delete all data in a profile, as otherwise I will not be able to restore from Word into a profile which already has data, without deleting the entire profile."] **Decision (defaults for the details, pending owner confirmation):** Admin only, on the Profiles screen ("Delete all data" next to Rename and Delete; URL `/profiles/<id>/clear/`). It shows a preview with the row count of every record type (Subjects, Topics, Sub-topics, Sections, Items, Cases, Notes, Note links, Version history), counting trashed and imported rows too. The Admin must type the profile's name exactly. A dedicated backup of kind `pre_clear` ("Before clearing profile") is made and committed first; if it fails nothing is deleted. Like the import backups it is never removed by automatic pruning and an Admin may delete it on the Backups screen. The deletion is one transaction with the Profile row locked (`select_for_update(nowait=True)`, the same lock the Word import takes), so it is refused with a message while an import into that profile is running. It deletes every diary row of that profile, including trashed and `import_ref` rows and the version history, and nothing of any other profile. The profile, its name, export name and members stay. The counts are written to the Permanent removal log (a `PurgeLog` row) and the backup to the backup log. Afterwards the profile has no diary rows, so the importer accepts it as empty (decision D-d).
- **URL slug.** The Case Law Diary slug is `caselaw`. The two future programs, Fees and Investments, will get `/fees/` and `/investments/` in the same way (not built yet; recorded so the names are not reused).
