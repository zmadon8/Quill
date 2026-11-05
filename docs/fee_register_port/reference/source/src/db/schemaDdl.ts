/**
 * Embedded, idempotent schema DDL applied at startup by the DB client.
 *
 * Using `CREATE TABLE IF NOT EXISTS` (and `IF NOT EXISTS` indexes) keeps this
 * safe to run on every launch and avoids depending on the on-disk migrations
 * folder being present at runtime in a packaged app. It mirrors the generated
 * Drizzle migration exactly.
 *
 * The `settings` table's data columns come from the shared SETTINGS_COLUMNS
 * catalog so the DDL, migrations, and backup all share one source of truth.
 */
import { settingsColumnsDdl } from './settingsColumns'

export const SCHEMA_DDL = `
CREATE TABLE IF NOT EXISTS firms (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  name text NOT NULL,
  status text DEFAULT 'active' NOT NULL,
  notes text,
  created_at text DEFAULT (datetime('now')) NOT NULL,
  updated_at text DEFAULT (datetime('now')) NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS firms_name_unique ON firms (name);

CREATE TABLE IF NOT EXISTS partners (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  firm_id integer NOT NULL,
  name text NOT NULL,
  created_at text DEFAULT (datetime('now')) NOT NULL,
  FOREIGN KEY (firm_id) REFERENCES firms(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS partners_firm_id_name_unique ON partners (firm_id, name);

CREATE TABLE IF NOT EXISTS matters (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  firm_id integer NOT NULL,
  partner_id integer NOT NULL,
  name text NOT NULL,
  is_archived integer DEFAULT 0 NOT NULL,
  -- Vestigial: custom numbering is now per-memo, not per-matter. Unused.
  is_custom integer DEFAULT 0 NOT NULL,
  addressee_line1 text,
  addressee_line2 text,
  addressee_use_firm_name integer DEFAULT 0 NOT NULL,
  court_name text,
  client text,
  additional_details_left text,
  additional_details_right text,
  plaintiff_name text,
  plaintiff_type text,
  defendant_name text,
  defendant_type text,
  -- Optional short name used in the Word export (file name + matter-name tag).
  short_name text,
  notes text,
  created_at text DEFAULT (datetime('now')) NOT NULL,
  updated_at text DEFAULT (datetime('now')) NOT NULL,
  FOREIGN KEY (firm_id) REFERENCES firms(id),
  FOREIGN KEY (partner_id) REFERENCES partners(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS matters_firm_id_name_unique ON matters (firm_id, name);

CREATE TABLE IF NOT EXISTS bank_accounts (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  name text NOT NULL,
  created_at text DEFAULT (datetime('now')) NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS bank_accounts_name_unique ON bank_accounts (name);

CREATE TABLE IF NOT EXISTS memos (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  memo_number text,
  financial_year text NOT NULL,
  seq integer NOT NULL,
  date text NOT NULL,
  matter_id integer NOT NULL,
  firm_id integer NOT NULL,
  partner_id integer NOT NULL,
  addressee_line1 text NOT NULL,
  addressee_line2 text,
  court_name text,
  additional_details_left text,
  additional_details_right text,
  plaintiff_name text,
  plaintiff_type text,
  defendant_name text,
  defendant_type text,
  client text,
  num_appearances integer DEFAULT 0 NOT NULL,
  dates_of_appearances text,
  fees_per_appearance real DEFAULT 0 NOT NULL,
  num_conferences integer DEFAULT 0 NOT NULL,
  dates_of_conferences text,
  fees_per_conference real DEFAULT 0 NOT NULL,
  misc_drafting_description text,
  fees_misc_drafting real DEFAULT 0 NOT NULL,
  num_drafts integer DEFAULT 0 NOT NULL,
  -- Vestigial: TDS is now recorded per payment, not per memo. Retained for
  -- backward compatibility; always written as 0 and never read.
  tds_rate real DEFAULT 0 NOT NULL,
  written_off integer DEFAULT 0 NOT NULL,
  is_draft integer DEFAULT 0 NOT NULL,
  custom_fees_appearances real,
  custom_fees_conferences real,
  custom_fees_misc real,
  custom_total_fees real,
  created_at text DEFAULT (datetime('now')) NOT NULL,
  updated_at text DEFAULT (datetime('now')) NOT NULL,
  FOREIGN KEY (matter_id) REFERENCES matters(id),
  FOREIGN KEY (firm_id) REFERENCES firms(id),
  FOREIGN KEY (partner_id) REFERENCES partners(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS memos_memo_number_unique ON memos (memo_number);
-- Indexes on the hot filter/join/sort columns so list and statistics queries
-- stay fast as the table grows into the tens of thousands of rows.
CREATE INDEX IF NOT EXISTS memos_financial_year ON memos (financial_year);
CREATE INDEX IF NOT EXISTS memos_matter_id ON memos (matter_id);
CREATE INDEX IF NOT EXISTS memos_firm_id ON memos (firm_id);
CREATE INDEX IF NOT EXISTS memos_partner_id ON memos (partner_id);
CREATE INDEX IF NOT EXISTS memos_date ON memos (date);
CREATE INDEX IF NOT EXISTS memos_is_draft ON memos (is_draft);

CREATE TABLE IF NOT EXISTS payments (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  memo_id integer,
  amount real NOT NULL,
  tds_rate real DEFAULT 0 NOT NULL,
  auto_tds integer DEFAULT 1 NOT NULL,
  tds_amount real DEFAULT 0 NOT NULL,
  -- Vestigial: always written as 0. A payment's memo amount is derived from the
  -- memo itself (see memoTotalFees); do not rely on this column.
  memo_amount real DEFAULT 0 NOT NULL,
  date_of_payment text NOT NULL,
  payee text,
  bank_account_id integer,
  payment_details text,
  payment_mode text,
  created_at text DEFAULT (datetime('now')) NOT NULL,
  updated_at text DEFAULT (datetime('now')) NOT NULL,
  FOREIGN KEY (memo_id) REFERENCES memos(id),
  FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id)
);
CREATE INDEX IF NOT EXISTS payments_memo_id ON payments (memo_id);
CREATE INDEX IF NOT EXISTS payments_date ON payments (date_of_payment);
CREATE INDEX IF NOT EXISTS payments_bank_account_id ON payments (bank_account_id);

CREATE TABLE IF NOT EXISTS settings (
  id integer PRIMARY KEY NOT NULL,
${settingsColumnsDdl()},
  updated_at text DEFAULT (datetime('now')) NOT NULL
);

CREATE TABLE IF NOT EXISTS memo_number_sequences (
  financial_year text PRIMARY KEY NOT NULL,
  last_seq integer DEFAULT 0 NOT NULL
);

-- A single received payment can be allocated across one, several, or no memos.
-- A payment with zero allocations is "unaccounted". A memo's paid amount is the
-- SUM of (amount + tds_amount) of its allocations.
CREATE TABLE IF NOT EXISTS payment_allocations (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  payment_id integer NOT NULL,
  memo_id integer NOT NULL,
  amount real DEFAULT 0 NOT NULL,
  tds_amount real DEFAULT 0 NOT NULL,
  created_at text DEFAULT (datetime('now')) NOT NULL,
  FOREIGN KEY (payment_id) REFERENCES payments(id),
  FOREIGN KEY (memo_id) REFERENCES memos(id)
);
CREATE INDEX IF NOT EXISTS payment_allocations_payment ON payment_allocations (payment_id);
CREATE INDEX IF NOT EXISTS payment_allocations_memo ON payment_allocations (memo_id);

-- Per-month manual adjustments for Statistics: working days and extra
-- appearances/conferences/drafts not captured by memos.
CREATE TABLE IF NOT EXISTS period_adjustments (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  financial_year text NOT NULL,
  month integer NOT NULL,            -- 1..12 (calendar month)
  working_days integer DEFAULT 0 NOT NULL,
  extra_appearances integer DEFAULT 0 NOT NULL,
  extra_conferences integer DEFAULT 0 NOT NULL,
  extra_drafts integer DEFAULT 0 NOT NULL,
  -- Optional per-month overrides: NULL = use the computed value.
  ov_appearances real,
  ov_conferences real,
  ov_drafts real,
  ov_billed real,
  ov_received real,
  ov_received_plus_tds real,
  updated_at text DEFAULT (datetime('now')) NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS period_adjustments_fy_month ON period_adjustments (financial_year, month);

-- Saved Statistics pivot configurations (Option 5).
CREATE TABLE IF NOT EXISTS saved_views (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  name text NOT NULL,
  measure text NOT NULL,
  row_dim text NOT NULL,
  col_dim text NOT NULL,
  firm_id integer,
  from_fy text,
  to_fy text,
  created_at text DEFAULT (datetime('now')) NOT NULL
);
`
