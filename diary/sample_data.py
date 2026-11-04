"""Clearly named TEST data for checking the screens (Milestone 1).

Every sample Subject name starts with ``SAMPLE_PREFIX``. Removal deletes only
Subjects with that prefix (and what sits under them), never anything else.
Both loading and removal work inside ONE profile; other profiles are never touched.
"""
from django.db import transaction
from django.db.models import Q

from .models import (
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


def sample_subjects(profile):
    return Subject.objects.filter(profile=profile, name__startswith=SAMPLE_PREFIX)


def _item(profile, citation="", **fields):
    """An Item; its citation is its first Case."""
    item = Item.objects.create(profile=profile, **fields)
    if citation:
        Case.objects.create(profile=profile, item=item, citation=citation, position=1)
    return item


def _items(profile, count, **parent):
    for n in range(1, count + 1):
        _item(
            profile,
            text=f"<p>Sample proposition number {n}.</p>",
            citation=f"(2020) {n} SCC {100 + n}",
            position=n,
            **parent,
        )


@transaction.atomic
def load_sample_data(profile):
    """Create the sample set in ``profile``. Returns False (and changes nothing) if it already exists there."""
    if sample_subjects(profile).exists():
        return False

    contract = Subject.objects.create(profile=profile,
        name=SAMPLE_PREFIX + "Contract Law", position=1, landing_position=1
    )
    _item(profile,
        subject=contract, text="<p>An Item placed directly under the Subject.</p>",
        citation="AIR 1950 SC 1", position=1,
    )
    formation = Topic.objects.create(profile=profile, subject=contract, name="Formation", position=1)
    offer = Subtopic.objects.create(profile=profile, topic=formation, name="Offer", position=1)
    _item(profile,
        subtopic=offer, text="<p>An offer must be <b>communicated</b> to be valid.</p>",
        citation="Lalman Shukla v. Gauri Dutt (1913) 11 ALJR 489", position=1,
    )
    _item(profile,
        subtopic=offer, text="<p>An invitation to treat is not an offer.</p>",
        citation="Harvey v. Facey [1893] AC 552", position=2,
    )
    several = _item(profile,
        subtopic=offer, position=3,
        text="<p>A <i>general offer</i> may be accepted by performance.</p>",
    )
    Case.objects.create(profile=profile, item=several, citation="Carlill v. Carbolic Smoke Ball Co [1893] 1 QB 256",
                        comment="<p>Leading case.</p>", position=1)
    Case.objects.create(profile=profile, item=several, citation="Harbhajan Lal v. Union of India AIR 1996 SC 1", position=2)
    Case.objects.create(profile=profile, item=several, citation="Third sample case (2001) 2 SCC 2",
                        comment="<p>Followed in <u>later</u> cases.</p>", position=3)
    lines = _item(profile,
        subtopic=offer, position=4, citation_layout="lines",
        text="<p>Revocation of an offer:</p>",
    )
    for n, (text, citation) in enumerate((("effective before acceptance only", "Sample v. Revocation (2010) 1 SCC 1"),
                                          ("effective by notice to the offeree", "Example v. Notice (2011) 2 SCC 2")), start=1):
        Case.objects.create(profile=profile, item=lines, citation=citation,
                            comment=f"<p>Revocation is {text}.</p>", position=n)
    _item(profile,
        subtopic=offer, text="<p>This sample proposition was overruled.</p>", citation="Old v. Law (1950) 1 SCC 1",
        flag="overruled", flag_text="Overruled by New v. Law (1990)", position=5,
    )
    _item(profile,
        subtopic=offer, text="<p>This sample Item has a Pending flag.</p>", citation="Doubtful v. Sample (2005) 3 SCC 3",
        flag="pending", flag_text="Check the citation against the report.", position=6,
    )
    acceptance = Subtopic.objects.create(profile=profile, topic=formation, name="Acceptance", position=2)
    _items(profile, 3, subtopic=acceptance)
    note = Note.objects.create(profile=profile, subtopic=offer, text="<p>Compare the rules on acceptance.</p>", position=1)
    NoteLink.objects.create(profile=profile, note=note, subtopic=acceptance)

    remedies = Topic.objects.create(profile=profile, subject=contract, name="Remedies", position=2)
    clause = Subtopic.objects.create(profile=profile, topic=remedies, name="Clause 12: Leave to Sue", position=1)
    _items(profile, 2, subtopic=clause)  # before the first Section: (1), (2)
    section_a = Section.objects.create(profile=profile, subtopic=clause, name="Leave to sue: grounds", position=3)
    for n in (1, 2):
        _item(profile, subtopic=clause, text=f"<p>Section A proposition {n}.</p>",
                            citation=f"(2015) {n} SCC 10", position=3 + n)
    Section.objects.create(profile=profile,
        subtopic=clause, name="Leave to sue: procedure", position=6,
        flag="other", flag_text="Section heading wording to be confirmed.",
    )
    for n in range(1, 9):
        _item(profile, subtopic=clause, text=f"<p>Section B proposition {n}.</p>",
                            citation=f"(2016) {n} SCC 20", position=6 + n)
    Note.objects.create(profile=profile, section=section_a, text="<p>A note on a Section.</p>", position=1)

    longs = Subject.objects.create(profile=profile, name=SAMPLE_PREFIX + "Long Lists", position=2, landing_position=2)
    for n in range(1, 31):
        Topic.objects.create(profile=profile, subject=longs, name=f"Sample Topic {n}", position=n)
    first_topic = longs.topics.get(position=1)
    many = Subtopic.objects.create(profile=profile, topic=first_topic, name="Forty-five Items (past 39)", position=1)
    _items(profile, 45, subtopic=many)
    plenty = Subtopic.objects.create(profile=profile, topic=first_topic, name="Thirty Sections (letters past z)", position=2)
    for n in range(1, 31):
        Section.objects.create(profile=profile, subtopic=plenty, name=f"Sample Section {n}", position=n)

    other = Subject.objects.create(profile=profile,
        name=SAMPLE_PREFIX + "Other Subject (Sample Act)", position=3,
        show_on_landing=False, other_acts_position=1,
    )
    _item(profile, subject=other, text="<p>An Item directly under an Other Subject.</p>",
                        citation="AIR 1960 SC 2", position=1)
    for n in (1, 2, 3):
        sub = Subtopic.objects.create(profile=profile, subject=other, name=f"Sample provision {n}", position=n)
        _items(profile, 2, subtopic=sub)
    return True


class SampleDataError(Exception):
    """Sample data cannot be removed without touching real records."""


@transaction.atomic
def remove_sample_data(profile):
    """Delete only the sample Subjects and everything under them. Returns how many Subjects.

    Links and Notes inside the sample are deleted first (links are PROTECTed targets).
    A Note outside the sample that links into it stops the removal with SampleDataError;
    nothing is deleted in that case.
    """
    ids = list(sample_subjects(profile).values_list("pk", flat=True))
    if not ids:
        return 0
    topics = set(Topic.objects.filter(profile=profile, subject__in=ids).values_list("pk", flat=True))
    subtopics = set(
        Subtopic.objects.filter(Q(subject__in=ids) | Q(topic__in=topics)).values_list("pk", flat=True)
    )
    sections = set(
        Section.objects.filter(Q(subject__in=ids) | Q(topic__in=topics) | Q(subtopic__in=subtopics))
        .values_list("pk", flat=True)
    )
    items = set(
        Item.objects.filter(Q(subject__in=ids) | Q(topic__in=topics) | Q(subtopic__in=subtopics))
        .values_list("pk", flat=True)
    )

    sample_notes = Note.objects.filter(
        Q(subject__in=ids) | Q(topic__in=topics) | Q(subtopic__in=subtopics)
        | Q(section__in=sections) | Q(item__in=items)
    )
    incoming = NoteLink.objects.filter(
        Q(subject__in=ids) | Q(topic__in=topics) | Q(subtopic__in=subtopics)
        | Q(section__in=sections) | Q(item__in=items)
    )
    outside = incoming.exclude(note__in=sample_notes)
    if outside.exists():
        raise SampleDataError(
            "Sample data was not removed: a Note that is not part of the sample links into it. "
            "Remove that link first."
        )
    NoteLink.objects.filter(note__in=sample_notes).delete()
    incoming.delete()
    sample_notes.delete()
    Subject.objects.filter(pk__in=ids).delete()
    return len(ids)
