"""One-time import of "Case Law Diary.docx" (docs/DESIGN.md section 8, Milestone 2).

``docx_reader`` and ``plan`` are plain Python (no Django): they read the Word file, never write to
it, and turn it into a plan of records. ``report`` writes the dry-run and reconciliation texts.
``loader`` is the only module that touches the database.
"""
