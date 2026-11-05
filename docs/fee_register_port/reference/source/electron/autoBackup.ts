/**
 * electron/autoBackup.ts
 *
 * Four independent automatic backup jobs, any mix of which may be active:
 *
 *   close   — written when the app quits; ONE file that overwrites itself.
 *   daily   — a new timestamped file when the calendar day has changed.
 *   weekly  — a new timestamped file when 7+ days have passed.
 *   monthly — a new timestamped file when the calendar month has changed.
 *
 * Each job has its own enable tick and destination folder (Settings). Daily /
 * weekly / monthly are checked once at startup and then hourly. Older files of
 * the same job are pruned down to the retention count (0 = keep everything);
 * only files this module names are ever deleted.
 */
import fs from 'fs'
import path from 'path'
import { db } from '@/db/client'
import { getSettings, updateSettings } from '@/services/settingsService'
import { generateBackupBuffer } from '@/services/backupService'
import type { SettingsDTO } from '@/types/ipc'

export type TimedJob = 'daily' | 'weekly' | 'monthly'

const CLOSE_BACKUP_FILENAME = 'fee-register-autobackup-lastclose.xlsx'
const DAY_MS = 24 * 60 * 60 * 1000

/** Local calendar date key "YYYY-MM-DD" and month key "YYYY-MM". */
const dayKey = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const monthKey = (d: Date) => dayKey(d).slice(0, 7)

/** Whether a timed job is due, given when it last ran. */
export function isJobDue(job: TimedJob, lastIso: string | null, now: Date): boolean {
  if (!lastIso) return true
  const last = new Date(lastIso)
  if (Number.isNaN(last.getTime())) return true
  switch (job) {
    case 'daily':
      return dayKey(last) !== dayKey(now)
    case 'weekly':
      return now.getTime() - last.getTime() >= 7 * DAY_MS
    case 'monthly':
      return monthKey(last) !== monthKey(now)
  }
}

interface JobConfig {
  enabled: boolean
  dir: string | null
  last: string | null
  lastKey: 'lastBackupDaily' | 'lastBackupWeekly' | 'lastBackupMonthly'
}

function jobConfig(s: SettingsDTO, job: TimedJob): JobConfig {
  switch (job) {
    case 'daily':
      return { enabled: s.backupDailyEnabled, dir: s.backupDailyDir, last: s.lastBackupDaily, lastKey: 'lastBackupDaily' }
    case 'weekly':
      return { enabled: s.backupWeeklyEnabled, dir: s.backupWeeklyDir, last: s.lastBackupWeekly, lastKey: 'lastBackupWeekly' }
    case 'monthly':
      return { enabled: s.backupMonthlyEnabled, dir: s.backupMonthlyDir, last: s.lastBackupMonthly, lastKey: 'lastBackupMonthly' }
  }
}

function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
}

/** Deletes the oldest files of a job beyond `keep` (0 = keep all). */
export function pruneBackups(dir: string, job: TimedJob, keep: number): void {
  if (keep <= 0) return
  const prefix = `fee-register-backup-${job}-`
  const files = fs
    .readdirSync(dir)
    .filter((f) => f.startsWith(prefix) && f.endsWith('.xlsx'))
    .sort() // timestamp in the name → lexical order is chronological
  for (const f of files.slice(0, Math.max(0, files.length - keep))) {
    try {
      fs.unlinkSync(path.join(dir, f))
    } catch {
      /* best effort */
    }
  }
}

/** Writes one timed backup (and prunes). Returns the file path. */
async function writeTimedBackup(job: TimedJob, dir: string, keep: number, now: Date): Promise<string> {
  ensureDir(dir)
  const stamp = now.toISOString().slice(0, 19).replace(/[:T]/g, '-')
  const file = path.join(dir, `fee-register-backup-${job}-${stamp}.xlsx`)
  fs.writeFileSync(file, await generateBackupBuffer(db))
  pruneBackups(dir, job, keep)
  return file
}

/** Runs every enabled timed job that is due. Safe to call often. */
export async function runAutoBackupIfDue(now: Date = new Date()): Promise<void> {
  for (const job of ['daily', 'weekly', 'monthly'] as TimedJob[]) {
    const s = getSettings(db)
    const cfg = jobConfig(s, job)
    if (!cfg.enabled || !cfg.dir) continue
    if (!isJobDue(job, cfg.last, now)) continue
    try {
      await writeTimedBackup(job, cfg.dir, s.backupRetention, now)
      updateSettings(db, { [cfg.lastKey]: now.toISOString() })
    } catch (err) {
      // Non-fatal: leave the last-run time unchanged so it retries next tick.
      console.error(`Automatic ${job} backup failed:`, (err as Error).message)
    }
  }
}

let timer: NodeJS.Timeout | null = null

/** Starts the periodic check (hourly) and runs one immediately. */
export function startAutoBackup(): void {
  void runAutoBackupIfDue()
  if (timer) clearInterval(timer)
  timer = setInterval(() => void runAutoBackupIfDue(), 60 * 60 * 1000)
}

/**
 * The "on closing" job: a single file that OVERWRITES itself each time, in the
 * close job's own folder. No-op unless the job is enabled and has a folder.
 */
export async function writeCloseBackup(): Promise<void> {
  const s = getSettings(db)
  if (!s.backupCloseEnabled || !s.backupCloseDir) return
  try {
    ensureDir(s.backupCloseDir)
    fs.writeFileSync(path.join(s.backupCloseDir, CLOSE_BACKUP_FILENAME), await generateBackupBuffer(db))
  } catch (err) {
    // Non-fatal: never block app shutdown on a backup failure.
    console.error('Close backup failed:', (err as Error).message)
  }
}
