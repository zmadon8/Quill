import { useEffect, useMemo, useState } from 'react'
import { cn } from '@/lib/cn'
import { useSettingsStore } from '@/stores/useSettingsStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { confirmDialog } from '@/stores/useConfirmStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { Card } from '@/components/ui/Card'
import { ImportMemosDialog } from '@/components/settings/ImportMemosDialog'
import { useHistoryStore } from '@/stores/useHistoryStore'
import { applySettings } from '@/lib/applySettings'
import { BackupSettings } from '@/components/settings/BackupSettings'
import { EditStatisticsCard } from '@/components/settings/EditStatisticsCard'
import { DiagnosticsCard } from '@/components/settings/DiagnosticsCard'
import { ShortcutsCard } from '@/components/settings/ShortcutsCard'
import type { DefaultPaymentAmount } from '@/types/ipc'

type SettingsTab = 'defaults' | 'statistics' | 'backup' | 'other'
const SETTINGS_TABS: Array<{ id: SettingsTab; label: string }> = [
  { id: 'defaults', label: 'Defaults' },
  { id: 'statistics', label: 'Start Years & Statistics' },
  { id: 'backup', label: 'Backup & Data' },
  { id: 'other', label: 'Other' },
]

export function SettingsPage() {
  const { settings, bankAccounts, load, save, reloadBankAccounts } = useSettingsStore()
  const show = useToastStore((s) => s.show)
  const { undoStack, redoStack, refresh: refreshHistory } = useHistoryStore()
  const [form, setForm] = useState({
    defaultFeesPerAppearance: 0,
    defaultFeesPerConference: 0,
    defaultFeesMiscDrafting: 0,
    defaultCourtName: '',
    defaultTdsRate: 10,
    defaultPaymentAmount: 'zero' as DefaultPaymentAmount,
    overdueDays: 0,
    defaultTab: 'memos',
    initialFinancialYear: '2026-27',
    memosStartYear: '2026-27',
    feebookStartYear: '2026-27',
    moneyUnit: 'full' as 'full' | 'truncated',
    moneySuffixThousands: 'k',
    moneySuffixLac: 'lac',
    moneySuffixCrore: 'cr',
    hidePaymentWhenPaid: false,
    defaultLinesEnabled: true,
    showStatusDots: true,
    zoomFactor: 1,
    defaultAdditionalDetailsLeft: '',
    defaultAdditionalDetailsRight: '',
  })
  const [newBank, setNewBank] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [appVersion, setAppVersion] = useState('')
  const [tab, setTab] = useState<SettingsTab>('defaults')

  useEffect(() => {
    void load()
    void refreshHistory()
    void (async () => {
      const res = await window.api.system.appVersion()
      if (res.ok) setAppVersion(res.data)
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (settings) {
      setForm({
        defaultFeesPerAppearance: settings.defaultFeesPerAppearance,
        defaultFeesPerConference: settings.defaultFeesPerConference,
        defaultFeesMiscDrafting: settings.defaultFeesMiscDrafting,
        defaultCourtName: settings.defaultCourtName ?? '',
        defaultTdsRate: settings.defaultTdsRate,
        defaultPaymentAmount: settings.defaultPaymentAmount ?? 'zero',
        overdueDays: settings.overdueDays ?? 0,
        defaultTab: settings.defaultTab ?? 'memos',
        initialFinancialYear: settings.initialFinancialYear ?? '2026-27',
        memosStartYear: settings.memosStartYear ?? '2026-27',
        feebookStartYear: settings.feebookStartYear ?? '2026-27',
        moneyUnit: settings.moneyUnit ?? 'full',
        moneySuffixThousands: settings.moneySuffixThousands,
        moneySuffixLac: settings.moneySuffixLac,
        moneySuffixCrore: settings.moneySuffixCrore,
        hidePaymentWhenPaid: settings.hidePaymentWhenPaid,
        defaultLinesEnabled: settings.defaultLinesEnabled ?? true,
        showStatusDots: settings.showStatusDots,
        zoomFactor: settings.zoomFactor,
        defaultAdditionalDetailsLeft: settings.defaultAdditionalDetailsLeft ?? '',
        defaultAdditionalDetailsRight: settings.defaultAdditionalDetailsRight ?? '',
      })
    }
  }, [settings])

  const n = (v: string) => (v === '' ? 0 : Number(v))

  // The form as last saved, to show an "unsaved changes" hint and keep Save quiet otherwise.
  const saved = useMemo(
    () =>
      settings
        ? {
            defaultFeesPerAppearance: settings.defaultFeesPerAppearance,
            defaultFeesPerConference: settings.defaultFeesPerConference,
            defaultFeesMiscDrafting: settings.defaultFeesMiscDrafting,
            defaultCourtName: settings.defaultCourtName ?? '',
            defaultTdsRate: settings.defaultTdsRate,
            defaultPaymentAmount: settings.defaultPaymentAmount ?? 'zero',
            overdueDays: settings.overdueDays ?? 0,
            defaultTab: settings.defaultTab ?? 'memos',
            initialFinancialYear: settings.initialFinancialYear ?? '2026-27',
            memosStartYear: settings.memosStartYear ?? '2026-27',
            feebookStartYear: settings.feebookStartYear ?? '2026-27',
            moneyUnit: settings.moneyUnit ?? 'full',
            moneySuffixThousands: settings.moneySuffixThousands,
            moneySuffixLac: settings.moneySuffixLac,
            moneySuffixCrore: settings.moneySuffixCrore,
            hidePaymentWhenPaid: settings.hidePaymentWhenPaid,
            defaultLinesEnabled: settings.defaultLinesEnabled ?? true,
            showStatusDots: settings.showStatusDots,
            zoomFactor: settings.zoomFactor,
            defaultAdditionalDetailsLeft: settings.defaultAdditionalDetailsLeft ?? '',
            defaultAdditionalDetailsRight: settings.defaultAdditionalDetailsRight ?? '',
          }
        : null,
    [settings],
  )
  const dirty = saved !== null && JSON.stringify(saved) !== JSON.stringify(form)

  const saveDefaults = async () => {
    const ok = await save(form)
    if (ok) {
      // Push the saved values to every client-side consumer so money display,
      // dots, zoom and font change instantly (no restart).
      const saved = useSettingsStore.getState().settings
      if (saved) applySettings(saved)
    }
    show(ok ? 'Settings saved.' : 'Could not save settings.', ok ? 'success' : 'error')
  }

  const addBank = async () => {
    const name = newBank.trim()
    if (!name) return
    const res = await window.api.settings.addBankAccount(name)
    if (res.ok) {
      setNewBank('')
      void reloadBankAccounts()
    } else show(errorMessage(res.error), 'error')
  }

  const deleteBank = async (id: number) => {
    const ok = await confirmDialog({
      title: 'Delete bank account?',
      message: 'This bank account will be removed. Existing payments keep their recorded bank name.',
      confirmLabel: 'Delete',
      destructive: true,
    })
    if (!ok) return
    const res = await window.api.settings.deleteBankAccount(id)
    if (res.ok) void reloadBankAccounts()
    else show(errorMessage(res.error), 'error')
  }

  const uploadTemplate = async () => {
    const res = await window.api.settings.pickAndUploadTemplate()
    if (!res.ok) {
      show(errorMessage(res.error), 'error')
    } else if (res.data.uploaded) {
      show('Template uploaded.', 'success')
      void load()
    }
  }

  const restore = async () => {
    const res = await window.api.settings.pickAndRestore()
    if (!res.ok) {
      show(errorMessage(res.error), 'error')
    } else if (res.data.restored) {
      show(`Restored ${res.data.rowsImported} records.`, 'success')
      void load()
    }
  }

  const clearAllData = async () => {
    const ok = await confirmDialog({
      title: 'Clear ALL data?',
      message:
        'This permanently removes every firm, matter, memo, and payment. ' +
        'You will first be asked where to save a backup — the data is only cleared ' +
        'after that backup is saved. This cannot be undone (except by restoring the backup).',
      confirmLabel: 'Back Up & Clear',
      destructive: true,
    })
    if (!ok) return
    const res = await window.api.settings.clearAllData()
    if (!res.ok) {
      show(errorMessage(res.error), 'error')
    } else if (res.data.cleared) {
      show('All data cleared. Backup saved.', 'success')
      void load()
    } else {
      show('Cancelled — nothing was cleared (no backup saved).', 'info')
    }
  }

  // Save bar, shown at the foot of every tab that has editable settings.
  const saveBar = (
    <div className="sticky bottom-0 -mx-1 flex items-center justify-end gap-3 border-t border-gray-200 bg-gray-50 px-1 py-3">
      {dirty && <span className="text-sm text-gray-500">You have unsaved changes.</span>}
      <Button onClick={saveDefaults} disabled={!dirty}>Save Settings</Button>
    </div>
  )

  const numberField = (label: string, key: 'defaultFeesPerAppearance' | 'defaultFeesPerConference' | 'defaultFeesMiscDrafting' | 'defaultTdsRate' | 'overdueDays', extra?: { max?: number }) => (
    <div>
      <Label>{label}</Label>
      <Input
        type="number"
        min={0}
        {...(extra?.max !== undefined ? { max: extra.max } : {})}
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: n(e.target.value) })}
      />
    </div>
  )

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h2 className="text-[1.75rem] font-normal leading-tight">Settings</h2>

      <div className="flex gap-5 border-b border-gray-200">
        {SETTINGS_TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              '-mb-px border-b-2 px-1 pb-1.5 text-sm transition-colors',
              tab === t.id
                ? 'border-blue-600 font-semibold text-gray-900'
                : 'border-transparent text-gray-500 hover:text-gray-900',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'defaults' && (
        <div className="space-y-4">
          {/* 1. Default fees */}
          <Card className="space-y-3 p-4">
            <h3 className="text-lg font-medium">Default Fees</h3>
            <div className="grid grid-cols-3 gap-4">
              {numberField('Fees / Appearance', 'defaultFeesPerAppearance')}
              {numberField('Fees / Conference', 'defaultFeesPerConference')}
              {numberField('Misc / Draft', 'defaultFeesMiscDrafting')}
            </div>
          </Card>

          {/* 2. TDS, payment prefill, bank accounts */}
          <Card className="space-y-4 p-4">
            <h3 className="text-lg font-medium">Payments</h3>
            <div className="grid grid-cols-2 gap-4">
              {numberField('Default TDS Rate (%)', 'defaultTdsRate', { max: 100 })}
              <div>
                <Label>Prefill Amount Received</Label>
                <Select
                  className="w-full"
                  value={form.defaultPaymentAmount}
                  onChange={(e) => setForm({ ...form, defaultPaymentAmount: e.target.value as DefaultPaymentAmount })}
                >
                  <option value="zero">0 (leave it blank)</option>
                  <option value="full">Full memo amount</option>
                  <option value="netOfTds">Memo amount less TDS</option>
                </Select>
              </div>
            </div>
            <p className="text-xs text-gray-400">
              Applies to every new payment (Memos, “+ Payment” and “Mark paid”): the Amount Received box
              starts with the amount still due on the memo. “Less TDS” uses the Default TDS Rate, worked
              out like the Net of TDS column. “Full” adds no TDS on top.
            </p>
            <div className="border-t border-gray-200 pt-3">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-gray-500">Bank Accounts</p>
              <div className="mb-3 flex flex-wrap gap-2">
                {bankAccounts.map((b) => (
                  <span key={b.id} className="flex items-center gap-1 rounded-sm border border-gray-300 px-2 py-1 text-sm">
                    {b.name}
                    <button className="text-gray-400 hover:text-red-700" aria-label={`Delete ${b.name}`} onClick={() => deleteBank(b.id)}>×</button>
                  </span>
                ))}
                {bankAccounts.length === 0 && <span className="text-sm text-gray-400">None yet.</span>}
              </div>
              <div className="flex items-center gap-2">
                <Input placeholder="New bank account" value={newBank} onChange={(e) => setNewBank(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void addBank()} />
                <Button variant="secondary" className="shrink-0" onClick={addBank}>Add</Button>
              </div>
            </div>
          </Card>

          {/* 3. Cause title and additional details */}
          <Card className="space-y-3 p-4">
            <h3 className="text-lg font-medium">Memo Text Defaults</h3>
            <div>
              <Label>Default Cause Title</Label>
              <Textarea rows={2} value={form.defaultCourtName} onChange={(e) => setForm({ ...form, defaultCourtName: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Default Additional Details (Left)</Label>
                <Textarea rows={2} value={form.defaultAdditionalDetailsLeft} onChange={(e) => setForm({ ...form, defaultAdditionalDetailsLeft: e.target.value })} />
              </div>
              <div>
                <Label>Default Additional Details (Right)</Label>
                <Textarea rows={2} value={form.defaultAdditionalDetailsRight} onChange={(e) => setForm({ ...form, defaultAdditionalDetailsRight: e.target.value })} />
              </div>
            </div>
            <p className="text-xs text-gray-400">Pre-filled into new memos (the matter&apos;s own details win if it has them).</p>
          </Card>

          {/* 4. Overdue, start page, money display, zoom */}
          <Card className="space-y-4 p-4">
            <h3 className="text-lg font-medium">Display</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                {numberField('Overdue Days (0 = off)', 'overdueDays')}
                <p className="mt-1 text-xs text-gray-400">
                  An unpaid memo older than this many days from its date is flagged “Overdue”.
                </p>
              </div>
              <div>
                <Label>Default Start Page</Label>
                <Select
                  className="w-full"
                  value={form.defaultTab}
                  onChange={(e) => setForm({ ...form, defaultTab: e.target.value })}
                >
                  <option value="memos">Memos</option>
                  <option value="dashboard">Dashboard</option>
                  <option value="firms">Firms</option>
                  <option value="feebook">Feebook</option>
                  <option value="outstanding">Outstanding</option>
                  <option value="settings">Settings</option>
                </Select>
                <p className="mt-1 text-xs text-gray-400">The tab shown when you open the app.</p>
              </div>
            </div>
            <div>
              <Label>Money Display</Label>
              <div className="flex flex-wrap items-end gap-3">
                <Select
                  className="w-48"
                  value={form.moneyUnit}
                  onChange={(e) => setForm({ ...form, moneyUnit: e.target.value as 'full' | 'truncated' })}
                >
                  <option value="full">Full</option>
                  <option value="truncated">Truncated (k, lac, cr)</option>
                </Select>
                {form.moneyUnit === 'truncated' && (
                  <>
                    <div className="w-28">
                      <Label>Thousands</Label>
                      <Input value={form.moneySuffixThousands} maxLength={12} onChange={(e) => setForm({ ...form, moneySuffixThousands: e.target.value })} />
                    </div>
                    <div className="w-28">
                      <Label>Lacs</Label>
                      <Input value={form.moneySuffixLac} maxLength={12} onChange={(e) => setForm({ ...form, moneySuffixLac: e.target.value })} />
                    </div>
                    <div className="w-28">
                      <Label>Crores</Label>
                      <Input value={form.moneySuffixCrore} maxLength={12} onChange={(e) => setForm({ ...form, moneySuffixCrore: e.target.value })} />
                    </div>
                  </>
                )}
              </div>
              <p className="mt-1 text-xs text-gray-400">
                Full shows the complete number. Truncated auto-scales by size (thousands below 1 lac, lacs
                below 1 crore, crores above) with up to 2 decimals; amounts under 10 show as they are. A
                word suffix gets a space (6.7 lac). Hover a shortened figure to see the full amount.
              </p>
            </div>
            <div className="w-48">
              <Label>Zoom</Label>
              <Select
                className="w-full"
                value={String(form.zoomFactor)}
                onChange={(e) => setForm({ ...form, zoomFactor: Number(e.target.value) })}
              >
                {[0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75].map((z) => (
                  <option key={z} value={z}>{Math.round(z * 100)}%</option>
                ))}
              </Select>
              <p className="mt-1 text-xs text-gray-400">Also ⌘ + / ⌘ − / ⌘ 0.</p>
            </div>
            <div className="space-y-2 border-t border-gray-200 pt-3">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.defaultLinesEnabled} onChange={(e) => setForm({ ...form, defaultLinesEnabled: e.target.checked })} />
                Tick Appearances, Conferences and Misc / Drafting by default on a new memo
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.showStatusDots} onChange={(e) => setForm({ ...form, showStatusDots: e.target.checked })} />
                Show coloured status dots (paid / unpaid / overdue / written off)
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.hidePaymentWhenPaid} onChange={(e) => setForm({ ...form, hidePaymentWhenPaid: e.target.checked })} />
                Hide the Payment button on fully paid memos
              </label>
              <p className="text-xs text-gray-400">
                When the first box is unticked, a new memo opens with those three lines switched off; tick
                a line on the memo to use it. Memos you edit or duplicate keep their own ticks.
              </p>
            </div>
          </Card>

          {/* 5. Word template */}
          <Card className="space-y-3 p-4">
            <h3 className="text-lg font-medium">Word Template</h3>
            <p className="text-sm text-gray-600">
              Current template: {settings?.wordTemplatePath ? 'uploaded' : 'none'}
            </p>
            <div>
              <Button variant="secondary" onClick={uploadTemplate}>Import Word Template</Button>
            </div>
          </Card>

          {saveBar}
        </div>
      )}

      {tab === 'statistics' && (
        <div className="space-y-4">
          <Card className="space-y-3 p-4">
            <h3 className="text-lg font-medium">Start Years</h3>
            <div className="grid grid-cols-3 gap-4">
              {([
                ['initialFinancialYear', 'Statistics Start Year'],
                ['memosStartYear', 'Memos Start Year'],
                ['feebookStartYear', 'Feebook Start Year'],
              ] as const).map(([key, label]) => (
                <div key={key}>
                  <Label>{label}</Label>
                  <Input
                    value={form[key]}
                    placeholder="2026-27"
                    onChange={(e) => setForm({ ...form, [key]: e.target.value.trim() })}
                  />
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-400">
              The first year shown in each area (e.g. 2026-27). Earlier years are hidden from that
              area&apos;s year filter, but the data stays stored.
            </p>
          </Card>

          <EditStatisticsCard />

          {saveBar}
        </div>
      )}

      {tab === 'backup' && (
        <div className="space-y-4">
          <BackupSettings />

          <Card className="space-y-3 p-4">
            <h3 className="text-lg font-medium">Import &amp; Restore</h3>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => setShowImport(true)}>Import Memos from Spreadsheet</Button>
              <Button variant="secondary" onClick={restore}>Restore from Excel (replaces all)</Button>
            </div>
            <p className="text-xs text-gray-400">
              Import adds memos from your own spreadsheet (creating firms &amp; matters by name) without
              deleting anything. Restore replaces ALL data from a Fee Register backup.
            </p>
          </Card>

          <Card className="space-y-3 border-2 border-red-200 bg-red-50/50 p-4">
            <h3 className="text-lg font-medium text-red-800">Clear All Data</h3>
            <p className="text-sm text-gray-600">
              Permanently remove every firm, matter, memo, and payment. You will first be asked where
              to save a backup — nothing is cleared until that backup is saved. This cannot be undone
              except by restoring the backup.
            </p>
            <div>
              <Button variant="danger" onClick={clearAllData}>Clear All Data</Button>
            </div>
          </Card>
        </div>
      )}

      {tab === 'other' && (
        <div className="space-y-4">
          <Card className="space-y-3 p-4">
            <h3 className="text-lg font-medium">Undo / Redo History</h3>
            <p className="text-sm text-gray-600">
              The actions currently available to undo or redo (most recent first). Up to 20 steps are
              kept. Use ⌘Z / ⌘⇧Z (or the arrows in the top bar) to step through them.
            </p>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {([
                ['Undo', undoStack],
                ['Redo', redoStack],
              ] as const).map(([title, stack]) => (
                <div key={title}>
                  <p className="mb-1 text-sm font-medium text-gray-700">
                    {title} ({stack.length})
                  </p>
                  {stack.length === 0 ? (
                    <p className="text-sm text-gray-400">Nothing to {title.toLowerCase()}.</p>
                  ) : (
                    <ol className="space-y-1 text-sm">
                      {stack.map((label, i) => (
                        <li key={i} className="flex items-center gap-2">
                          <span className="w-5 text-right text-xs text-gray-400">{i + 1}.</span>
                          <span className={i === 0 ? 'font-medium' : ''}>{label}</span>
                          {i === 0 && <span className="text-xs text-gray-400">(next)</span>}
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              ))}
            </div>
          </Card>

          <ShortcutsCard />

          <DiagnosticsCard />

          <Card className="space-y-1 p-4">
            <h3 className="text-lg font-medium">About</h3>
            <p className="text-sm text-gray-600">
              Fee Register{appVersion ? ` — version ${appVersion}` : ''}
            </p>
            <p className="text-sm text-gray-600">Created by Ziyad Madon.</p>
          </Card>

          {saveBar}
        </div>
      )}

      {showImport && <ImportMemosDialog onClose={() => setShowImport(false)} />}
    </div>
  )
}
