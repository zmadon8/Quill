# Fees (Memo program) desktop parity notes

## Purpose

This is a running note of every change the web port of the Fees (Memo) program makes to what the program **does**, where that behaviour diverges from, or adds to, the existing desktop (Electron) version. The owner maintains the desktop app in parallel (decision D6), so each entry here is a candidate to mirror in the desktop code later.

## Scope

This note tracks **memo program feature and behaviour changes only**: new tags, new settings, validation rules, and export behaviour that a desktop user would also see. It does not track web-only platform mechanics (how pages are served, how uploads work in a browser, how memory is managed); those are listed separately under "Out of scope" so it is clear they were considered and intentionally left out.

It is seeded from decisions already recorded in the spec and is kept running: as later phases decide further changes to what the memo program does, add a row.

Sources:
- [docs/fees-spec/requirements.md](fees-spec/requirements.md)
- [docs/fees-spec/design.md](fees-spec/design.md)
- [docs/FEES_PHASE0_ANALYSIS.md](FEES_PHASE0_ANALYSIS.md)

## Feature and behaviour changes

| Feature | Desktop behaviour today | Web behaviour | Why | Mirror in desktop? | Source |
|---|---|---|---|---|---|
| Five memo text-default tags | No such tags and no settings for them; memo name, designation, address, bank details and PAN are not driven by configurable firm-constant fields. | Five profile-level `FeesSettings` fields (`memo_default_name` M1, `memo_default_designation` M2, `memo_default_address` M3 multi-line, `memo_default_bank_details` M4 multi-line, `memo_default_pan` M5), blank by default, editable in a "Memo text defaults" Settings group, substituted at export time into the placeholders `MEMO_NAME`, `MEMO_DESIGNATION`, `MEMO_ADDRESS`, `MEMO_BANK_DETAILS`, `MEMO_PAN`. `MEMO_BANK_DETAILS` and `MEMO_ADDRESS` keep their line breaks. No per-memo override. | Owner asked to define these firm-constant texts once in Settings and have them print on every memo. | Yes | R-SET-7, R-EX-1, design 8.2 |
| Signature image tag and upload | No signature tag and no signature upload; a memo carries no embedded signature image. | A signature image (png or jpg/jpeg only, 2 MB cap) is uploaded in the same Settings box as the Word template, stored on `WordTemplate` (`signature_data`, `signature_filename`, `signature_content_type`), downloadable and replaceable like the template, and embedded at the `MEMO_SIGNATURE` (short `MSIG`) tag location. With no signature uploaded the tag renders to nothing and still leaves a valid `.docx`. | Owner asked for a signature image to be placed in the template memo. | Yes (optional; confirm the desktop .docx exporter can embed an image the same way) | R-SET-8, R-EX-1, design 8.4 |
| Editable owner name | The owner name is the hard-coded constant `FIRM_OWNER` = "Ziyad Madon" in `exportService.ts`, used in the export file name. | `FeesSettings.export_owner_name` (default "Ziyad Madon", 0 to 80 characters), editable in Settings, replaces the hard-coded `FIRM_OWNER` and feeds the `{owner}` filename placeholder. | Makes the owner name a setting instead of a code constant, so it can be changed without editing code. | Yes (optional; only matters if the desktop owner name should ever change) | R-FN-1, design 8.3 |
| Customisable memo export filename pattern | Fixed filename rule `sanitize(middle) + " " + FIRM_OWNER + " (" + matter + ").docx"`, not configurable. | `FeesSettings.memo_filename_pattern` (0 to 200 characters, blank means the default) with named placeholders, optional `[ ... ]` segments, a "Reset to default" button and a live preview. Default pattern `Memo {memo_no}[ of {fy}] {owner} ({matter})` reproduces the original output byte-for-byte; sanitising and length limits match the original rule. | Lets the owner change how memo export filenames are built without code changes, while staying byte-identical by default. | Yes (optional; the default keeps parity, so only mirror if the desktop should expose the pattern too) | R-FN-2 to R-FN-6, design 8.3 |
| Custom total of 0 or null treated as no override (D3 fix) | Pre-port behaviour the spec is correcting: a `custom_total_fees` of 0 (or null) could be read as an override of the computed total. | `resolve_memo_fees` treats a `custom_total_fees` of 0 or null as "no override" and falls back to the computed total; it is the single implementation of the fee rule used by every list, report, export and statistic. | Avoids a stored 0 or null silently zeroing or overriding a memo's fees. | Yes | D3 (analysis section 4), R-MEMO-1 |
| Reject custom memo number matching the auto-number shape (Q8) | Pre-port behaviour the spec is correcting: a custom memo number could collide with a future auto-generated number of the form `YYYY-YY/N`. | A custom number matching `^\d{4}-\d{2}/\d+$` (any financial year) is rejected on save with `INVALID_MEMO` and a message naming the rule, keeping numbering predictable. | Prevents a hand-typed number from clashing with the automatic sequence. | Yes | Q8 (analysis section 4), R-NUM-3 |
| Payment-split edit keeps omitted allocations when two or more exist (Q3 fix) | Pre-port behaviour the spec is correcting: on a memo update, omitting allocations did not reliably preserve existing splits. | On update: allocations provided (even empty) replace; omitted with exactly one existing rebuilds it; omitted with two or more existing keeps them unchanged; omitted with none stays unaccounted. | Stops an edit that does not touch payments from destroying a multi-way payment split. | Yes | R-PAY-4 |
| Real-date validation on non-draft memo save (Q5) | Pre-port behaviour the spec is correcting: a non-draft memo could be saved with an invalid calendar date. | A non-draft save validates the date is a real calendar date (plus matter and non-negative computed total), else `INVALID_MEMO` with "Missing or invalid required field(s): Date, Matter". Drafts skip validation. | Keeps impossible dates (for example 31 February) out of finalised memos. | Yes | R-MEMO-2 |
| Search escapes `%` and `_` (Q6) | Pre-port behaviour the spec is correcting: search terms containing `%` or `_` could be treated as SQL LIKE wildcards. | Memo search escapes `%` and `_` in the term so they match literally; terms under two characters return nothing; results are limited to 20. | Makes search match the literal characters the user typed. | Yes | R-RD-7 |

## Out of scope (web-only mechanics, not for desktop)

These were considered and deliberately left out of the table above because they are about how the web platform works, not about what the memo program does. They have no desktop counterpart to mirror:

- Uploads use a browser file picker and replace-in-place dialogs instead of native OS file dialogs (template and signature uploads).
- Pages are server-rendered Django templates plus small vanilla JS, not React or a JS build (decision D4).
- Streaming and RAM budget mechanics: downloads are built via a temp file and `FileResponse` and never held fully in memory, with the memory limits documented for the port.

## How to keep this updated

When a later phase changes what the memo program **does** (not how the web platform works), add a row here with the source spec or analysis section id.
