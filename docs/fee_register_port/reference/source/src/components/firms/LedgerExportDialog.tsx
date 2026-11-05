import { useMemo, useState } from 'react'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { Label } from '@/components/ui/Label'
import type { MatterDTO, PartnerDTO } from '@/types/ipc'

type Scope = 'firm' | 'partner' | 'matters'
type StatusFilter = 'active' | 'archived' | 'both'

/**
 * Export a running-balance ledger (Excel) for a whole firm, for one
 * group, or for specific matters of the firm.
 */
export function LedgerExportDialog({
  firmId,
  firmName,
  partners,
  matters,
  onClose,
}: {
  firmId: number
  firmName: string
  partners: PartnerDTO[]
  matters: MatterDTO[]
  onClose: () => void
}) {
  const show = useToastStore((s) => s.show)
  const [scope, setScope] = useState<Scope>('firm')
  const [partnerId, setPartnerId] = useState<number | ''>(partners[0]?.id ?? '')
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<StatusFilter>('active')

  const sorted = useMemo(
    () =>
      matters
        .filter((m) => status === 'both' || (status === 'archived') === m.isArchived)
        .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase())),
    [matters, status],
  )
  const toggle = (id: number) =>
    setPicked((cur) => {
      const n = new Set(cur)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })

  // Only matters currently listed (i.e. matching the status filter) are exported.
  const chosen = sorted.filter((m) => picked.has(m.id)).map((m) => m.id)
  const canExport =
    scope === 'firm' || (scope === 'partner' && partnerId !== '') || (scope === 'matters' && chosen.length > 0)

  const run = async () => {
    setBusy(true)
    try {
      const res = await window.api.memos.exportLedgerExcel({
        firmId,
        ...(scope === 'partner' && partnerId !== '' ? { partnerId } : {}),
        ...(scope === 'matters' ? { matterIds: chosen } : {}),
      })
      if (!res.ok) show(errorMessage(res.error), 'error')
      else if (res.data.saved) {
        show('Ledger exported.', 'success')
        onClose()
      }
    } finally {
      setBusy(false)
    }
  }

  const radio = (value: Scope, label: string) => (
    <label className="flex items-center gap-2 py-1 text-sm">
      <input type="radio" name="ledger-scope" checked={scope === value} onChange={() => setScope(value)} />
      {label}
    </label>
  )

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-lg space-y-3 overflow-y-auto rounded-sm border border-gray-900 bg-gray-50 p-5 shadow-[0_6px_24px_rgba(28,27,25,0.18)]">
        <h3 className="text-xl font-medium">Export Ledger — {firmName}</h3>
        <p className="text-sm text-gray-600">
          One running-balance ledger in date order: memos as debits, payments (net) and TDS as credits.
        </p>

        <div>
          {radio('firm', 'Entire firm')}
          {radio('partner', 'One group')}
          {scope === 'partner' && (
            <div className="mb-2 ml-6">
              <Label>Group</Label>
              <Select
                className="w-full"
                value={partnerId}
                onChange={(e) => setPartnerId(e.target.value ? Number(e.target.value) : '')}
              >
                {partners.length === 0 && <option value="">(none)</option>}
                {partners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            </div>
          )}
          {radio('matters', 'Specific matters')}
          {scope === 'matters' && (
            <div className="ml-6">
              <div className="mb-2">
                <Label>Show matters</Label>
                <Select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
                  <option value="active">Active</option>
                  <option value="archived">Archived</option>
                  <option value="both">Both</option>
                </Select>
              </div>
              <div className="mb-1 flex gap-3 text-xs">
                <button className="text-blue-700 hover:underline" onClick={() => setPicked(new Set(sorted.map((m) => m.id)))}>
                  Select all
                </button>
                <button className="text-blue-700 hover:underline" onClick={() => setPicked(new Set())}>
                  Select none
                </button>
                <span className="text-gray-500">{chosen.length} selected</span>
              </div>
              <div className="max-h-60 overflow-y-auto border border-gray-300 bg-white p-2">
                {sorted.length === 0 && <p className="text-sm text-gray-500">No matters match this filter.</p>}
                {sorted.map((m) => (
                  <label key={m.id} className="flex cursor-pointer items-center gap-2 py-0.5 text-sm">
                    <input type="checkbox" checked={picked.has(m.id)} onChange={() => toggle(m.id)} />
                    <span className="truncate">{m.name}</span>
                    {m.isArchived && <span className="text-xs text-gray-400">(archived)</span>}
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={run} disabled={!canExport || busy}>Export</Button>
        </div>
      </div>
    </div>
  )
}
