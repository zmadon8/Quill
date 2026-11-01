"""Clearly named TEST data for checking the screens (Milestone 1).

Every sample Subject name starts with ``SAMPLE_PREFIX``. Removal deletes only
Subjects with that prefix (and what sits under them), never anything else.
"""
from django.db import transaction

from .models import (
    KIND_MULTI,
    KIND_NESTED,
    Case,
    Item,
    Note,
    NoteLink,
    Section,
    Subject,
    Subtopic,
    Topic,
)

SAMPLE_PREFIX = "TEST SAMPLE: "


def sample_subjects():
    return Subject.objects.filter(name__startswith=SAMPLE_PREFIX)


def _items(count, **parent):
    for n in range(1, count + 1):
        Item.objects.create(
            text=f"<p>Sample proposition number {n}.</p>",
            citation=f"(2020) {n} SCC {100 + n}",
            position=n,
            **parent,
        )


@transaction.atomic
def load_sample_data():
    """Create the sample set. Returns False (and changes nothing) if it already exists."""
    if sample_subjects().exists():
        return False

    contract = Subject.objects.create(
        name=SAMPLE_PREFIX + "Contract Law", position=1, landing_position=1
    )
    Item.objects.create(
        subject=contract, text="<p>An Item placed directly under the Subject.</p>",
        citation="AIR 1950 SC 1", position=1,
    )
    formation = Topic.objects.create(subject=contract, name="Formation", position=1)
    offer = Subtopic.objects.create(topic=formation, name="Offer", position=1)
    Item.objects.create(
        subtopic=offer, text="<p>An offer must be <b>communicated</b> to be valid.</p>",
        citation="Lalman Shukla v. Gauri Dutt (1913) 11 ALJR 489", position=1,
    )
    Item.objects.create(
        subtopic=offer, text="<p>An invitation to treat is not an offer.</p>",
        citation="Harvey v. Facey [1893] AC 552", position=2,
    )
    multi = Item.objects.create(
        subtopic=offer, kind=KIND_MULTI, position=3,
        text="<p>A <i>general offer</i> may be accepted by performance.</p>",
    )
    Case.objects.create(item=multi, citation="Carlill v. Carbolic Smoke Ball Co [1893] 1 QB 256",
                        comment="<p>Leading case.</p>", position=1)
    Case.objects.create(item=multi, citation="Harbhajan Lal v. Union of India AIR 1996 SC 1", position=2)
    Case.objects.create(item=multi, citation="Third sample case (2001) 2 SCC 2",
                        comment="<p>Followed in <u>later</u> cases.</p>", position=3)
    nested = Item.objects.create(
        subtopic=offer, kind=KIND_NESTED, position=4,
        text="<p>Revocation of an offer:</p>", citation="Sample v. Nested (2010) 1 SCC 1",
    )
    for n, text in enumerate(("before acceptance only", "by notice to the offeree"), start=1):
        Item.objects.create(parent_item=nested, text=f"<p>Revocation is effective {text}.</p>", position=n)
    Item.objects.create(
        subtopic=offer, text="<p>This sample proposition was overruled.</p>", citation="Old v. Law (1950) 1 SCC 1",
        flag="overruled", flag_text="Overruled by New v. Law (1990)", position=5,
    )
    Item.objects.create(
        subtopic=offer, text="<p>This sample Item is marked for review.</p>", citation="Doubtful v. Sample (2005) 3 SCC 3",
        needs_review=True, review_note="Check the citation against the report.", position=6,
    )
    acceptance = Subtopic.objects.create(topic=formation, name="Acceptance", position=2)
    _items(3, subtopic=acceptance)
    note = Note.objects.create(subtopic=offer, text="<p>Compare the rules on acceptance.</p>", position=1)
    NoteLink.objects.create(note=note, subtopic=acceptance)

    remedies = Topic.objects.create(subject=contract, name="Remedies", position=2)
    clause = Subtopic.objects.create(topic=remedies, name="Clause 12: Leave to Sue", position=1)
    _items(2, subtopic=clause)  # before the first Section: (i), (ii)
    section_a = Section.objects.create(subtopic=clause, name="Leave to sue: grounds", position=3)
    for n in (1, 2):
        Item.objects.create(subtopic=clause, text=f"<p>Section A proposition {n}.</p>",
                            citation=f"(2015) {n} SCC 10", position=3 + n)
    Section.objects.create(
        subtopic=clause, name="Leave to sue: procedure", position=6,
        needs_review=True, review_note="Section heading wording to be confirmed.",
    )
    for n in range(1, 9):
        Item.objects.create(subtopic=clause, text=f"<p>Section B proposition {n}.</p>",
                            citation=f"(2016) {n} SCC 20", position=6 + n)
    Note.objects.create(section=section_a, text="<p>A note on a Section.</p>", position=1)

    longs = Subject.objects.create(name=SAMPLE_PREFIX + "Long Lists", position=2, landing_position=2)
    for n in range(1, 31):
        Topic.objects.create(subject=longs, name=f"Sample Topic {n}", position=n)
    first_topic = longs.topics.get(position=1)
    many = Subtopic.objects.create(topic=first_topic, name="Forty-five Items (past xxxix)", position=1)
    _items(45, subtopic=many)
    plenty = Subtopic.objects.create(topic=first_topic, name="Thirty Sections (letters past Z)", position=2)
    for n in range(1, 31):
        Section.objects.create(subtopic=plenty, name=f"Sample Section {n}", position=n)

    other = Subject.objects.create(
        name=SAMPLE_PREFIX + "Other Subject (Sample Act)", position=3,
        show_on_landing=False, other_acts_position=1,
    )
    Item.objects.create(subject=other, text="<p>An Item directly under an Other Subject.</p>",
                        citation="AIR 1960 SC 2", position=1)
    for n in (1, 2, 3):
        sub = Subtopic.objects.create(subject=other, name=f"Sample provision {n}", position=n)
        _items(2, subtopic=sub)
    return True


@transaction.atomic
def remove_sample_data():
    """Delete only the sample Subjects and everything under them. Returns how many Subjects.

    Cross-reference links from sample Notes go with their Notes. A link from a real
    Note into the sample is protected by the database and stops the removal with an
    error rather than being deleted silently.
    """
    ids = list(sample_subjects().values_list("pk", flat=True))
    if ids:
        Subject.objects.filter(pk__in=ids).delete()
    return len(ids)
