import { useSettingsStore } from '@/stores/useSettingsStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Card } from '@/components/ui/Card'
import type { SettingsDTO } from '@/types/ipc'

type BoolKey = 'backupCloseEnabled' | 'backupDailyEnabled' | 'backupWeeklyEnabled' | 'backupMonthlyEnabled'
type DirKey = 'backupCloseDir' | 'backupDailyDir' | 'backupWeeklyDir' | 'backupMonthlyDir'
type LastKey = 'lastBackupDaily' | 'lastBackupWeekly' | 'lastBackupMonthly'

const JOBS: Array<{
  id: string
  label: string
  note: string
  enabled: BoolKey
  dir: DirKey
  last?: LastKey
}> = [
  { id: 'close', label: 'On closing the program', note: 'One file that overwrites itself each time you quit.', enabled: 'backupCloseEnabled', dir: 'backupCloseDir' },
  { id: 'daily', label: 'Daily', note: 'A new dated file each day (first launch of the day, then hourly checks).', enabled: 'backupDailyEnabled', dir: 'backupDailyDir', last: 'lastBackupDaily' },
  { id: 'weekly', label: 'Weekly', note: 'A new dated file every 7 days.', enabled: 'backupWeeklyEnabled', dir: 'backupWeeklyDir', last: 'lastBackupWeekly' },
  { id: 'monthly', label: 'Monthly', note: 'A new dated file each calendar month.', enabled: 'backupMonthlyEnabled', dir: 'backupMonthlyDir', last: 'lastBackupMonthly' },
]

function lastRun(iso: string | null | undefined): string {
  if (!iso) return 'Never'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'Never'
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** Four independent backup jobs — each with its own tick and folder. */
export function BackupSettings() {
  const { settings, save } = useSettingsStore()
  const show = useToastStore((s) => s.show)
  if (!settings) return null

  const update = async (patch: Partial<SettingsDTO>, okMsg?: string) => {
    const ok = await save(patch)
    if (!ok) show('Could not update backup settings.', 'error')
    else if (okMsg) show(okMsg, 'success')
  }

  const pick = async (job: (typeof JOBS)[number], alsoEnable: boolean) => {
    const res = await window.api.settings.pickFolder()
    if (!res.ok) return show(errorMessage(res.error), 'error')
    if (res.data === null) return
    await update(
      { [job.dir]: res.data, ...(alsoEnable ? { [job.enabled]: true } : {}) } as Partial<SettingsDTO>,
      'Backup folder set.',
    )
  }

  const toggle = async (job: (typeof JOBS)[number], on: boolean) => {
    // Turning a job on with no folder yet: ask for the folder first.
    if (on && !settings[job.dir]) return pick(job, true)
    await update({ [job.enabled]: on } as Partial<SettingsDTO>)
  }

  const backupNow = async () => {
    const res = await window.api.backup.export()
    if (!res.ok) show('Backup failed.', 'error')
    else if (res.data.saved) show('Backup saved.', 'success')
  }

  return (
    <Card className="space-y-3 p-4">
      <h3 className="text-lg font-medium">Automatic Backups</h3>
      <p className="text-sm text-gray-600">
        Tick any combination. Each backup type has its own folder, so you can send them to
        different places (for example, a cloud-synced folder for the daily one).
      </p>
      <div className="divide-y rounded border">
        {JOBS.map((job) => (
          <div key={job.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
            <label className="flex w-56 shrink-0 cursor-pointer items-start gap-2">
              <input
                type="checkbox"
                className="mt-1"
                checked={settings[job.enabled]}
                onChange={(e) => void toggle(job, e.target.checked)}
              />
              <span>
                <span className="block text-sm font-medium">{job.label}</span>
                <span className="block text-xs text-gray-500">{job.note}</span>
              </span>
            </label>
            <div className="flex min-w-[260px] flex-1 items-center gap-2">
              <Input
                readOnly
                value={settings[job.dir] ?? ''}
                placeholder="No folder chosen"
                className="bg-gray-50 text-gray-600"
              />
              <Button variant="secondary" size="sm" onClick={() => void pick(job, false)}>
                Choose…
              </Button>
            </div>
            {job.last && (
              <span className="w-40 shrink-0 text-xs text-gray-400">Last: {lastRun(settings[job.last])}</span>
            )}
            {settings[job.enabled] && !settings[job.dir] && (
              <span className="text-xs text-amber-600">Choose a folder to enable this backup.</span>
            )}
          </div>
        ))}
      </div>
      <div className="flex items-end gap-3">
        <div className="w-48">
          <Label>Keep newest (per dated type)</Label>
          <Input
            type="number"
            min={0}
            value={settings.backupRetention}
            onChange={(e) => void update({ backupRetention: Math.max(0, Math.floor(Number(e.target.value) || 0)) })}
          />
        </div>
        <p className="pb-2 text-xs text-gray-500">
          Older daily / weekly / monthly files beyond this number are deleted. 0 keeps everything.
        </p>
      </div>
      <div className="border-t pt-3">
        <p className="mb-2 text-sm font-medium text-gray-700">Manual backup</p>
        <p className="mb-2 text-xs text-gray-500">Save a full Excel backup of all data to a location you choose.</p>
        <Button variant="secondary" onClick={backupNow}>Back Up Now (Excel)</Button>
      </div>
    </Card>
  )
}
