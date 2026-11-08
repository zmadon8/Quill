import { useEffect, useMemo, useState } from 'react'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Card } from '@/components/ui/Card'
import { currentFinancialYear, recentFinancialYears } from '@/lib/financialYear'
import type { PeriodAdjustmentDTO } from '@/types/ipc'

const MONTHS_IN_FY_ORDER = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
const MONTH_NAMES = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Text-box state for one month: numbers kept as strings so blank = "not set". */
interface MonthForm {
  workingDays: string
  extraAppearances: string
  extraConferences: string
  extraDrafts: string
  overrideAppearances: string
  overrideConferences: string
  overrideDrafts: string
  overrideBilled: string
  overrideReceived: string
  overrideReceivedPlusTds: string
}

const blankForm = (): MonthForm => ({
  workingDays: '', extraAppearances: '', extraConferences: '', extraDrafts: '',
  overrideAppearances: '', overrideConferences: '', overrideDrafts: '',
  overrideBilled: '', overrideReceived: '', overrideReceivedPlusTds: '',
})

const str = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))
const num = (v: string) => (v.trim() === '' ? 0 : Number(v))
const optNum = (v: string) => (v.trim() === '' ? null : Number(v))

const COLS: Array<{ key: keyof MonthForm; label: string; group: 'base' | 'override' }> = [
  { key: 'workingDays', label: 'Working Days', group: 'base' },
  { key: 'extraAppearances', label: '+ Appearances', group: 'base' },
  { key: 'extraConferences', label: '+ Conferences', group: 'base' },
  { key: 'extraDrafts', label: '+ Drafts', group: 'base' },
  { key: 'overrideAppearances', label: 'Appearances', group: 'override' },
  { key: 'overrideConferences', label: 'Conferences', group: 'override' },
  { key: 'overrideDrafts', label: 'Drafts', group: 'override' },
  { key: 'overrideBilled', label: 'Billed', group: 'override' },
  { key: 'overrideReceived', label: 'Received', group: 'override' },
  { key: 'overrideReceivedPlusTds', label: 'Received + TDS', group: 'override' },
]

/**
 * Settings → Edit Statistics. Per month of a financial year:
 *  - working days and extra counts (added to what the memos give), and
 *  - optional override values that REPLACE the computed figure (blank = use
 *    the computed value). Overrides apply to the all-firms Statistics table.
 */
export function EditStatisticsCard() {
  const show = useToastStore((s) => s.show)
  const [initialFy, setInitialFy] = useState('2026-27')
  const [fy, setFy] = useState(currentFinancialYear())
  const [forms, setForms] = useState<Record<number, MonthForm>>({})
  const [saving, setSaving] = useState(false)
  const fyOptions = useMemo(() => recentFinancialYears(8, initialFy), [initialFy])

  useEffect(() => {
    void (async () => {
      const s = await window.api.settings.get()
      if (s.ok) {
        setInitialFy(s.data.initialFinancialYear)
        setFy((cur) => (cur < s.data.initialFinancialYear ? s.data.initialFinancialYear : cur))
      }
    })()
  }, [])

  useEffect(() => {
    void (async () => {
      const res = await window.api.statistics.listAdjustments(fy)
      const map: Record<number, MonthForm> = {}
      for (const m of MONTHS_IN_FY_ORDER) map[m] = blankForm()
      if (res.ok) {
        for (const a of res.data) {
          map[a.month] = {
            workingDays: a.workingDays ? String(a.workingDays) : '',
            extraAppearances: a.extraAppearances ? String(a.extraAppearances) : '',
            extraConferences: a.extraConferences ? String(a.extraConferences) : '',
            extraDrafts: a.extraDrafts ? String(a.extraDrafts) : '',
            overrideAppearances: str(a.overrideAppearances),
            overrideConferences: str(a.overrideConferences),
            overrideDrafts: str(a.overrideDrafts),
            overrideBilled: str(a.overrideBilled),
            overrideReceived: str(a.overrideReceived),
            overrideReceivedPlusTds: str(a.overrideReceivedPlusTds),
          }
        }
      }
      setForms(map)
    })()
  }, [fy])

  const set = (month: number, key: keyof MonthForm, v: string) =>
    setForms((f) => ({ ...f, [month]: { ...f[month], [key]: v } }))

  const save = async () => {
    // Reject anything that isn't a non-negative number.
    for (const m of MONTHS_IN_FY_ORDER) {
      for (const c of COLS) {
        const v = forms[m]?.[c.key] ?? ''
        if (v.trim() !== '' && !(Number(v) >= 0)) {
          show(`${MONTH_NAMES[m]} — ${c.label}: enter a number, or leave blank.`, 'error')
          return
        }
      }
    }
    setSaving(true)
    try {
      for (const m of MONTHS_IN_FY_ORDER) {
        const f = forms[m]
        if (!f) continue
        const dto: PeriodAdjustmentDTO = {
          financialYear: fy,
          month: m,
          workingDays: num(f.workingDays),
          extraAppearances: num(f.extraAppearances),
          extraConferences: num(f.extraConferences),
          extraDrafts: num(f.extraDrafts),
          overrideAppearances: optNum(f.overrideAppearances),
          overrideConferences: optNum(f.overrideConferences),
          overrideDrafts: optNum(f.overrideDrafts),
          overrideBilled: optNum(f.overrideBilled),
          overrideReceived: optNum(f.overrideReceived),
          overrideReceivedPlusTds: optNum(f.overrideReceivedPlusTds),
        }
        const res = await window.api.statistics.saveAdjustment(dto)
        if (!res.ok) {
          show(errorMessage(res.error), 'error')
          return
        }
      }
      show('Statistics saved.', 'success')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Edit Statistics</h3>
        <Select value={fy} onChange={(e) => setFy(e.target.value)} aria-label="Financial year">
          {fyOptions.map((y) => <option key={y} value={y}>{y}</option>)}
        </Select>
      </div>
      <p className="text-sm text-gray-600">
        <strong>Working days</strong> and <strong>+ extras</strong> add to what your memos show and
        feed the per-week figures. The <strong>Override</strong> boxes replace the computed value for that
        month; leave them blank to use the computed figure. Overridden values appear in italics on
        the Statistics tab.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-gray-500">
            <tr>
              <th className="px-2 py-1" rowSpan={2}>Month</th>
              <th className="px-2 py-1" colSpan={4}>Working days &amp; extras</th>
              <th className="border-l px-2 py-1" colSpan={6}>Override (blank = computed)</th>
            </tr>
            <tr>
              {COLS.map((c) => (
                <th key={c.key} className={'px-2 py-1 ' + (c.key === 'overrideAppearances' ? 'border-l' : '')}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {MONTHS_IN_FY_ORDER.map((m) => (
              <tr key={m}>
                <td className="px-2 py-1 font-medium">{MONTH_NAMES[m]}</td>
                {COLS.map((c) => (
                  <td key={c.key} className={'px-1 py-1 ' + (c.key === 'overrideAppearances' ? 'border-l' : '')}>
                    <Input
                      type="number"
                      min={0}
                      className="w-24"
                      aria-label={`${MONTH_NAMES[m]} ${c.label}`}
                      value={forms[m]?.[c.key] ?? ''}
                      onChange={(e) => set(m, c.key, e.target.value)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex justify-end">
        <Button onClick={save} disabled={saving}>Save</Button>
      </div>
    </Card>
  )
}
