"""Plain-text dry-run and reconciliation reports (pure Python). Every difference is listed, none hidden."""
from collections import Counter, OrderedDict

from .plan import EXPECTED, ITEM, REASONS, SECTION, SUBJECT, SUBTOPIC, TOPIC, strip_colon, summary_counts

LINE = "=" * 78
FIRST_LINES_PER_TOPIC = 3

COUNT_LABELS = OrderedDict([
    ("subjects", "Subjects (all)"),
    ("main_subjects", "  main Subjects (landing page)"),
    ("other_subjects", "  Other Subjects"),
    ("topics", "Topics (under main Subjects)"),
    ("subtopics", "Sub-topics"),
    ("sections", "Sections"),
    ("items", "Items"),
    ("items_clean", "  clean Items (Text and Citation split)"),
    ("items_flagged", "  flagged Items (whole line as Text)"),
    ("review_marked", "Review-marked records (flagged Items + Sections)"),
    ("text_paragraphs", "Paragraphs with text"),
    ("blank_paragraphs", "Blank paragraphs (skipped)"),
    ("colon_changes", "Names with the trailing colon removed"),
])


def _short(text, width=150):
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 3] + "..."


def owner_subject(node):
    while node is not None and node.kind != SUBJECT:
        node = node.parent
    return node


def per_subject_counts(plan):
    """Ordered {subject name: Counter} in the order the Subjects are listed (main, then Other)."""
    subjects = plan.of(SUBJECT)
    ordered = [s for s in subjects if not s.other_subject] + [s for s in subjects if s.other_subject]
    table = OrderedDict((s.ref, Counter(name=s.name, other=s.other_subject)) for s in ordered)
    for node in plan.nodes:
        owner = owner_subject(node)
        row = table[owner.ref]
        if node.kind == TOPIC:
            row["topics"] += 1
        elif node.kind == SUBTOPIC:
            row["subtopics"] += 1
        elif node.kind == SECTION:
            row["sections"] += 1
            row["flagged_sections"] += 1 if node.needs_review else 0
        elif node.kind == ITEM:
            row["items"] += 1
            row["flagged"] += 1 if node.needs_review else 0
    return table


def _table(headers, rows):
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)] if rows else [len(h) for h in headers]
    def fmt(row):
        cells = []
        for i, value in enumerate(row):
            cells.append(str(value).ljust(widths[i]) if i == 0 else str(value).rjust(widths[i]))
        return "  ".join(cells)
    out = [fmt(headers), "  ".join("-" * w for w in widths)]
    out.extend(fmt(r) for r in rows)
    return out


def section_groups(plan):
    """For each Section: the number of Items that follow it (by position) before the next Section."""
    groups = []
    for section in plan.of(SECTION):
        siblings = [n for n in plan.nodes if n.parent is section.parent and n.kind in (ITEM, SECTION)]
        siblings.sort(key=lambda n: n.position)
        count = 0
        for n in siblings:
            if n.position <= section.position:
                continue
            if n.kind == SECTION:
                break
            count += 1
        groups.append((section.ref, section.name, count))
    return groups


def dry_run_report(plan, filename, sha256, size, generated):
    counts = summary_counts(plan)
    out = [LINE, "DRY RUN: import of the Word file (nothing has been saved)", LINE]
    out += [f"File: {filename}", f"Size: {size} bytes", f"SHA-256: {sha256}", f"Made: {generated}", ""]
    out.append("The Word file was only read, never changed.")
    out.append("")
    if plan.problems:
        out += ["PROBLEMS (the import will refuse to run until these are resolved)", "-" * 78]
        out += [f"  - {p}" for p in plan.problems]
        out.append("")
    notes = plan.file_notes
    out.append(
        f"In the file: {notes.get('tables', 0)} tables, {notes.get('images', 0)} images, "
        f"{notes.get('footnote_references', 0)} footnote references."
    )
    out.append("")
    out += ["1. TOTALS (file against the figures in docs/IMPORT_ANALYSIS.md)", "-" * 78]
    rows = []
    for key, label in COUNT_LABELS.items():
        rows.append((label, counts[key], EXPECTED[key], "same" if counts[key] == EXPECTED[key] else "DIFFERENT"))
    out += _table(("", "In file", "Expected", ""), rows)
    out.append("")

    out += ["2. COUNTS PER SUBJECT", "-" * 78]
    rows = []
    for row in per_subject_counts(plan).values():
        rows.append((
            row["name"] + (" (Other)" if row["other"] else ""),
            row["topics"], row["subtopics"], row["sections"], row["items"], row["items"] - row["flagged"], row["flagged"],
        ))
    out += _table(("Subject", "Topics", "Sub-topics", "Sections", "Items", "Clean", "Flagged"), rows)
    out.append("")

    out += ["3. WHY ITEM LINES ARE FLAGGED (first matching reason; imported whole as Text, no Citation)", "-" * 78]
    reasons = Counter(n.reason for n in plan.of(ITEM) if n.reason)
    rows = [(REASONS[k], reasons[k]) for k in REASONS if reasons[k]]
    rows.append(("Total flagged Items", sum(reasons.values())))
    out += _table(("Reason", "Lines"), rows)
    out.append("")

    out += ["4. SECTIONS (flagged for review, decision I10)", "-" * 78]
    for ref, name, count in section_groups(plan):
        out.append(f"  {ref}: {name!r} with {count} Item(s) after it, up to the next Section")
    for node in plan.of(SECTION):
        out.append(f"    reason: {node.review_note}")
    if not plan.of(SECTION):
        out.append("  none")
    out.append("")

    out += ["5. NAMES WITH THE TRAILING COLON REMOVED (decision I8)", "-" * 78]
    changed = [n for n in plan.nodes if n.colon_removed]
    for n in changed:
        out.append(f"  {n.ref} [{n.kind}] {n.original_line!r} -> {n.name!r}")
    if not changed:
        out.append("  none")
    out.append("")

    out += ["6. FORMATTING", "-" * 78]
    items = plan.of(ITEM)
    formatted = [n for n in items if n.formatted]
    out.append(f"  {len(formatted)} Item lines have bold, italic or underline runs; these are kept as b, i, u in Text.")
    split_formatted = [n for n in formatted if n.citation]
    out.append(
        f"  On {len(split_formatted)} split lines the Citation is stored as plain text (it is shown in italics by "
        "the display), so formatting on the citation side is not stored."
    )
    other = [n for n in plan.nodes if n.other_formatting and n.kind in (ITEM, SECTION)]
    out.append(f"  Lines with other formatting (colour, size and so on), which is dropped: {len(other)}")
    for n in other:
        out.append(f"    {n.ref}: {', '.join(n.other_formatting)}: {_short(n.original_line)}")
    out.append("")

    out += ["7. OTHER THINGS NOTICED", "-" * 78]
    out.append(f"  Blank paragraphs skipped: {len(plan.blank_paragraphs)}")
    for index, previous in plan.blank_paragraphs:
        out.append(f"    paragraph {index + 1}, after {_short(previous, 60)!r}")
    restarted = [n for n in items if n.list_restarted]
    out.append(
        f"  Item groups where Word's list restarted inside the same Sub-topic or Topic (kept in document order, "
        f"not flagged): {len(restarted)}"
    )
    for n in restarted:
        out.append(f"    {n.ref}: {_short(n.original_line, 100)}")
    for ref, text in plan.skipped_headings:
        out.append(f"  Heading 1 {text!r} ({ref}) is not stored as a Subject; its Topics become Other Subjects.")
    for w in plan.warnings:
        out.append(f"  Warning: {w}")
    out.append("")

    out += [f"8. THE FIRST {FIRST_LINES_PER_TOPIC} LINES OF EACH TOPIC (or Other Subject)", "-" * 78]
    shown = Counter()
    for node in plan.nodes:
        if node.kind in (SUBJECT, TOPIC):
            out.append(f"  {node.kind.upper()} {node.name}")
            continue
        top = node.parent if node.parent is not None and node.parent.kind in (SUBJECT, TOPIC) else (
            node.parent.parent if node.parent is not None else None)
        key = top.ref if top is not None else None
        if key is None or shown[key] >= FIRST_LINES_PER_TOPIC:
            continue
        shown[key] += 1
        out.append(f"      [{node.kind}] {_short(node.original_line, 110)}")
    out.append("")

    out += ["9. FLAGGED LINES AND WHY", "-" * 78]
    for node in plan.nodes:
        if node.needs_review:
            out.append(f"  {node.ref} [{node.kind}] {node.review_note}")
            out.append(f"      {_short(node.original_line)}")
    out.append("")
    out.append(LINE)
    out.append("STOPPED: fix the problems above first." if plan.problems else "No problems found. Approve this report before running the import.")
    return "\n".join(out) + "\n"


def compare_with_database(plan, db):
    """Pure comparison of the plan (what the file says) with ``db`` (what the loader read back).

    ``db`` has: ``rows`` {ref: dict(kind, rebuilt, original_line, name, needs_review, review_note)},
    ``order`` [refs in database listing order], ``groups`` [(ref, name, items after it)].
    Returns a dict of findings.
    """
    found = {"missing": [], "extra": [], "expected_diff": [], "unexpected": [], "original_mismatch": [], "review_diff": []}
    rows = db["rows"]
    for node in plan.nodes:
        row = rows.get(node.ref)
        if row is None:
            found["missing"].append(node.ref)
            continue
        if row["original_line"] != node.original_line:
            found["original_mismatch"].append((node.ref, node.original_line, row["original_line"]))
        if row["rebuilt"] != node.original_line:
            if node.kind in (SUBJECT, TOPIC, SUBTOPIC) and row["rebuilt"] == strip_colon(node.original_line) != node.original_line:
                found["expected_diff"].append((node.ref, node.kind, node.original_line, row["rebuilt"]))
            else:
                found["unexpected"].append((node.ref, node.kind, node.original_line, row["rebuilt"]))
        if row["needs_review"] != node.needs_review:
            found["review_diff"].append((node.ref, node.needs_review, row["needs_review"]))
    planned = {n.ref for n in plan.nodes}
    found["extra"] = sorted(r for r in rows if r not in planned)
    found["order_ok"] = db["order"] == [r for r in plan.expected_order if r in planned]
    found["groups_ok"] = [tuple(g) for g in db["groups"]] == [tuple(g) for g in section_groups(plan)]
    return found


def reconciliation_report(plan, db, filename, sha256, generated, profile_name):
    counts = summary_counts(plan)
    found = compare_with_database(plan, db)
    out = [LINE, f"RECONCILIATION: the Word file against profile {profile_name!r}", LINE]
    out += [f"File: {filename}", f"SHA-256: {sha256}", f"Made: {generated}", ""]
    problems = 0

    out += ["1. COUNTS (file against database)", "-" * 78]
    rows = []
    db_counts = db["counts"]
    for key in ("subjects", "main_subjects", "other_subjects", "topics", "subtopics", "sections", "items",
                "items_clean", "items_flagged", "review_marked"):
        same = counts[key] == db_counts[key]
        problems += 0 if same else 1
        rows.append((COUNT_LABELS[key], counts[key], db_counts[key], "same" if same else "DIFFERENT"))
    out += _table(("", "File", "Database", ""), rows)
    out.append(f"  Text paragraphs in the file: {counts['text_paragraphs']}; blank paragraphs skipped: "
               f"{counts['blank_paragraphs']}.")
    out.append("")

    out += ["2. COUNTS PER SUBJECT (file against database)", "-" * 78]
    rows = []
    per_db = db["per_subject"]
    for ref, row in per_subject_counts(plan).items():
        theirs = per_db.get(ref, Counter())
        mine = (row["topics"], row["subtopics"], row["sections"], row["items"], row["flagged"])
        other = (theirs["topics"], theirs["subtopics"], theirs["sections"], theirs["items"], theirs["flagged"])
        same = mine == other
        problems += 0 if same else 1
        rows.append((row["name"], *mine, "same" if same else f"DB has {other}"))
    out += _table(("Subject", "Topics", "Sub-topics", "Sections", "Items", "Flagged", ""), rows)
    out.append("")

    out += ["3. TEXT ROUND TRIP (rebuilt from the database, compared line by line with the file)", "-" * 78]
    out.append(f"  Lines compared: {len(plan.nodes)}")
    out.append(f"  Lines missing from the database: {len(found['missing'])}")
    for ref in found["missing"]:
        out.append(f"    {ref}")
    out.append(f"  Records in the database that are not in the file: {len(found['extra'])}")
    for ref in found["extra"]:
        out.append(f"    {ref}")
    out.append(f"  Stored original_line differs from the file: {len(found['original_mismatch'])}")
    for ref, was, now in found["original_mismatch"]:
        out.append(f"    {ref}: file {_short(was, 70)!r} / stored {_short(now, 70)!r}")
    out.append(f"  Expected differences (trailing colon removed, decision I8): {len(found['expected_diff'])}")
    out.append(f"  UNEXPECTED differences: {len(found['unexpected'])}")
    for ref, kind, was, now in found["unexpected"]:
        out.append(f"    {ref} [{kind}]")
        out.append(f"      file:     {_short(was, 200)!r}")
        out.append(f"      database: {_short(now, 200)!r}")
    out.append(f"  Order of records in the database matches the file: {'yes' if found['order_ok'] else 'NO'}")
    out.append(f"  Review marker differs between file plan and database: {len(found['review_diff'])}")
    for ref, planned, stored in found["review_diff"]:
        out.append(f"    {ref}: expected {planned}, stored {stored}")
    problems += (len(found["missing"]) + len(found["extra"]) + len(found["original_mismatch"])
                 + len(found["unexpected"]) + len(found["review_diff"]) + (0 if found["order_ok"] else 1))
    out.append("")

    out += ["4. NAMES WITH THE TRAILING COLON REMOVED (original beside stored)", "-" * 78]
    for ref, kind, was, now in found["expected_diff"]:
        out.append(f"  {ref} [{kind}] {was!r} -> {now!r}")
    if not found["expected_diff"]:
        out.append("  none")
    out.append(f"  Expected {counts['colon_changes']}; found {len(found['expected_diff'])}.")
    if counts["colon_changes"] != len(found["expected_diff"]):
        problems += 1
    out.append("")

    out += ["5. SECTIONS AND THE ITEMS AFTER THEM (Word's grouping against the Diary's)", "-" * 78]
    wanted = section_groups(plan)
    for (ref, name, in_file), (_, _, in_db) in zip(wanted, db["groups"] or [(None, None, "missing")] * len(wanted)):
        out.append(f"  {ref} {name!r}: {in_file} Item(s) in the file, {in_db} in the database")
    if not wanted:
        out.append("  no Sections")
    out.append(f"  Same grouping: {'yes' if found['groups_ok'] else 'NO'}")
    if not found["groups_ok"]:
        problems += 1
    out.append("")

    out += [f"6. EVERY REVIEW-MARKED RECORD AND WHY ({db['counts']['review_marked']})", "-" * 78]
    for ref, kind, note in db["review_list"]:
        out.append(f"  {ref} [{kind}] {note}")
    out.append("")
    out.append(LINE)
    out.append("RESULT: MATCH. Nothing lost, nothing invented." if not problems
               else f"RESULT: {problems} DIFFERENCE(S) FOUND. See above.")
    return "\n".join(out) + "\n"
