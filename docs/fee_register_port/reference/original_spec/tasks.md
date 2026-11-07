# Implementation Plan: Fee Register

## Overview

Build a fully working Electron + React + TypeScript desktop application for a legal practitioner to raise, track, and export legal invoices (Memos). The implementation follows the layered architecture defined in the design: SQLite database via Drizzle ORM, a pure service layer, typed IPC channels via contextBridge, and a React UI with Zustand state management and shadcn/ui components.

Tasks are ordered so each step produces working, integrated code — no orphaned modules.

---

## Tasks

- [x] 1. Scaffold project structure and tooling
  - Initialise a new Electron + Vite project using `electron-vite` with React and TypeScript
  - Configure `tsconfig.json` for both main and renderer processes
  - Install and configure Tailwind CSS and shadcn/ui
  - Install core runtime dependencies: `better-sqlite3`, `drizzle-orm`, `drizzle-kit`, `docxtemplater`, `pizzip`, `libreoffice-convert`, `exceljs`, `zustand`, `fast-check`, `vitest`
  - Install dev dependencies: `@types/better-sqlite3`, `electron-rebuild`, `electron-builder`
  - Create the full directory skeleton from the design (`electron/`, `src/`, `tests/`)
  - Configure `vitest.config.ts` for unit and property test suites
  - _Requirements: all (project foundation)_

- [x] 2. Database schema and migrations
  - [x] 2.1 Define Drizzle ORM schema in `src/db/schema.ts`
    - Define all seven tables: `firms`, `partners`, `matters`, `memos`, `payments`, `bank_accounts`, `settings`, `memo_number_sequences` exactly as specified in the design
    - Add all constraints, defaults, unique indexes, and foreign keys
    - _Requirements: 1.1, 2.1, 3.1, 4.2, 8.2, 13.6, 13.7_

  - [x] 2.2 Create database client singleton in `src/db/client.ts`
    - Initialise `better-sqlite3` pointing to the user's app-data directory
    - Wrap with Drizzle client
    - Enable WAL mode and foreign key enforcement
    - Seed the single-row `settings` record on first run
    - _Requirements: 13.1–13.6_

  - [x]* 2.3 Write property test for schema uniqueness constraints
    - **Property 1: Firm names are unique**
    - **Validates: Requirements 1.1**

  - [x] 2.4 Generate and apply initial migration with `drizzle-kit generate`
    - Verify migration runs cleanly and all tables exist
    - _Requirements: all DB-backed requirements_

- [x] 3. Core service — Memo number generation
  - [x] 3.1 Implement `memoNumberService.ts`
    - `deriveFinancialYear(date: string): string` — April–March boundary logic
    - `generateMemoNumber(db, date): string` — exclusive transaction against `memo_number_sequences`, increments `last_seq`, never decrements on delete
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x]* 3.2 Write property tests for memo number service
    - **Property 8: Memo number format and financial year boundary are correct for any date**
    - **Validates: Requirements 3.1, 3.2**

  - [x]* 3.3 Write property test for sequential uniqueness
    - **Property 9: Sequential counter starts at 1 for each new financial year**
    - **Property 10: All Memo numbers across any sequence of creations are pairwise distinct**
    - **Property 11: Deleted Memo numbers are never reused**
    - **Validates: Requirements 3.3, 3.4, 3.5**

- [x] 4. Core service — Fees in Words
  - [x] 4.1 Implement `feesInWordsService.ts`
    - Pure TypeScript, no external packages
    - Handles crore, lakh, thousand, hundred, paise
    - Output always prefixed "Rupees" and suffixed "Only"
    - _Requirements: 4.6_

  - [x]* 4.2 Write property tests for fees in words
    - **Property 14: Fees in Words always starts with "Rupees" and ends with "Only"**
    - **Validates: Requirements 4.6**

  - [x]* 4.3 Write unit tests for feesInWordsService
    - Known amounts: 0, round thousands, one lakh, ten lakhs, one crore, amounts with paise
    - _Requirements: 4.6_

- [x] 5. Checkpoint — Core services
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. IPC layer — Firms and Partners
  - [x] 6.1 Implement `electron/ipc/firms.ts` IPC handlers
    - `firms.create`, `firms.list`, `firms.get`, `firms.update`, `firms.addPartner`, `firms.removePartner`
    - `firms.list` returns firms sorted alphabetically (case-insensitive)
    - `firms.get` returns full `FirmDetail` with partners and matters
    - `firms.create` and `firms.update` enforce unique name; return `{ error: "DUPLICATE_FIRM_NAME" }` on conflict
    - Firm status (active/archived) derived from its Matters
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7_

  - [x]* 6.2 Write property tests for Firm classification and sort order
    - **Property 2: Firm active/archived classification matches its Matters**
    - **Property 3: Firms list is always alphabetically sorted**
    - **Validates: Requirements 1.3, 1.4**

- [x] 7. IPC layer — Matters
  - [x] 7.1 Implement `electron/ipc/matters.ts` IPC handlers
    - `matters.create`, `matters.list`, `matters.get`, `matters.archive`, `matters.unarchive`
    - New Matters default to `is_archived = false`
    - `matters.list` returns Matters sorted by Partner then alphabetically within Partner (case-insensitive)
    - Guard against creating a Memo for an archived Matter (checked in memo handler, not here)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x]* 7.2 Write property tests for Matter lifecycle
    - **Property 4: Matters within a Partner are always alphabetically sorted**
    - **Property 5: New Matters always start as Active**
    - **Property 6: Archive → Unarchive is a round-trip for Matter status**
    - **Validates: Requirements 1.8, 2.2, 2.3, 2.4**

- [x] 8. IPC layer — Memos
  - [x] 8.1 Implement `electron/ipc/memos.ts` core CRUD handlers
    - `memos.create` — validates required fields (`date`, `matter_id`, `total_fees > 0`), checks matter is not archived, calls `generateMemoNumber`, inserts memo
    - `memos.get` — returns full `MemoDetail` with all computed fields calculated at read time
    - `memos.update` — re-validates required fields, updates memo
    - `memos.delete` — deletes memo; does NOT decrement `memo_number_sequences.last_seq`
    - Computed fields: `fees_appearances`, `fees_conferences`, `total_fees`, `total_fees_in_words` (via feesInWordsService), `less_tds`, `amount_paid` (SUM), `date_of_last_payment` (MAX), `status`
    - _Requirements: 3.1–3.5, 4.1–4.11_

  - [x] 8.2 Implement `memos.list`, `memos.createBasedOn`, and bulk export handler stubs
    - `memos.list` with `MemoFilter` — financial year, firm, partner, matter, selectedMatters, unpaidOnly
    - `memos.createBasedOn` — copies all non-payment non-calculated fields, clears `memo_number`, `date`, and payment lines 27–30
    - `memos.bulkExportExcel` stub (wired to exportService in task 11)
    - Memos list columns: Memo Number, Date, Firm, Matter Name, Total Fees, Amount Paid, Date of Last Payment, Status
    - _Requirements: 5.1, 5.2, 5.3, 7.1–7.8_

  - [x]* 8.3 Write property tests for Memo validation and computed fields
    - **Property 7: Archived Matters reject all Memo creation attempts**
    - **Property 12: Fee line item amounts equal count × rate**
    - **Property 13: Total Fees equals the sum of all three fee components**
    - **Property 15: Less TDS equals total fees × rate / 100**
    - **Property 17: Memo save is rejected when any required field is absent**
    - **Property 18: "Create Based On" preserves non-payment non-calculated fields and clears the rest**
    - **Validates: Requirements 2.7, 4.3, 4.4, 4.5, 4.7, 4.10, 4.11, 5.1, 5.2, 5.3**

- [x] 9. IPC layer — Payments, Settings, and Feebook
  - [x] 9.1 Implement `electron/ipc/payments.ts`
    - `payments.addToMemo`, `payments.update`, `payments.delete`, `payments.listForMemo`
    - `payment_type` derived: `'Full'` if `SUM(all payments for memo) = total_fees`, else `'Partial'`
    - `payment_details` field stored but never returned in any export
    - _Requirements: 8.1–8.7_

  - [x]* 9.2 Write property test for payment aggregate and status
    - **Property 19: Payment aggregate determines Memo status and payment type simultaneously**
    - **Validates: Requirements 7.2, 10.8**

  - [x] 9.3 Implement `electron/ipc/settings.ts`
    - `settings.get`, `settings.update` — single-row settings table
    - `settings.addBankAccount`, `settings.updateBankAccount`, `settings.deleteBankAccount`
    - `settings.uploadTemplate` — copies `.docx` to app data directory, stores path
    - `settings.restoreFromExcel` stub (wired to backupService in task 11)
    - _Requirements: 13.1–13.10_

  - [x] 9.4 Implement `electron/ipc/feebook.ts`
    - `feebook.list` with `FeebookFilter` — financial year, firm, partner, bank account, unaccountedOnly
    - Feebook columns: Memo Number, Amount Paid (bold in UI), TDS, Memo Amount, Date of Payment, Bank Account, Payment Type
    - `feebook.exportExcel` stub (wired to exportService in task 11)
    - _Requirements: 10.1–10.8_

- [x] 10. IPC layer — Outstanding, Statistics, and Backup
  - [x] 10.1 Implement `electron/ipc/outstanding.ts` and `statistics.ts`
    - `outstanding.list` with `OutstandingFilter` — partner, matter, selectedMatters; shows all Unpaid Memos regardless of Matter archived status; grouped by Matter
    - `outstanding.exportExcel` stub (wired in task 11)
    - `statistics.get` with breakdown by financialYear, matter, firm, partner; financial year breakdown in descending order
    - _Requirements: 11.1–11.5, 12.1–12.3_

  - [x]* 10.2 Write property test for statistics aggregates
    - **Property 21: Statistics aggregates equal the sum of individual Memo values**
    - **Validates: Requirements 12.1**

  - [x] 10.3 Implement `backup.export()` IPC handler stub (wired to backupService in task 11)
    - _Requirements: 14.1, 14.2, 14.3_

- [x] 11. Service layer — Export and Backup
  - [x] 11.1 Implement `exportService.ts` — Word export
    - Load user template from `settings.word_template_path`; return `{ error: "NO_TEMPLATE" }` if null
    - Build full placeholder map with all LINE_N keys as specified in the design
    - Configure docxtemplater with `paragraphLoop: true`, `nullGetter: () => ""`
    - Post-render pass: remove paragraphs that resolve entirely to empty string (Req 9.4)
    - Derive filename: `Memo No ${seq} of Ziyad Madon (${matterName}).docx`
    - Open Electron save dialog and write `.docx` buffer
    - Internal fields (LINE_3, LINE_4, Lines 25–30) excluded from placeholder map
    - _Requirements: 9.1, 9.3, 9.4, 9.5, 9.6_

  - [x] 11.2 Implement `exportService.ts` — PDF export
    - Reuse Word export pipeline to produce a `.docx` buffer
    - Write to `os.tmpdir()`, call `libreoffice-convert`, clean up temp file
    - Catch LibreOffice-not-found error; return `{ error: "LIBREOFFICE_NOT_FOUND" }`
    - Derive filename with `.pdf` extension using same format
    - Open Electron save dialog and write PDF buffer
    - _Requirements: 9.2, 9.3_

  - [x] 11.3 Implement `exportService.ts` — Excel exports (Memos bulk, Feebook, Outstanding)
    - `bulkExportMemos(filter)` — all visible Memo columns to `.xlsx`
    - `exportFeebook(filter)` — Feebook columns to `.xlsx`
    - `exportOutstanding(filter)` — Date, Memo Number, Matter Name, Total Fees grouped by Matter with a total row at bottom
    - Wire stubs from tasks 8.2, 9.4, 10.1
    - _Requirements: 7.13, 10.7, 11.5_

  - [x] 11.4 Implement `backupService.ts` — full backup and restore
    - `backup.export()` — ExcelJS workbook with sheets: Firms, Partners, Matters, Memos, Payments, BankAccounts, Settings; all stored fields included; open save dialog
    - `settings.restoreFromExcel()` — validate sheets/columns, prompt user confirmation, truncate all tables in dependency order, re-insert from workbook, recompute `memo_number_sequences`
    - Wire stubs from tasks 9.3, 10.3
    - _Requirements: 13.10, 14.1, 14.2, 14.3_

  - [x]* 11.5 Write property test for export filename format
    - **Property 20: Export filename matches the required format for any Memo**
    - **Validates: Requirements 9.3**

  - [x]* 11.6 Write property test for backup round-trip
    - **Property 22: Backup round-trip preserves all data**
    - **Validates: Requirements 14.2, 14.3**

- [x] 12. Checkpoint — All IPC and service layer
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Electron main process wiring
  - [x] 13.1 Set up `electron/main.ts`
    - Create `BrowserWindow` with correct `webPreferences` (contextIsolation, preload path)
    - Register all IPC handlers from tasks 6–10
    - On first launch detect LibreOffice presence; display one-time notice if missing
    - _Requirements: all (app shell)_

  - [x] 13.2 Set up `electron/preload.ts` contextBridge
    - Expose typed `window.api` with all IPC namespaces: `firms`, `matters`, `memos`, `payments`, `feebook`, `outstanding`, `statistics`, `settings`, `backup`
    - All methods return `Promise<IPCResponse<T>>`
    - _Requirements: all (IPC surface)_

- [x] 14. Zustand stores and global UI state
  - Implement stores in `src/stores/`:
    - `useFirmStore` — firm list, active filter (All/Active/Archived, default Active)
    - `useMatterStore` — matter list, active filter (All/Active/Archived, default Active)
    - `useMemoStore` — memo list, active filters (financialYear default current, firm default All, partner default All, matter, selectedMatters, unpaidOnly)
    - `useFeebookStore` — feebook list, active filters (financialYear default current, firm, partner, bankAccount, unaccountedOnly)
    - `useOutstandingStore` — outstanding list, active filters
    - `useStatisticsStore` — breakdown selector
    - `useSettingsStore` — settings values, bank accounts
  - Each store exposes load action (calls IPC) and persists filter state for Back navigation (Req 15.2)
  - _Requirements: 1.5, 7.3–7.8, 10.2–10.6, 15.2_

- [x] 15. App shell and navigation
  - [x] 15.1 Implement `App.tsx` and `TopNav` component
    - Persistent top-level tab bar: Memos | Feebook | Outstanding | Statistics | Settings
    - `BackupButton` in top-right area
    - _Requirements: 14.1, 15.3_

  - [x] 15.2 Implement routing / view stack with Back navigation
    - Simple view-stack (no router library needed for an Electron app unless preferred)
    - `Back` button / breadcrumb on all detail views
    - Restores filter state on Back (Req 15.2)
    - _Requirements: 15.1, 15.2_

- [x] 16. Firms UI
  - [x] 16.1 Implement `FirmList` component
    - Alphabetically sorted list of Firms
    - Dropdown filter: All / Active / Archived (default Active)
    - "Create Firm" button; inline "New Matter" button per row
    - Row click navigates to `FirmDetailPage`
    - _Requirements: 1.4, 1.5, 1.6, 1.11_

  - [x] 16.2 Implement `FirmDetailPage` component
    - Edit form for Firm name and Partners (add/remove)
    - Matters organised by Partner, then alphabetically within Partner
    - Dropdown filter for Matters: All / Active / Archived (default Active)
    - Archive / unarchive individual Matters
    - _Requirements: 1.7, 1.8, 1.9, 1.10_

- [x] 17. Matters UI
  - Implement `MatterDetailPage` component
    - Shows all Memos within the Matter
    - "New Memo" button (blocked with error toast if Matter is Archived)
    - Dropdown filter: Active / Archived / All (default Active)
    - _Requirements: 2.5, 2.6, 2.7_

- [x] 18. Memo form UI
  - [x] 18.1 Implement `MemoForm` base component
    - All 30 LINE fields as per Req 4.2 with correct input types (text, number, multi-line textarea, date picker, dropdown for Bank Account)
    - Memo Number field: read-only, shows "(auto)" until saved
    - Addressee Line 1 pre-filled from Firm name; TDS Rate and fees defaults pre-filled from Settings
    - Real-time reactive calculation panel: Fees for Appearances, Fees for Conferences, Total Fees, Total Fees in Words, Less TDS
    - Required-field validation with inline error messages (date, matter, total_fees > 0)
    - _Requirements: 4.1–4.11_

  - [x] 18.2 Add "Create Based On" support to MemoForm
    - When opened via `createBasedOn`, pre-fill from returned `MemoFormData`, leave Date blank, clear payment fields
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 18.3 Implement save options in MemoForm
    - Three buttons: "Save", "Save & Export to Word", "Save & Export to PDF"
    - Each calls the appropriate IPC chain; shows error toast if no template uploaded
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ]* 18.4 Write unit tests for MemoForm pre-fill logic
    - Verify Settings values propagate correctly to form defaults
    - **Property 16: New Memo form pre-fills match current Settings values**
    - **Validates: Requirements 4.9_**

- [x] 19. Memos list UI
  - Implement `MemosPage` with `MemoList` and filter bar
    - Columns: Memo Number, Date, Firm, Matter Name, Total Fees, Amount Paid, Date of Last Payment, Status
    - Filter bar: Financial Year (desc, default current), Firm (default All), Partner (default All), Matter, Selected Matters checkbox + multi-select, Unpaid Only checkbox
    - Per-row actions: Edit, Mark Payment, Export to Word, Export to PDF
    - "Bulk Export to Excel" button
    - _Requirements: 7.1–7.13_

- [x] 20. Payment modal UI
  - Implement `PaymentModal` component
    - Payment summary: total paid vs total fees
    - List of existing payments with Edit and Delete actions
    - "Add Payment" form with fields: Amount, TDS Amount, Memo Amount, Date of Payment, Payee, Bank Account (dropdown), Payment Details (internal note)
    - Each add/edit/delete persists immediately via IPC; summary recalculates
    - On modal close, Memo list row refreshes
    - _Requirements: 8.1–8.7_

- [x] 21. Feebook UI
  - Implement `FeebookPage` with `FeebookList` and filter bar
    - Columns: Memo Number, Amount Paid (bold), TDS, Memo Amount, Date of Payment, Bank Account, Payment Type
    - Filter bar: Financial Year (default current), Firm (default All), Partner (default All), Bank Account (default All), Unaccounted Memos Only checkbox
    - Edit payment record inline (from Feebook tab)
    - "Export to Excel" button
    - _Requirements: 10.1–10.8_

- [x] 22. Outstanding Memos UI
  - Implement `OutstandingPage` with `OutstandingList` and filter bar
    - Lists all Unpaid Memos regardless of Matter archived status
    - Filter bar: Partner filter, Matter filter, Selected Matters multi-select option
    - No Active/Archived distinction filter
    - List organised by Matter
    - "Export to Excel" button (columns: Date, Memo Number, Matter Name, Total Fees; total row at bottom)
    - _Requirements: 11.1–11.5_

- [x] 23. Statistics UI
  - Implement `StatisticsPage`
    - Breakdown selector: Financial Year | Matter | Firm | Partner
    - Financial Year breakdown displays years in descending order
    - Shows: number of Appearances, total amount billed, total amount received per grouping
    - _Requirements: 12.1–12.3_

- [x] 24. Settings UI
  - Implement `SettingsPage` with three sections:
    - `DefaultsForm` — Fees per Appearance, Fees per Conference, Fees Misc/Drafting, Additional Details Left/Right, TDS Rate (default 10%)
    - `BankAccountManager` — add, edit, delete Bank Accounts
    - `TemplateUploader` — upload `.docx` file; show current template filename; show error guidance if no template is set
    - "Restore from Excel" button with confirmation dialog ("This replaces all data. Cannot be undone.")
    - _Requirements: 13.1–13.10_

- [x] 25. Backup button UI
  - Wire `BackupButton` in `TopNav` to `backup.export()` IPC
  - Shows success/error toast
  - _Requirements: 14.1_

- [x] 26. Error handling and toasts
  - Implement global error toast / snackbar component
  - Wire all IPC error responses to user-visible messages:
    - `DUPLICATE_FIRM_NAME` / `DUPLICATE_MATTER_NAME` → inline field error
    - `MATTER_ARCHIVED` → error toast on Memo creation attempt
    - `NO_TEMPLATE` → toast with link to Settings
    - `LIBREOFFICE_NOT_FOUND` → toast with setup guidance
    - SQLite / backup errors → error toast with message
  - _Requirements: 4.11, 9.6, all error handling scenarios in design_

- [x] 27. Final integration and wiring
  - [x] 27.1 Wire all UI components to IPC stores end-to-end
    - Confirm every user action in every view calls the correct IPC handler
    - Confirm filter state is preserved on Back navigation for all list views
    - Confirm LibreOffice first-launch detection notice is shown
    - _Requirements: 15.1, 15.2, 15.3_

  - [x]* 27.2 Write integration tests for critical end-to-end flows
    - Full Memo creation flow including number generation (same FY and cross-year boundary)
    - Payment recording and status update on Memo list row
    - Archive/unarchive round-trip; blocked Memo creation on archived Matter
    - Backup export → restore → verify data equivalence
    - _Requirements: 3.1–3.5, 7.2, 8.1–8.5, 14.2, 14.3_

- [x] 28. Final checkpoint — Ensure all tests pass
  - Ensure all unit, property, and integration tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; they validate correctness properties but are not required for the app to function.
- Each task references specific requirements for traceability.
- Computed Memo fields (`fees_appearances`, `fees_conferences`, `total_fees`, `total_fees_in_words`, `less_tds`, `amount_paid`, `status`) are always recalculated at read time and never stored in the database.
- The `payment_details` field is stored but deliberately excluded from all exports, Feebook views, and backup exports per Requirement 8.7 and design spec.
- LibreOffice must be installed by the user for PDF export; the app handles the missing-LibreOffice case gracefully.
- Word template placeholders follow the `LINE_N_*` naming convention in the design's export pipeline section.
- Property-based tests use `fast-check` with a minimum of 100 iterations per property.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1"] },
    { "id": 1, "tasks": ["2.2", "3.1", "4.1"] },
    { "id": 2, "tasks": ["2.3", "2.4", "3.2", "3.3", "4.2", "4.3"] },
    { "id": 3, "tasks": ["6.1", "7.1", "9.3"] },
    { "id": 4, "tasks": ["6.2", "7.2", "8.1", "9.1", "9.4", "10.1"] },
    { "id": 5, "tasks": ["8.2", "8.3", "9.2", "10.2", "10.3"] },
    { "id": 6, "tasks": ["11.1", "11.2", "11.3", "11.4"] },
    { "id": 7, "tasks": ["11.5", "11.6", "13.1", "13.2"] },
    { "id": 8, "tasks": ["15.1", "15.2"] },
    { "id": 9, "tasks": ["16.1", "16.2", "18.1"] },
    { "id": 10, "tasks": ["17", "18.2", "18.3", "19", "21", "22", "23", "24"] },
    { "id": 11, "tasks": ["18.4", "20", "25", "26"] },
    { "id": 12, "tasks": ["27.1"] },
    { "id": 13, "tasks": ["27.2"] }
  ]
}
```
