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

## Round 4: Contents panel, login, program top bar

Owner words are quoted exactly. Details marked DEFAULT are mine and pending owner confirmation.

**Confirmed by the owner in this round.** Yes to both open questions. Backup download file names use IST timestamps (confirmed). "History" in the earlier IST request meant the Backups log and the Profiles purge log (confirmed). The ui-round-3 defaults the owner did not object to (panel Back/Forward details, Review filter, delete-all-data details, URL redirects) are treated as confirmed.

- **Item 1a.** [Owner: "reduce the line spacing between header items which spill across lines."] Decision: panel links use `line-height: 1.25`; padding keeps every row at least 44px tall for touch. DEFAULT: padding stays so one-line rows are unchanged.
- **Item 1b.** [Owner: "replace the Expand All and Contract All buttons, with buttons with outward and inward facing arrows, and keep them on the same line as the 'Subject'"] Decision: two icon buttons (outward arrows = Expand all, inward arrows = Collapse all), 44px wide, each with `title` and `aria-label`, in the same row as the Subject name. DEFAULT: the inward arrows are called "Collapse all" (the owner wrote "Contract All").
- **Item 1c.** [Owner: "The spacing is a bit off. The parent headers should not be to the right of the child headers. But at the same time, the table of contents should not become so wide as to reduce space on the main screen."] Decision: hanging indent, so the number sits in a fixed-width column and long text wraps under the text, not under the number. Children are indented about 1rem more than their parent's text start, so a parent label is never right of a child's. DEFAULT width 280px (17.5rem), was 256px; resizing (192 to 640px) is kept.
- **Item 1d.** [Owner: "When viewing 'All subjects', keep a bit more space before 'Other Subjects' to show the difference. Perhaps a line to demarcate it?"] Decision: "Other Subjects" is a labelled group with extra space above and a divider line.
- **Item 1e.** [Owner: "Add a button at the top called 'view in context'. When this is ticked, the entire Subject will always be visible, and selecting anything on the Table of Contents will simply take you to that entry. Tell me what will happen if I untick this - what will then show up on the page?"] Decision: a "All" tick at the top of the panel. Ticked: every Topic or Sub-topic link opens the whole Subject and jumps to that entry. Unticked: a link shows only that Topic or Sub-topic (the earlier behaviour), and if you were at a spot in the whole Subject you are taken to the Topic or Sub-topic you were reading. The Subject contents page, when ticked, links into the whole Subject reading view. The choice is kept in this browser's `localStorage` (`quill.incontext`) and in a cookie (`quill_in_context`) the server reads to choose the page; the script restores the cookie from `localStorage` if needed. DEFAULT: ticked (on) for everyone until it is unticked; a missing cookie counts as on, unticking writes `0`. The tick is hidden until the script runs (it does nothing without JavaScript). The script restores the cookie from `localStorage` once per tab session, so blocked cookies cannot cause a reload loop. Moving to another entry inside the whole Subject opens its Topic in the panel and scrolls the panel to it.
- **Item 1f.** [Owner: "By default, it should always be on 'Collapse all'."] Decision: every Topic is collapsed by default on every page, including the Subject contents page. On reading pages only the path to the current entry is open. Your own open/close choices are remembered per Subject in `localStorage`. "Collapse all" returns to the default and forgets the saved choices.
- **Item 1g.** [Owner: "The dots after the letters & numbers for auto-numbering, which appear in the Table of Contents, should also show in the main body."] Decision: Topic, Sub-topic and Section labels in the body use the same dotted form as the panel (labels ending in a bracket such as "(a)" are left alone, as in the panel). Check of the Word export spec (section 12): it does not mention full stops on auto-numbers, so the export is unchanged; DEFAULT: the export follows the number formats in Settings, not the screen dots. Open question for the owner below.
- **Item 1h.** [Owner: "At present, the Table of Contents is in a limited box on the side, which runs out of space eventually, whereas the main text is free length and continues indefinitely. So, it is possible that I can keep scrolling down a page on the right with the text, and see no space - maybe this is a fix for later, but I would like the Table of Contents to be persistent. Tell me how you would do this, and if I am making sense."] Decision: on wide screens (900px and up) the panel is `position: sticky` under the top, `max-height: calc(100vh - 5rem)` with its own scrollbar, so it stays on screen while the text scrolls, and the current entry is scrolled into view within the panel on load. No ancestor has overflow that would break sticky, and the grid uses `align-items: start`. On phones the panel stays a slide-over opened by the Subjects button.
- **Item 2.** [Owner: "In the Main Log In page, It should not say 'Case Law Diary'. It should say nothing. Just Log In."] Decision: the login page shows only "Log in".
- **Item 3.** [Owner: "Remove the user name on the Top Bar, when viewing inside the sub-program."] Decision: the user name is not shown in the header inside Case Law Diary; the suite pages still show it.
- **Item 10 (architecture).** [Owner: "for now we will do number 1 (separate modules in one website, and revisit later when adding any new sub-programs)."] Decision: option 1, separate modules in one website. Each program is its own Django app with its own tables and URL prefix (`/caselaw/`, later `/fees/`, `/investments/`). The shared suite core is Home, Users, Profiles, Settings, Backups and login. Rules: no imports between programs (only from the shared core); each program has its own tests; each can be switched off independently. Revisit when adding the next sub-program.
- **Open questions (defaults apply).** 1. Should the Word export also print the full stops? Default: no. 2. Should "All" start ticked? Default: yes (as briefed); say so if you would rather it start unticked. 3. Is 280px a good starting width? Default: yes.

- **Round 4 review fixes.** The panel's resize handle sits on a fixed outer box and only the inner list scrolls, so the handle stays in place. Case labels such as (i) end in a bracket, so they take no full stop by design.

### Round 4 follow-ups

- "See also" links to an Item or Section point at the whole-Subject page with the item anchor, so the "All" redirect no longer drops the target.
- The "All" checkbox stays hidden when scripts are off.

### Round 4 follow-ups, second pass (owner tested on the live site)

- **Back and Forward.** [Owner: "Make the 'back' and 'forwards' buttons just buttons with arrows and without text."] Decision: icon-only buttons (SVG arrows), still right of the program name on every header, 44px square, with `aria-label` and `title` "Back" / "Forward" and the same disabled styling.
- **All.** [Owner: "The button for 'View in Context' should be in the same line as the directory path, but on the extreme right."] Decision: the checkbox moved from the panel to the breadcrumb row, pushed to the right end. On narrow screens it wraps to its own line, still right-aligned and visible on phones. DEFAULT: it is not shown on a Subject contents page that has no Topics (no panel there).
- **Panel heading.** [Owner: "Remove 'subjects' at the top of the Table of Contents. In the directory path, clicking 'Subjects' will have the same result that it would have had if I had clicked 'Subjects' as appearing on the top of the Table of Contents."] Decision: the heading is removed; Expand all / Collapse all stay at the top of the panel and "‹ Topics" stays on the all-Subjects list. The breadcrumb "Subjects" link switches the panel to the list of every Subject without leaving the page (on phones it opens the slide-over with the list). It keeps `href` to the Subjects index as the no-JavaScript fallback, and has `aria-controls="panel-subjects"` and `aria-expanded`. Clicking it again, with the list showing, returns to the Topics. On pages without a panel it is a normal link.
- **Sticky panel.** [Owner: "The fix you have stated to the Panel at 'h' above ('Panel stays on screen') is not working."] Root cause: in the wide-screen rule `.contents-panel { position: sticky; top: 4rem; inset: auto; ... }` the shorthand `inset: auto` came after `top: 4rem` and reset `top` to `auto`, so the panel never stuck. Fix: `inset: auto; top: 4rem`. Also set `overflow: visible` (the base slide-over rule has `overflow-y: auto`) and `align-self: start`. Checked in headless Chromium at 1280x800: before the fix the panel top moved to -2865px after scrolling 3000px; after, it stays at 64px, and the inner list scrolls on its own.

## Milestone 3, sub-release 3a: service layer (no screens yet)

Everything below is a **DEFAULT, not confirmed by the owner**. The code is in `diary/services/` (no views or templates); screens arrive in 3b to 3d and call these functions. Role checks (Editor or Admin; permanent delete Admin only) are made in the view layer, not here.

- **M3-1. One transaction per action.** Every public function runs in `transaction.atomic()`, finds records only inside the given profile (another profile's id is "not found", never a different error), locks the rows it changes, bumps `version` by one and writes a full VersionHistory snapshot for every record it touches.
- **M3-2. Stale saves.** Edit, delete, move, restore and convert take `expected_version`. A mismatch raises `Conflict`, which carries the version numbers, the stored snapshot (theirs) and the attempted changes (mine). A repeat of something already done (the same edit, deleting a deleted record, restoring a live one, the same move, converting to the type it already has) changes nothing and is not a conflict.
- **M3-3. Trash batches.** New table `diary.TrashBatch` (id, profile, root type and id, label, created by and at) and a `delete_batch` column on every record table. Deleting a record trashes it and all its live descendants under one new batch id. Records already in Trash keep their earlier batch. Restoring a record restores that record and the part of its batch below it; an Item restored alone also brings back its own Cases and Notes. The live siblings keep their positions when something is deleted (numbers come from the order, so gaps never show); restore puts the record back before the first live sibling with a higher position and then renumbers the sequence 1 to n.
- **M3-4. Restore edge cases.** Parent or any ancestor in Trash: `ParentInTrash` lists the chain; with `restore_parents=True` each ancestor is restored on its own (not the rest of its batch). A Subject (per profile) or Topic (per Subject) name already used by a live record: `NameClash` with a suggestion ("Name (restored)"); the caller then passes `new_name`. A Case cannot come back under an Item that is no longer a Multi-Item, nor an Item under a Nested Item that is no longer nested. A Topic cannot come back into a Subject that now holds direct Sub-topics (and the reverse).
- **M3-5. Permanent delete.** Only for records in Trash. It is refused while any Note link from outside the deleted tree points at something in it, whether that link is live or itself in Trash; the refusal lists each link (link, Note, target, live or not). Links inside the tree go with it. The version history is never deleted. IDs are not reused (database sequences).
- **M3-6. Positions.** Items, Nested Items and Sections of one parent share one sequence; Sections sort before Items on a tie. Notes, Cases, Topics, Sub-topics and the children of a Nested Item each have their own sequence, and Subjects use `landing_position` or `other_acts_position` by group. Create, move, reorder and restore renumber their sequence 1 to n (siblings that shift get a "reorder" history row). Moves are refused with a reason when they cross profiles, put a heading inside itself or its own contents, put a Topic or Sub-topic where the Subject holds the other kind, nest more than one level, or put a Multi-Item or Nested Item under a Nested Item.
- **M3-7. Previews.** `preview_move` and `preview_delete` list the Items, Sections, Topics or Cases whose generated number changes (before and after, using the user's number formats), and `preview_delete` also says how many records go to Trash. Previews write nothing.
- **M3-8. Undo groups.** Every action stamps its history rows with one `group` id (new column on VersionHistory). `undo_group` reverses the whole action by restoring each record to the version before the action (a record the action created is moved to Trash). It only reverses the user's own actions; the view layer keeps the list of group ids for the session. If a record changed after the action it raises `UndoWarning` (list of records) unless `force=True`; if another user changed it, it is refused. The undo is itself an action with its own group, so undoing it is a redo. Names are not silently changed: if the old name is taken by another live Subject or Topic, Undo stops with `NameClash` and changes nothing.
- **M3-9. History restore.** `restore_version` copies back only the content fields (name, text, citation, flag, review marker, comment). Where a record sits and what type of Item it is are not changed; restoring a version from before a conversion is refused with an explanation (use Undo, or convert back first).
- **M3-10. Conversions.** Implemented as in section 6, with these choices. Multi to Item joins the Cases as `(a) Citation - comment; (b) Citation`; a single Case gives just its citation. The joined text is refused if over 1,000 characters. Comments are flattened to plain text, so the warning "Formatting and line breaks in comments will be lost." must be accepted (`accept_warnings=True`). Cases that disappear in a conversion go to Trash in a batch labelled "Removed by conversion", and every record written has change kind "convert" under one Undo group. Nested to Item or Multi with children needs an explicit choice, "keep" (children move to sit directly after it, in order) or "fold". Folding is refused (and "keep" offered) when a child has a flag, a For review marker or a Note. The database already forbids a Multi-Item or Nested Item under a Nested Item and a Section under an Item, so those parts of the refusal rule can never occur; they are enforced by the structure.
- **M3-11. Validation.** Names of Subjects, Topics and Sub-topics are required, tidied (surrounding and repeated spaces removed) and at most 300 characters; Subject names are unique among live Subjects of a profile ignoring case; the citation is one line of at most 1,000 characters; a Multi-Item has no citation. Content rules are checked on create, edit, history restore and convert only, so imported or older data can always be moved, deleted and restored.
- **M3-12. Backups.** `diary.TrashBatch` is in the backup registry as an optional model (an older backup has none, so a restore leaves the table empty), and an older file without `delete_batch` or `group` loads with empty values.

### Milestone 3, sub-release 3b (edit mode for headings and Items)

All defaults, not confirmed by the owner.

- **M3-13. Edit mode.** Edit mode is a page state, not a setting: it is on when the address has `?edit=1` and the user is an Editor of the profile (Admins follow their membership role). The reading view, the Subjects page and the Other Subjects page show an "Edit mode" / "Done editing" link only to Editors. Readers never get the controls, and every edit address returns 403 for them (also for GET), 405 for an Editor's GET, and 404 for another profile's ids or an unknown record type. Every edit is a POST with the CSRF token; the views in `diary/views_edit.py` only read the form, call `diary/services/` and redirect back to a `next` address that must be on this site (otherwise the Subjects page).
- **M3-14. What the controls do.** Each heading, Section, Item and Subject has an edit bar: drag handle, Up, Down, "Move to...", Delete, and where they apply Rename, Add and "Move to Other Subjects / Show on landing page". Up and Down work without JavaScript; the drag handle (`static/js/edit-mode.js`, pointer events, no library) is an extra. Dropping sends the 0-based index among the other records of the same run (Items, Nested Items and Sections of one parent share a run; Topics, Sub-topics and each Subject list have their own) and the server does the renumbering. Delete and "Move to..." always show a preview page first (the numbers that change, and for Delete how many records go to Trash) and need a second press; Up, Down and drop do not, because they are small and can be undone by moving back. The tree picker lists every Subject, Topic, Sub-topic and Nested Item of the profile; places that would break a rule (itself, something below it, wrong type) are shown greyed out, and the service still refuses anything else with a message. Adding an Item here takes plain text (turned into paragraphs) and a citation; the full Item editor is sub-release 3c. Items are not renamed here.
- **M3-15. Stale pages.** Every edit form carries the record's version. A stale version shows a plain conflict page (HTTP 409) that says what was not saved and links back to reload; it shows what the Editor tried to save but does not offer a merge. The two-versions screen with a choice arrives with 3c/3d.
- **M3-16. Subjects between lists.** `set_landing` in `diary/services/records.py` moves a Subject between the landing page list and Other Subjects: it goes to the end of the other list, the list it left closes up, and repeating the choice changes nothing.

### Milestone 3, sub-release 3c (Item editor, conversion screen, review switch)

All defaults, not confirmed by the owner.

- **M3-17. The rich text box.** TipTap could not be installed here, so `static/js/richtext-editor.js` is a small vanilla `contenteditable` box: Bold, Italic, Underline buttons and Ctrl/Cmd+B, I, U, Enter for a paragraph, Shift+Enter for a line break. Pasted content is cleaned to p, br, b, i, u before it goes in (Word's bold, italic and underline styles on spans are kept, everything else is dropped). The cleaned HTML is written to a hidden textarea that the form posts. Without the script the textarea shows and takes HTML. The server (`diary/richtext.py`, called by the service layer) is the authority and cleans again.
- **M3-18. The Item editor.** `GET /caselaw/edit/item/<id>/` (Editors only; Readers 403, another profile's or a trashed Item 404) is one form: text, Citation (one line; absent for a Multi-Item), flag (none, overruled, doubted, other) and short flag text, the For review switch and note, and for a Multi-Item the Cases list (add, remove, Up/Down, each with a citation and an optional rich comment). One Save posts the whole form with the version of the Item and of each Case, inside one database transaction: if any part is stale or refused nothing is saved. A stale save shows the 409 conflict page listing everything that was typed, so nothing is lost; the keep mine / keep theirs / merge choice is sub-release 3d. A refused value (for example a citation over 1,000 characters) shows the form again with the message and what was typed. Cases left out of the form are moved to the Trash; the order of the list is the new order. The flag text is cleared when the flag is "none". The page also shows created and last edited time (IST) and who, and for imported records a read-only panel with the original Word line. History is a Trash/History screen of sub-release 3d and is not linked yet.
- **M3-19. Change to.** Each other type has a button on the editor (none for an Item under a Nested Item). It opens a preview (before and after side by side) built from `preview_conversion`; nothing changes until the Editor presses the confirm button. Warnings (Multi-Item to Item: "Formatting and line breaks in comments will be lost.") change the button to "I understand, change to ..." and are sent as `accept=1`. A Nested Item with Items beneath first asks keep or fold; the fold choice is greyed out with the reasons when the service would refuse it, and a refusal shows the reasons and no confirm button. Each conversion is one Undo group in the service layer; a stale version shows the conflict page.
- **M3-20. Review marker switch.** In Edit mode every Item and Section edit bar has one button, "Mark for review" or "Clear review", and a "Review note" box that marks it with a note (the Sections' note goes through the same service call). Clearing also clears the note (the history keeps it). Like all edit controls it shows only in Edit mode to Editors. Addresses: `edit_item`, `edit_item_convert`, `edit_review` in `diary/views_item.py`.

### Milestone 3, sub-release 3d (Trash, History, Undo, conflict screen)

All defaults, not confirmed by the owner.

- **M3-21. Trash screen.** `GET /caselaw/trash/` (`diary/views_trash.py`) for Editors of the profile only: Readers get 403 and the nav entry "Trash" is not drawn for them. It lists the top of every deleted batch: a trashed record whose parent is not trashed in the same batch. Each entry shows the kind, name, full path ("Contract > Formation"), when and by whom (IST), how many records are in the batch, **Restore**, **History** and, for the Admin, **Delete permanently...**. Records left in Trash when a record is restored with its parent chain become tops of their own, so nothing in Trash is ever out of sight. Restore is a POST with the CSRF token. If a parent or ancestor is in Trash a page lists the chain and offers "Restore them too" (each ancestor on its own, not the rest of its batch). If a Subject or Topic name is taken, a page asks for a new name with the service's suggestion ("Name (restored)") filled in; the chosen names travel in `rename_<type>_<id>` fields so several clashes can be answered in turn. Other profiles' ids are 404.
- **M3-22. Permanent delete.** Only from the Trash screen, POST with CSRF, and only for the suite-wide Admin who is an Editor of the profile (an Admin whose own role is Reader gets 403, per section 9.6; a plain Editor gets 403). The first press shows a page naming the record and how many of each type are lost; the second press (`confirmed=1`) deletes. If Notes outside the deleted records link to anything in them (live or in Trash) the page is shown instead (HTTP 409), lists each link (Note, whether live, target) and has no delete button; nothing is deleted. The version history is kept.
- **M3-23. Version history screens.** `GET /caselaw/history/<type>/<id>/` lists every version of any record type (version, what happened, time in IST, who) and `.../<version>/` shows the full snapshot, marking content fields that differ from now. **Restore this version** (Editors, POST with the current version) saves the old content as a new version (M3-9 rules: only content fields; position and Item type unchanged; a record in Trash must be restored first). Records of other profiles, unknown types and missing versions are 404; Readers get 403. History is linked from the edit bar of every record in Edit mode, from the Item editor and from the Trash. A permanently deleted record keeps its history, shown with a note.
- **M3-24. Undo in the session.** Every POST of Edit mode, Trash and History runs in one Undo group (`services.action_group()`, a context variable that all service calls inside it share), so one user action is one group: the Item editor's save of the Item and all its Cases used to write one group per service call and is now one. After the request, the group id is added to the session (`diary_undo_groups`, newest last, at most 30, each with its profile id) if it wrote any history. The **Undo: <what>** button in Edit mode (all three Edit pages) posts the newest group; the service enforces the rules of M3-8. If records changed since, a page lists them and offers "Undo anyway" (`force=1`); if someone else changed one, Undo is refused with a message. A group that is not in this session's list for this profile is refused ("nothing to undo"). Undo is itself an action added to the list, so it can be undone (redo); the undone group is removed from the list.
- **M3-25. Conflict screen.** The plain 409 page of M3-15 and M3-18 is replaced by `diary/conflicts.py` and `edit_conflict.html` (still HTTP 409 and nothing saved). It shows a table of what the Editor tried to do (Mine) next to what is stored now (Theirs), differing rows highlighted, for edits, moves, deletes, restores and conversions (for these without typed fields: "What you asked for" and the current name). Three choices: **Keep mine** posts the same request again with every version number (the record, and each Case of the Item editor) brought up to date; **Keep theirs** goes back and changes nothing; **Edit and merge** reopens what was typed with the current version: the Item editor (typed text and Cases next to the saved version, nothing saved yet), a name or review note box, or the tree picker for a move. Everything typed is carried in hidden fields, so nothing is lost. There is no merge for a delete or an Up/Down click; those offer keep mine or keep theirs only. The earlier version stays in the history either way.
- **M3-27. Review fixes.** (1) Undo applies the Restore placement rules (`check_restorable`: Case under a Multi-Item, child Item under a Nested Item, Topics and direct Sub-topics not mixed) to every record it brings back from Trash or puts back under an earlier parent (Undo of a Move), after the whole action is applied; a refusal rolls the Undo back with a message. (2) Tree walks go level by level (one query per parent type and child type per level, `children_of_many`), and the Trash screen counts each batch from the rows it already loaded. (3) Trash batch rows that no record carries are deleted after Restore, permanent delete and Undo (`prune_batches`). (4) A name given while restoring may only rename a Subject, Topic or Sub-topic, and goes through the same length and required checks as any edit.
- **M3-26. Navigation and roles.** The "Trash" nav entry uses `diary_editor` from the `current_profile` context processor (Editor of the profile). All addresses of 3d are guarded by the same decorators as Edit mode (Readers 403, signed-out users to login, wrong method 405, other profile 404).

**Deviation from the original plan (recorded):** section 7 and the plan name TipTap for the rich text box and SortableJS for drag and drop. Neither could be installed (no package access in the build environment), so both are vanilla JavaScript: `static/js/richtext-editor.js` (a `contenteditable` box limited to p, br, b, i, u) and `static/js/edit-mode.js` (pointer events, always with Up and Down buttons). The server sanitiser remains the authority. A library can replace either later without changing the service layer or the forms.

**Owner defaults that need confirmation (milestone 3):** a Reader sees no Trash or History; permanent delete is Admin only and refused while Notes link to the target; Undo covers the current browser session only (up to 30 actions); a history restore never moves a record or changes its Item type; Keep mine overwrites the other version (kept in History).

## UI round 5

Items 1 to 5, 6, 7 and 9 of the owner's round 5 request. The rest are recorded when they are built. Entries marked DEFAULT are choices made where the owner did not say.

- **R5-1.** [Owner: "Remove the tab 'subjects' in the header. Instead, when you click 'Case Law Diary', go to 'Subjects'."] Decision: the Subjects entry is removed from the program nav; inside a program the program name links to `/caselaw/subjects/` (title "Subjects"). On suite pages (Home, Users, Settings, Backups) the name still links to Home. DEFAULT: the link keeps the same look as before.
- **R5-2.** [Owner: "On the left of 'Case Law Diary', put a button with a 'Home' logo. This will take you to the 'Home' Page."] Decision: an inline SVG house button (44px target, label "Home (Alt+H)") sits left of the program name, so the header reads Home, name, Back, Forward. Alt+H still works. DEFAULT: shown only inside programs, not on suite pages, where the name already goes Home.
- **R5-3.** [Owner: "In the 'Home' Page, make the entire 'Case Law Diary' text a button. Remove the description beneath it and the 'Open' button."] Decision: the picker shows one large link with only the program display name, going to Subjects, with a visible focus outline. DEFAULT: styled as a boxed italic serif block in the Chambers style.
- **R5-4.** [Owner: "When editing a User, keep 'Case Law Diary Profile' and 'Role in that Profile' on the same Line. I do not need any description beneath either one."] Decision: the profile and role selects sit side by side (stacking only under 480px) and both help texts are removed. DEFAULT: the Admin checkbox keeps its help text, as the owner named only these two.
- **R5-5.** [Owner: "On the 'Subjects' Page, 'Other Subjects' should be visible on the same page. Put a line below the main list of subjects, then have a title 'Other Subjects', and then list all of the other subjects in like manner as the Main subjects."] Decision: a divider, an "Other Subjects" heading (`#other-subjects`) and the other Subjects in the same style with item counts follow the main list. Edit mode reorders and moves within each list. DEFAULT: `/caselaw/other-subjects/` redirects (temporary) to `/caselaw/subjects/#other-subjects`, keeping `?edit=1`; breadcrumbs of an Other Subject link to that section.
- **R5-6.** [Owner: "Keep a button in directory view to 'show header' which will reveal the entire header once you have scrolled down. Let it be an icon, not text, so that it is small. Perhaps it can be like the three horizontal parallel lines that show up for Menus in mobile view on most apps or web pages."] Decision: on the reading pages a three-line icon button (label and title "Show header", 44px tap target) sits at the left end of the sticky breadcrumb row. DEFAULT: it appears only once the header has scrolled out of view and needs JavaScript. Clicking it drops the whole header down just under the breadcrumb row as an overlay with a shadow (a spacer keeps the page from jumping); Escape or a click elsewhere closes it and Escape returns focus to the button; `aria-expanded` follows. DEFAULT: scrolling back to the top closes it.
- **R5-7.** [Owner: "When jumping to a Topic / Sub-Topic etc., while 'View in Context' is active, jump there so that I can see the header in question too, and not just the text below it."] Decision: every jump target in the reading area has `scroll-margin-top` equal to the sticky breadcrumb row height (measured by the script into `--sticky-offset`, so it stays right when the row wraps) plus a small gap, so the heading shows below the row. After the All redirect the script jumps again once the offset is known and after the page has loaded (unless you have already scrolled). Verified in headless Chromium at 1200px and 375px: target top is at or below the row bottom.
- **R5-9.** [Owner: "Rename 'View in Context' to 'All'. Also, in Settings, allow me to change, for a particular profile, the default status of All view to be ticked On or Off."] Decision: the tick is now labelled "All" (cookie `quill_in_context` and `localStorage` key `quill.incontext` keep their names). Profile settings has "Show \"All\" ticked by default" (`Profile.reading_all_default`, default on); Editors change it, Readers only see it. "No choice yet" means the cookie is absent and there is no `localStorage` value. In that state the server uses the profile default and the script writes no cookie until the box is toggled. Any cookie wins over the profile default (`0` is off, anything else on). DEFAULT: the cookie and `localStorage` are per browser, not per profile, so a choice made in one profile also applies to another profile in the same browser. DEFAULT: old backups without the field restore as on.
- **R5-8.** [Owner: "Allow a User to go directly to a particular program whenever he logs in, as the landing page instead of Home."] Decision: `User.landing_program` (blank means Home) is the program key opened after sign-in. DEFAULT: a per-user setting, Home when blank. DEFAULT: every signed-in user changes their own on a "My settings" page (`/my-settings/`, linked from the suite nav), offering Home plus each program they have a profile in; an Admin can also set it on the user edit screen. DEFAULT: a safe `next` address (for example after a session timeout) wins over the landing program; an unsafe one is ignored. DEFAULT: if the chosen program is no longer available to the user (no live profile) the sign-in opens Home with no message. A user already signed in who opens the login page is sent the same way. Backups include the field; older backups restore as Home.
- **R5-10a.** [Owner: "When adding a new item There are currently three text boxes: Name (for headers only), Text (item only) and Citation (item only). Is it possible to merge the Name & Text boxes, such that whatever I put in there will be entered into Name (if it is a Heading or a Section), or Text (if it is an item)? Further, if 'Item' is not selected, grey out 'Citation'."] Decision: the Add form has one Text box (field `text`). For Subject, Topic, Sub-topic and Section the server stores it as the name: tags are stripped, whitespace and newlines collapse to single spaces, it is required and at most the model field length (300, Section 500). For Item and Nested Item it is the Item text. Citation is saved only for Item and Nested Item; the server ignores a posted citation for every other kind, whatever the script did. `static/js/add-form.js` swaps the rich text box for a single plain line (no toolbar) when a heading kind is chosen, keeps what was typed when the kind changes, and disables (greys) Citation unless the kind is Item or Nested Item. Without JavaScript the form still works (a plain textarea; the server decides by kind). DEFAULT: the script sends `text_format=html` so the rich box's cleaned HTML is sanitised by `diary/richtext.py`; plain typed text (no script) is escaped into paragraphs as before. DEFAULT: a Section now needs a name when added (previously blank was accepted); Rename still allows blank. DEFAULT: in a Subject's edit bar the Add form starts on Topic instead of Item, so its Citation is rendered disabled from the start; elsewhere it starts on Item. DEFAULT: an old form posting `name` for a heading is still accepted when `text` is absent.
- **R5-10b (icons part).** [Owner: "The editing feature is a bit clunky. Help me redesign it, so that it is easier and quicker to add or edit entries - ESPECIALLY adding entries. Perhaps, in editing mode, change all buttons to icons, so that they are smaller?"] Decision: the buttons in each record's edit bar (drag handle, up, down, edit, mark or clear review, move to, show on landing or move to Other Subjects, history, delete, and the Review note, Rename and Add openers, plus Add a Subject) are inline SVG icon buttons (`.edit-btn.icon-btn`, icons from `templates/diary/_icon.html`), each with `aria-label`, `title` and a visually hidden text span. They sit in one compact `.edit-actions` row. Existing form posts, `formaction`s and the `data-drag-handle` hook are unchanged. DEFAULT: the buttons are 44px by 44px by default and under `(pointer: coarse)`, and shrink to 30px only for `(hover: hover) and (pointer: fine)`. DEFAULT: on that desktop pointer the row is hidden (opacity 0, so it still takes its space and does not shift the page) until the record is hovered or has keyboard focus inside it, or one of its panels is open; on touch it is always visible. DEFAULT: the Undo, Trash, Restore and History-page buttons keep their text, as they are page-level actions with consequences worth reading. Quick add and add-after are R5-10c, built separately. Checked in headless Chromium: 44px under coarse emulation, 30px and hidden with a fine hovering pointer, revealed by focus within.
- **R5-10b (quick add).** [Owner: "...perhaps, for all users with editing ability, add a '+' button to create (ONLY on the desktop view) next to every item or header etc allowing me to add new items?"] Decision: a "+" icon button (`aria-label` "Add entry here", `data-add-here`, template `_add_here.html`) sits next to every Subject, Topic and Sub-topic heading, every Section and every Item, for Editors only (nothing is rendered for Readers, and `edit/add/` answers 403 to them whatever is posted). In reading view it exists only when `(min-width: 900px) and (hover: hover) and (pointer: fine)` matches (CSS hides it otherwise) and shows on hover or keyboard focus; in Edit mode it is one of the icon buttons on every screen size. The "+" is an ordinary link to the Add page (`edit/add/?after=item:5` or `?parent=topic:3`, preselecting the place, `next` carried), so it works without JavaScript and on phones. `static/js/quick-add.js` (loaded only for Editors) turns the click into a small inline form directly beneath the row, only when the same media query matches at click time: a kind switch, Text (a plain line for Subject, Topic, Sub-topic and Section; the minimal rich box from `richtext-editor.js` for Item and Nested Item), Citation (disabled for the headings). Enter or Ctrl+Enter saves, Shift+Enter is a new line in the rich box, Escape cancels. It posts to the same `edit_add` view with the header `X-Requested-With: fetch` and gets JSON back (`ok`, `id`, `kind`, `version`, `after`, or `errors`, with 400 for a rule or typing error, 409 for a stale version, 403 for a non-Editor). Everything is done by `svc.create(..., index=...)`, so numbering, History and Undo behave as for any add, and the add is one Undo step including the siblings that shift. DEFAULT: on a heading the "+" adds INSIDE it, as the FIRST entry (`first=1`), so the new entry appears right under the heading where the form is; the Add form in the edit bar still adds at the end. DEFAULT: default kind after an Item or Section is Item (same parent; inside a Nested Item only Item is offered), on a Topic or Sub-topic Item, on a Subject Topic. DEFAULT: after a save the script fetches the same page again and swaps the article content, which is the simplest way to get every generated number right (the scroll position is kept), and opens the form again beneath the new Item or Section for "add another"; after adding a heading it just closes the form, because "after" a heading would really mean inside it. No sibling-version check is sent for "inside" adds.
- **R5-10c.** [Owner: "When editing, and viewing items, put a button with the item to add an item AFTER that item."] Decision: the same "+" on an Item or Section means add directly after it, in the same parent (`after=<kind>:<id>`, kinds item, section, topic, subtopic). The server finds the record inside the signed-in profile (another profile's id or a Trash record is refused), takes its parent from its position sequence, counts its live siblings up to it and creates the new record at that index, so later siblings move down by one (a `reorder` History row each) and Items, Sections and Nested Items keep sharing one sequence. Optimistic concurrency: the form sends `after_version`, the version of the record the Editor saw; a stale one is a conflict (the normal conflict screen, or 409 JSON), and "Keep mine" re-sends with the current version. A Reader gets 403. Visible in reading view for Editors on desktop and in Edit mode everywhere (on a phone it opens the Add page). DEFAULT: one button serves both 10b and 10c (on an Item or Section it is "add after", on a heading it is "add inside"), instead of two buttons per row.

Questions for the owner: (1) Should the Home icon also show on suite pages? (2) Should the Admin checkbox help text go too? (3) Should the Other Subjects list be collapsible?

### Editing redesign (plain description for the owner)

Adding is now quicker in three ways. First, the edit buttons are small icons instead of words; hover or tab to a record to see them, and each has a hover label. Second, there is a **+** next to every heading, Section and Item. On a computer with a mouse, click it and a small box opens right under that line; type the text (and a citation for an Item), press **Enter**, and the entry is added directly after that Item or Section (or first inside that heading). The box stays open under the new entry so you can keep typing the next one; **Shift+Enter** starts a new line, **Esc** closes the box. Third, the same + works on a phone or tablet in Edit mode, but there it opens the ordinary Add page with the place already chosen, because a small screen has no room for the inline box. People who can only read never see the + and the server refuses them even if they try. Everything you add this way is numbered correctly, appears in History, and can be reversed with **Undo** (one step per entry). If someone else changed the Item you were adding after, nothing is added and you get the usual two versions screen.
