CREATE TABLE `bank_accounts` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`name` text NOT NULL,
	`created_at` text DEFAULT (datetime('now')) NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `bank_accounts_name_unique` ON `bank_accounts` (`name`);--> statement-breakpoint
CREATE TABLE `firms` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`name` text NOT NULL,
	`created_at` text DEFAULT (datetime('now')) NOT NULL,
	`updated_at` text DEFAULT (datetime('now')) NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `firms_name_unique` ON `firms` (`name`);--> statement-breakpoint
CREATE TABLE `matters` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`firm_id` integer NOT NULL,
	`partner_id` integer NOT NULL,
	`name` text NOT NULL,
	`is_archived` integer DEFAULT 0 NOT NULL,
	`created_at` text DEFAULT (datetime('now')) NOT NULL,
	`updated_at` text DEFAULT (datetime('now')) NOT NULL,
	FOREIGN KEY (`firm_id`) REFERENCES `firms`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`partner_id`) REFERENCES `partners`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `matters_firm_id_name_unique` ON `matters` (`firm_id`,`name`);--> statement-breakpoint
CREATE TABLE `memo_number_sequences` (
	`financial_year` text PRIMARY KEY NOT NULL,
	`last_seq` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE TABLE `memos` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`memo_number` text NOT NULL,
	`financial_year` text NOT NULL,
	`seq` integer NOT NULL,
	`date` text NOT NULL,
	`matter_id` integer NOT NULL,
	`firm_id` integer NOT NULL,
	`partner_id` integer NOT NULL,
	`addressee_line1` text NOT NULL,
	`addressee_line2` text,
	`court_name` text,
	`additional_details_left` text,
	`additional_details_right` text,
	`plaintiff_name` text,
	`plaintiff_type` text,
	`defendant_name` text,
	`defendant_type` text,
	`client` text,
	`num_appearances` integer DEFAULT 0 NOT NULL,
	`dates_of_appearances` text,
	`fees_per_appearance` real DEFAULT 0 NOT NULL,
	`num_conferences` integer DEFAULT 0 NOT NULL,
	`dates_of_conferences` text,
	`fees_per_conference` real DEFAULT 0 NOT NULL,
	`misc_drafting_description` text,
	`fees_misc_drafting` real DEFAULT 0 NOT NULL,
	`tds_rate` real DEFAULT 10 NOT NULL,
	`created_at` text DEFAULT (datetime('now')) NOT NULL,
	`updated_at` text DEFAULT (datetime('now')) NOT NULL,
	FOREIGN KEY (`matter_id`) REFERENCES `matters`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`firm_id`) REFERENCES `firms`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`partner_id`) REFERENCES `partners`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `memos_memo_number_unique` ON `memos` (`memo_number`);--> statement-breakpoint
CREATE TABLE `partners` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`firm_id` integer NOT NULL,
	`name` text NOT NULL,
	`created_at` text DEFAULT (datetime('now')) NOT NULL,
	FOREIGN KEY (`firm_id`) REFERENCES `firms`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `partners_firm_id_name_unique` ON `partners` (`firm_id`,`name`);--> statement-breakpoint
CREATE TABLE `payments` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`memo_id` integer,
	`amount` real NOT NULL,
	`tds_amount` real DEFAULT 0 NOT NULL,
	`memo_amount` real DEFAULT 0 NOT NULL,
	`date_of_payment` text NOT NULL,
	`payee` text,
	`bank_account_id` integer,
	`payment_details` text,
	`created_at` text DEFAULT (datetime('now')) NOT NULL,
	`updated_at` text DEFAULT (datetime('now')) NOT NULL,
	FOREIGN KEY (`memo_id`) REFERENCES `memos`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`bank_account_id`) REFERENCES `bank_accounts`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `settings` (
	`id` integer PRIMARY KEY NOT NULL,
	`default_fees_per_appearance` real DEFAULT 0 NOT NULL,
	`default_fees_per_conference` real DEFAULT 0 NOT NULL,
	`default_fees_misc_drafting` real DEFAULT 0 NOT NULL,
	`default_additional_details_left` text,
	`default_additional_details_right` text,
	`default_tds_rate` real DEFAULT 10 NOT NULL,
	`word_template_path` text,
	`updated_at` text DEFAULT (datetime('now')) NOT NULL
);
