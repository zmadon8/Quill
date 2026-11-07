# Requirements Document

## Introduction

The Fee Register is a desktop/web application for a legal practice to raise and track legal invoices ("Memos") and the fees received against them. It manages Firms, Matters, and Memos in a hierarchical structure (Firm → Matter → Memo), supports Word/PDF export from a user-uploaded template, tracks multiple payments per Memo, and provides reporting views (Feebook, Outstanding Memos, Statistics) alongside data backup and application settings.

---

## Glossary

- **Memo**: A legal invoice raised by the practice. Equivalent to an invoice document.
- **Firm**: A client organisation. A Firm contains one or more Partners and one or more Matters.
- **Partner**: A named sub-folder within a Firm. Each Matter is assigned to exactly one Partner.
- **Matter**: A named case or engagement belonging to a Firm and a Partner. Memos are raised against a Matter.
- **Appearance**: A court appearance billed as a fee line item on a Memo.
- **Conference**: A client conference billed as a fee line item on a Memo.
- **Financial Year**: The period from 1 April of one calendar year to 31 March of the following calendar year (e.g. 1 April 2026 – 31 March 2027 is "2026-27").
- **Memo Number**: The unique auto-generated identifier for a Memo, in the format "YYYY-YY/N" (e.g. "2026-27/1").
- **TDS**: Tax Deducted at Source. A deduction applied to the Total Fees when computing the net amount payable.
- **Feebook**: The application tab showing all payment receipts across Memos.
- **Word Template**: A user-uploaded `.docx` file used as the base for Memo export. The application fills template placeholders with Memo field values.
- **Active Matter**: A Matter not manually archived by the user.
- **Archived Matter**: A Matter that has been manually archived; new Memos cannot be raised against it.
- **Active Firm**: A Firm that has at least one Active Matter.
- **Archived Firm**: A Firm that has no Active Matters.
- **Application**: The Fee Register desktop/web application.
- **User**: The practitioner operating the Application.

---

## Requirements

---

### Requirement 1: Firm Management

**User Story:** As a User, I want to create and manage Firms with Partners so that I can organise Matters and Memos by client.

#### Acceptance Criteria

1. THE Application SHALL allow the User to create a Firm by providing a unique Firm name.
2. THE Application SHALL allow the User to add one or more Partners to a Firm.
3. THE Application SHALL classify a Firm as Active when it has at least one Active Matter, and as Archived when it has no Active Matters.
4. WHEN the User views the Firms list, THE Application SHALL display Firms in alphabetical order.
5. WHEN the User views the Firms list, THE Application SHALL provide a dropdown filter with the options "All", "Active", and "Archived", defaulting to "Active".
6. WHEN the User selects a Firm from the Firms list, THE Application SHALL navigate to that Firm's detail page.
7. WHEN the User is on a Firm detail page, THE Application SHALL allow the User to edit the Firm name and Partners.
8. WHEN the User is on a Firm detail page, THE Application SHALL display Matters organised by Partner, then alphabetically within each Partner.
9. WHEN the User is on a Firm detail page, THE Application SHALL provide a dropdown filter for Matters with options "All", "Active", and "Archived", defaulting to "Active".
10. WHEN the User is on a Firm detail page, THE Application SHALL allow the User to archive or unarchive individual Matters.
11. WHEN the User views the Firms list, THE Application SHALL display a button next to each Firm that allows the User to create a new Matter for that Firm directly.

---

### Requirement 2: Matter Management

**User Story:** As a User, I want to create and manage Matters under a Firm and Partner so that I can group related Memos together.

#### Acceptance Criteria

1. THE Application SHALL allow the User to create a Matter by providing a unique Matter Name, selecting a Firm, and selecting a Partner.
2. WHEN a Matter is created, THE Application SHALL set its status to Active by default.
3. THE Application SHALL allow the User to archive an Active Matter, changing its status to Archived.
4. THE Application SHALL allow the User to unarchive an Archived Matter, changing its status to Active.
5. WHEN the User views the Matters list, THE Application SHALL display Matters with a dropdown filter containing "Active", "Archived", and "All", defaulting to "Active".
6. WHEN the User selects a Matter from any list, THE Application SHALL navigate to a Matter detail page showing all Memos within that Matter.
7. WHILE a Matter is Archived, THE Application SHALL prevent the creation of new Memos for that Matter.

---

### Requirement 3: Memo Number Generation

**User Story:** As a User, I want Memo numbers to be auto-generated and reset at the start of each financial year so that Memos are uniquely and consistently identified.

#### Acceptance Criteria

1. WHEN a new Memo is created, THE Application SHALL auto-generate a Memo Number in the format "YYYY-YY/N", where "YYYY-YY" is the Financial Year and "N" is a sequential counter starting at 1.
2. THE Application SHALL derive the Financial Year from the Memo Date: dates from 1 April to 31 March of the following year belong to the same Financial Year.
3. WHEN the first Memo of a new Financial Year is created, THE Application SHALL reset the sequential counter to 1 for that Financial Year.
4. THE Application SHALL guarantee that Memo Numbers are unique across all Memos.
5. WHEN a Memo is deleted, THE Application SHALL NOT reuse the Memo Number of the deleted Memo.

---

### Requirement 4: Memo Creation and Fields

**User Story:** As a User, I want to create a Memo with all required fields so that I can raise a complete legal invoice.

#### Acceptance Criteria

1. WHEN the User initiates Memo creation for an Active Matter, THE Application SHALL present a Memo form containing all Memo fields defined in this requirement.
2. THE Application SHALL include the following fields on the Memo form:
   - Date (LINE 1)
   - Memo Number (LINE 2) — auto-generated, read-only
   - Firm (LINE 3) — internal only, not exported
   - Partner (LINE 4) — internal only, not exported
   - Addressee Line 1 (LINE 5) — defaults to Firm name, editable, single line
   - Addressee Line 2 (LINE 6) — multi-line, blank by default, internal only in the sense that it is part of the exported Memo address block
   - Matter Name (LINE 7)
   - Court Name (LINE 8) — multi-line
   - Additional Details Left (LINE 9) — optional, multi-line
   - Additional Details Right (LINE 10) — optional, multi-line
   - Plaintiff Name (LINE 11)
   - Plaintiff Type (LINE 12)
   - Defendant Name (LINE 13)
   - Defendant Type (LINE 14)
   - Client (LINE 15)
   - Number of Appearances (LINE 16) — non-negative integer
   - Dates of Appearances (LINE 17)
   - Fees per Appearance (LINE 18) — non-negative decimal
   - Number of Conferences (LINE 19) — non-negative integer
   - Dates of Conferences (LINE 20)
   - Fees per Conference (LINE 21) — non-negative decimal
   - Misc/Drafting Description (LINE 22)
   - Fees for Misc/Drafting (LINE 23) — non-negative decimal
   - TDS Rate (LINE 25) — pre-filled from Settings default, editable
   - Fees Paid (LINE 27)
   - Date of Payment (LINE 28)
   - Payee (LINE 29)
   - Bank Account (LINE 30) — selected from the Bank Accounts configured in Settings
3. THE Application SHALL auto-calculate Fees for Appearances (LINE 18A) as LINE 16 multiplied by LINE 18.
4. THE Application SHALL auto-calculate Fees for Conferences (LINE 21A) as LINE 19 multiplied by LINE 21.
5. THE Application SHALL auto-calculate Total Fees (LINE 24) as LINE 18A plus LINE 21A plus LINE 23.
6. THE Application SHALL auto-generate Total Fees in Words (LINE 24A) from the numeric value of LINE 24, expressed as Indian-English words (e.g. "Rupees One Lakh Twenty Thousand Only").
7. THE Application SHALL auto-calculate Less TDS (LINE 26) as LINE 24 multiplied by (LINE 25 divided by 100).
8. WHEN the User opens a new Memo form, THE Application SHALL pre-fill Addressee Line 1 with the Firm name.
9. WHEN the User opens a new Memo form, THE Application SHALL pre-fill Fees per Appearance, Fees per Conference, Fees for Misc/Drafting, Additional Details Left, Additional Details Right, and TDS Rate from the current values in Settings.
10. WHEN the User saves a Memo, THE Application SHALL validate that Date, Matter, and Total Fees are present before saving.
11. IF a required field is missing when the User attempts to save, THEN THE Application SHALL display an error message identifying the missing field and SHALL NOT save the Memo.

---

### Requirement 5: Memo Based on Previous Memo

**User Story:** As a User, I want to create a new Memo pre-filled from a previously issued Memo so that I can reduce repetitive data entry.

#### Acceptance Criteria

1. WHEN the User selects the "Create Based On" action for an existing Memo, THE Application SHALL open a new Memo form pre-filled with all non-payment, non-calculated fields from the selected Memo.
2. WHEN the new Memo form is opened via "Create Based On", THE Application SHALL generate a new Memo Number and leave the Date blank for the User to enter.
3. WHEN the new Memo form is opened via "Create Based On", THE Application SHALL clear all payment fields (Lines 27–30).

---

### Requirement 6: Memo Save Options

**User Story:** As a User, I want multiple save options when creating or editing a Memo so that I can immediately export the document if needed.

#### Acceptance Criteria

1. WHEN the User is on the Memo creation or edit form, THE Application SHALL display the following save options: "Save", "Save & Export to Word", and "Save & Export to PDF".
2. WHEN the User selects "Save & Export to Word", THE Application SHALL save the Memo and immediately trigger a Word document export.
3. WHEN the User selects "Save & Export to PDF", THE Application SHALL save the Memo and immediately trigger a PDF document export.

---

### Requirement 7: Memo List View

**User Story:** As a User, I want a filterable list of all Memos so that I can find, manage, and act on invoices efficiently.

#### Acceptance Criteria

1. WHEN the User opens the Memos tab, THE Application SHALL display a list of Memos with the following columns: Memo Number, Date, Firm, Matter Name, Total Fees, Amount Paid, Date of Last Payment, and Status.
2. THE Application SHALL derive Status as "Paid" when the sum of all payments equals Total Fees, and "Unpaid" otherwise.
3. WHEN the User views the Memos list, THE Application SHALL provide a Financial Year filter, listing years in descending order and defaulting to the current Financial Year.
4. WHEN the User views the Memos list, THE Application SHALL provide a Firm filter listing Firms alphabetically, defaulting to "All".
5. WHEN the User views the Memos list, THE Application SHALL provide a Partner filter listing Partners alphabetically and including a "(none)" option, defaulting to "All".
6. WHEN the User views the Memos list, THE Application SHALL provide a Matter filter listing Matters alphabetically.
7. WHEN the User ticks the "Selected Matters" checkbox, THE Application SHALL display a multi-select control allowing the User to choose specific Matters to filter by.
8. WHEN the User ticks the "Unpaid Only" checkbox, THE Application SHALL restrict the Memos list to Memos whose Status is "Unpaid".
9. WHEN the User selects "Export to Word" for a Memo, THE Application SHALL export that Memo as a Word document.
10. WHEN the User selects "Export to PDF" for a Memo, THE Application SHALL export that Memo as a PDF document.
11. WHEN the User selects "Edit" for a Memo, THE Application SHALL open the Memo edit form.
12. WHEN the User selects "Mark Payment" for a Memo, THE Application SHALL open a payment entry form for that Memo.
13. WHEN the User selects "Bulk Export to Excel", THE Application SHALL export all Memos currently displayed in the filtered list to an Excel file.

---

### Requirement 8: Payment Management

**User Story:** As a User, I want to record multiple payments against a Memo so that I can accurately track partial and full payments.

#### Acceptance Criteria

1. THE Application SHALL allow zero or more payment records to be associated with a single Memo.
2. WHEN the User records a payment, THE Application SHALL capture the following fields: Amount, TDS Amount, Memo Amount, Date of Payment, Payee, Bank Account, and Payment Details (internal note).
3. THE Application SHALL display the aggregate (sum) of all payment amounts in the "Amount Paid" column of the Memos list.
4. THE Application SHALL display the date of the most recent payment in the "Date of Last Payment" column of the Memos list.
5. WHEN the User accesses "Mark Payment" from the Memos tab, THE Application SHALL allow the User to add, edit, or delete individual payment records for that Memo.
6. WHEN the User accesses payment records from the Feebook tab, THE Application SHALL allow the User to edit those records.
7. THE Application SHALL NOT include Payment Details in any exported Memo document or Feebook export.

---

### Requirement 9: Word and PDF Export

**User Story:** As a User, I want to export a Memo as a Word or PDF document using my own template so that I can send professional invoices to clients.

#### Acceptance Criteria

1. WHEN the User exports a Memo to Word, THE Application SHALL populate the user-uploaded Word Template with the Memo field values and produce a `.docx` file.
2. WHEN the User exports a Memo to PDF, THE Application SHALL populate the Word Template with the Memo field values and produce a `.pdf` file.
3. THE Application SHALL name the exported file using the format "Memo No {N} of Ziyad Madon ({Matter Name})" where {N} is the sequential number portion of the Memo Number (e.g. "Memo No 12 of Ziyad Madon (Varian Arbitration)").
4. WHEN populating the template, THE Application SHALL omit any template line or placeholder that has a blank value, leaving no blank line in the exported document.
5. THE Application SHALL NOT include in the exported document the fields classified as internal only: Firm (LINE 3), Partner (LINE 4), and all payment fields (Lines 25–30).
6. IF no Word Template has been uploaded when the User requests an export, THEN THE Application SHALL display an error message informing the User to upload a template in Settings before exporting.

---

### Requirement 10: Feebook Tab

**User Story:** As a User, I want a consolidated view of all payments received so that I can reconcile income efficiently.

#### Acceptance Criteria

1. WHEN the User opens the Feebook tab, THE Application SHALL display all payment records with the following columns: Memo Number (may be blank for unaccounted entries), Amount Paid (displayed in bold), TDS, Memo Amount, Date of Payment, Bank Account, and Payment Type (indicating full or partial payment).
2. WHEN the User views the Feebook, THE Application SHALL provide a Financial Year filter defaulting to the current Financial Year.
3. WHEN the User views the Feebook, THE Application SHALL provide a Firm filter defaulting to "All".
4. WHEN the User views the Feebook, THE Application SHALL provide a Partner filter defaulting to "All".
5. WHEN the User views the Feebook, THE Application SHALL provide a Bank Account filter defaulting to "All".
6. WHEN the User ticks the "Unaccounted Memos Only" checkbox, THE Application SHALL restrict the Feebook list to payment records where the associated Memo Number is blank.
7. WHEN the User selects "Export to Excel" from the Feebook tab, THE Application SHALL export the currently filtered list of payment records to an Excel file.
8. THE Application SHALL classify a payment as a full payment when the sum of all payments for its Memo equals the Memo's Total Fees, and as a partial payment otherwise.

---

### Requirement 11: Outstanding Memos View

**User Story:** As a User, I want to see all unpaid Memos per Firm so that I can follow up on outstanding invoices.

#### Acceptance Criteria

1. WHEN the User opens the Outstanding Memos view, THE Application SHALL display all Memos whose Status is "Unpaid", regardless of whether the Matter is Active or Archived.
2. WHEN the User views Outstanding Memos, THE Application SHALL provide a Partner filter and a Matter filter (including a "Selected Matters" multi-select option).
3. WHEN the User views Outstanding Memos, THE Application SHALL NOT provide an Active/Archived distinction filter.
4. WHEN the User views Outstanding Memos, THE Application SHALL organise the list by Matter.
5. WHEN the User selects "Export to Excel" from the Outstanding Memos view, THE Application SHALL export a file with columns: Date, Memo Number, Matter Name, and Total Fees, organised by Matter, with a total row at the bottom.

---

### Requirement 12: Statistics Tab

**User Story:** As a User, I want statistical summaries of billing and receipts so that I can understand the practice's financial performance.

#### Acceptance Criteria

1. WHEN the User opens the Statistics tab, THE Application SHALL display aggregated data including: number of Appearances, total amount billed, and total amount received.
2. WHEN the User views Statistics, THE Application SHALL provide views broken down by: Financial Year, Matter, Firm, and Partner.
3. WHEN the User selects a Financial Year breakdown, THE Application SHALL display statistics for each Financial Year in descending order.

---

### Requirement 13: Settings Tab

**User Story:** As a User, I want to configure application-wide defaults and manage reference data so that new Memos are pre-filled accurately.

#### Acceptance Criteria

1. THE Application SHALL allow the User to set a default Fees per Appearance value, which pre-fills LINE 18 on new Memos.
2. THE Application SHALL allow the User to set a default Fees per Conference value, which pre-fills LINE 21 on new Memos.
3. THE Application SHALL allow the User to set a default Fees for Misc/Drafting value, which pre-fills LINE 23 on new Memos.
4. THE Application SHALL allow the User to set default text for Additional Details Left (LINE 9), which pre-fills that field on new Memos.
5. THE Application SHALL allow the User to set default text for Additional Details Right (LINE 10), which pre-fills that field on new Memos.
6. THE Application SHALL allow the User to set a default TDS Rate (LINE 25), defaulting to 10%.
7. THE Application SHALL allow the User to add, edit, and delete Bank Accounts, which are used in LINE 30 of Memos and in payment records.
8. THE Application SHALL allow the User to upload a Word Template file (`.docx` format) for use in Memo export.
9. WHEN the User uploads a Word Template, THE Application SHALL store it and use it for all subsequent Memo exports.
10. THE Application SHALL provide a "Restore from Excel" function that imports previously exported application data from an Excel backup file.

---

### Requirement 14: Backup and Export

**User Story:** As a User, I want to back up all application data to Excel so that I can preserve and restore records.

#### Acceptance Criteria

1. THE Application SHALL provide a Backup/Export control accessible from the top-right area of the application.
2. WHEN the User triggers Backup/Export, THE Application SHALL export all data (Firms, Partners, Matters, Memos, and Payments) to an Excel file.
3. THE Application SHALL include all Memo fields, all payment fields, and all reference data in the backup Excel file.

---

### Requirement 15: Navigation

**User Story:** As a User, I want clear navigation between pages and sub-sections so that I can move through the application without losing context.

#### Acceptance Criteria

1. WHEN the User navigates from a list view to a detail view (e.g. Firm list to Firm detail, Matter list to Memo list), THE Application SHALL display a Back button or breadcrumb navigation that returns the User to the previous view.
2. THE Application SHALL maintain the User's active filter state when the User returns to a list view via the Back button.
3. THE Application SHALL provide a persistent top-level navigation bar with access to the Memos, Feebook, Outstanding Memos, Statistics, and Settings tabs.
