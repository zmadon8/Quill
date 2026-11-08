import { useEffect, useState, useCallback } from 'react'
import { useNavStore } from '@/stores/useNavStore'
import { useUiPrefsStore } from '@/stores/useUiPrefsStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { confirmDialog } from '@/stores/useConfirmStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Card } from '@/components/ui/Card'
import { Select } from '@/components/ui/Select'
import { Textarea } from '@/components/ui/Textarea'
import { MatterFieldsForm, emptyMatterFields, matterFieldsFrom, type MatterFields } from './MatterFieldsForm'
import { PaymentModal } from '@/components/memos/PaymentModal'
import { StatusLabel, memoDisplayStatus } from '@/components/ui/StatusDot'
import { displayDate } from '@/lib/formatDate'
import type { MatterDetail, MemoListItem, FirmSummary, PartnerDTO } from '@/types/ipc'
import { Money } from '@/components/ui/Money'
import { DataTable, ColumnsMenu, useTablePrefs, type DTColumn } from '@/components/ui/DataTable'

export function MatterDetailPage({ matterId }: { matterId: number }) {
  const [matter, setMatter] = useState<MatterDetail | null>(null)
  const [memos, setMemos] = useState<MemoListItem[]>([])
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editFields, setEditFields] = useState<MatterFields>(emptyMatterFields())
  const [editFirmId, setEditFirmId] = useState<number | ''>('')
  const [editPartnerId, setEditPartnerId] = useState<number | ''>('')
  const [firms, setFirms] = useState<FirmSummary[]>([])
  const [partners, setPartners] = useState<PartnerDTO[]>([])
  const [saving, setSaving] = useState(false)
  const [payFor, setPayFor] = useState<number | null>(null)
  const [notes, setNotes] = useState('')
  const push = useNavStore((s) => s.push)
  const show = useToastStore((s) => s.show)
  const hidePaid = useUiPrefsStore((s) => s.hidePaymentWhenPaid)

  const load = useCallback(async () => {
    const m = await window.api.matters.get(matterId)
    if (m.ok) {
      setMatter(m.data)
      setNotes(m.data.notes ?? '')
    }
    const list = await window.api.memos.listForMatter(matterId)
    if (list.ok) setMemos(list.data)
  }, [matterId])

  const saveNotes = async () => {
    if (!matter) return
    // updateMatter rewrites every matter-level field, so send the matter's
    // current values with only `notes` changed — otherwise the other fields
    // (cause title, parties, addressee, etc.) would be cleared.
    const res = await window.api.matters.update(matterId, {
      name: matter.name,
      firmId: matter.firmId,
      partnerId: matter.partnerId,
      ...matterFieldsFrom(matter),
      notes,
    })
    if (res.ok) {
      setMatter(res.data)
      show('Notes saved.', 'success')
    } else show(errorMessage(res.error), 'error')
  }

  const refreshTick = useNavStore((s) => s.refreshTick)
  useEffect(() => {
    void load()
  }, [load, refreshTick])

  const startEdit = async () => {
    if (!matter) return
    setEditName(matter.name)
    setEditFields(matterFieldsFrom(matter))
    setEditFirmId(matter.firmId)
    setEditPartnerId(matter.partnerId)
    setEditing(true)
    // Load all firms for the Firm dropdown and the current firm's partners.
    const [fs, fd] = await Promise.all([
      window.api.firms.list('all'),
      window.api.firms.get(matter.firmId),
    ])
    if (fs.ok) setFirms(fs.data)
    if (fd.ok) setPartners(fd.data.partners)
  }

  // When the chosen firm changes in the editor, load that firm's partners and
  // default the partner to the first available (unless it's still the original).
  const onFirmChange = async (firmId: number) => {
    setEditFirmId(firmId)
    const fd = await window.api.firms.get(firmId)
    if (fd.ok) {
      setPartners(fd.data.partners)
      // Keep the current partner if it belongs to the new firm; else pick first.
      const stillValid = fd.data.partners.some((p) => p.id === editPartnerId)
      if (!stillValid) setEditPartnerId(fd.data.partners[0]?.id ?? '')
    }
  }

  const saveEdit = async () => {
    if (!editName.trim()) {
      show('Matter name is required.', 'error')
      return
    }
    if (editFirmId === '' || editPartnerId === '') {
      show('Choose a firm and a group for the matter.', 'error')
      return
    }
    // Moving the matter to a different firm also moves all its memos.
    if (matter && editFirmId !== matter.firmId) {
      const ok = await confirmDialog({
        title: 'Move matter to another firm?',
        message:
          `This will move "${matter.name}" and all of its memos to the selected firm and partner. ` +
          `Statistics, Feebook, and Outstanding will reflect the new firm.`,
        confirmLabel: 'Move Matter',
      })
      if (!ok) return
    }
    setSaving(true)
    try {
      const res = await window.api.matters.update(matterId, {
        name: editName.trim(),
        firmId: editFirmId,
        partnerId: editPartnerId,
        ...editFields,
      })
      if (res.ok) {
        setMatter(res.data)
        setEditing(false)
        show('Matter updated.', 'success')
        void load() // refresh memo list (firm/partner may have changed)
      } else {
        show(errorMessage(res.error), 'error')
      }
    } finally {
      setSaving(false)
    }
  }

  const toggleWrittenOff = async (id: number, current: boolean) => {
    // Perform immediately, then offer Undo via a short-lived toast (no confirm dialog).
    const res = await window.api.memos.setWrittenOff(id, !current)
    if (!res.ok) {
      show(errorMessage(res.error), 'error')
      return
    }
    void load()
    show(current ? 'Memo restored.' : 'Memo written off.', {
      variant: 'success',
      action: {
        label: 'Undo',
        run: async () => {
          const undo = await window.api.memos.setWrittenOff(id, current)
          if (undo.ok) void load()
          else show(errorMessage(undo.error), 'error')
        },
      },
    })
  }

  const newMemo = () => {
    if (matter?.isArchived) {
      show('Memos can only be created for active matters.', 'error')
      return
    }
    push({ kind: 'memoForm', matterId, title: 'New Memo' })
  }

  // Duplicate a memo: opens a new memo pre-filled from it (date and number
  // are left for the user to set).
  const duplicateMemo = (m: MemoListItem) => {
    if (matter?.isArchived) {
      show('Memos can only be created for active matters.', 'error')
      return
    }
    push({ kind: 'memoForm', basedOnId: m.id, title: 'New Memo' })
  }

  const exportStatement = async () => {
    const res = await window.api.memos.exportStatementExcel({ matterId })
    if (!res.ok) show(errorMessage(res.error), 'error')
    else if (res.data.saved) show('Statement exported.', 'success')
  }

  const sum = (f: (m: MemoListItem) => number) => memos.reduce((a, m) => a + f(m), 0)
  const memoColumns: Array<DTColumn<MemoListItem>> = [
    {
      key: 'memo', label: 'Memo No.', width: 130, hideable: false,
      cell: (m) => (
        <button
          className="text-left font-medium text-blue-700 hover:underline"
          onClick={() => push({ kind: 'memoForm', memoId: m.id, title: m.memoNumber })}
        >
          {m.memoNumber}
        </button>
      ),
      foot: () => 'Totals',
    },
    { key: 'date', label: 'Date', width: 100, cell: (m) => displayDate(m.date) },
    { key: 'apps', label: 'Apps', width: 70, align: 'right', hideable: true, cell: (m) => m.numAppearances, foot: () => sum((m) => m.numAppearances) },
    { key: 'confs', label: 'Confs', width: 70, align: 'right', hideable: true, cell: (m) => m.numConferences, foot: () => sum((m) => m.numConferences) },
    { key: 'drafts', label: 'Drafts', width: 70, align: 'right', hideable: true, cell: (m) => m.numDrafts, foot: () => sum((m) => m.numDrafts) },
    { key: 'total', label: 'Total', width: 110, align: 'right', cell: (m) => <>₹ <Money v={m.totalFees} /></>, foot: () => <>₹ <Money v={sum((m) => m.totalFees)} /></> },
    { key: 'net', label: 'Net of TDS', width: 110, align: 'right', hideable: true, cell: (m) => <>₹ <Money v={m.netOfTds} /></>, foot: () => <>₹ <Money v={sum((m) => m.netOfTds)} /></> },
    { key: 'paid', label: 'Paid', width: 110, align: 'right', hideable: true, cell: (m) => <>₹ <Money v={m.amountPaid} /></>, foot: () => <>₹ <Money v={sum((m) => m.amountPaid)} /></> },
    {
      key: 'due', label: 'Due', width: 110, align: 'right', cellClassName: 'font-bold',
      cell: (m) => <>₹ <Money v={Math.max(0, m.amountDue)} /></>,
      foot: () => <>₹ <Money v={sum((m) => Math.max(0, m.amountDue))} /></>,
    },
    { key: 'status', label: 'Status', width: 90, hideable: true, cell: (m) => <StatusLabel status={m.isDraft ? 'Draft' : memoDisplayStatus(m)} /> },
    {
      key: 'actions', label: 'Actions', width: 300, align: 'right', hideable: false,
      cell: (m) => (
        <div className="flex flex-wrap justify-end gap-1">
          {!m.isDraft && !(hidePaid && m.status === 'Paid') && (
            <Button size="sm" variant="success" onClick={() => setPayFor(m.id)}>Payment</Button>
          )}
          <Button size="sm" variant="secondary" disabled={!!matter?.isArchived} onClick={() => duplicateMemo(m)}>
            Duplicate
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={!m.writtenOff && m.status === 'Paid'}
            title={!m.writtenOff && m.status === 'Paid' ? 'A fully paid memo cannot be written off' : undefined}
            onClick={() => toggleWrittenOff(m.id, m.writtenOff)}
          >
            {m.writtenOff ? 'Restore' : 'Write Off'}
          </Button>
        </div>
      ),
    },
  ]
  const tablePrefs = useTablePrefs('matterMemos', memoColumns)

  const exportLedger = async () => {
    const res = await window.api.memos.exportLedgerExcel({ matterId })
    if (!res.ok) show(errorMessage(res.error), 'error')
    else if (res.data.saved) show('Ledger exported.', 'success')
  }

  if (!matter) return <p className="text-sm text-gray-500">Loading…</p>

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[1.75rem] font-normal leading-tight">
            {matter.name}
            {matter.isArchived && <span className="ml-2 text-sm text-gray-400">(archived)</span>}
          </h2>
          <p className="text-sm text-gray-500">
            {matter.firmName} · {matter.partnerName}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={exportStatement}>
            Statement (Excel)
          </Button>
          <Button variant="secondary" onClick={exportLedger}>
            Ledger (Excel)
          </Button>
          <Button variant="secondary" onClick={startEdit}>
            Edit Matter
          </Button>
          <Button onClick={newMemo} disabled={matter.isArchived}>
            + New Memo
          </Button>
        </div>
      </div>

      {editing && (
        <Card className="space-y-4 p-4">
          <h3 className="text-lg font-medium">Edit Matter</h3>
          <div>
            <Label>Matter Name</Label>
            <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
          </div>
          <div>
            <Label>Short Name (used in the Word export)</Label>
            <Input
              value={editFields.shortName}
              placeholder="Leave blank to use the full matter name"
              onChange={(e) => setEditFields({ ...editFields, shortName: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Firm</Label>
              <Select
                className="w-full"
                value={editFirmId === '' ? '' : editFirmId}
                onChange={(e) => void onFirmChange(Number(e.target.value))}
              >
                {firms.map((f) => (
                  <option key={f.id} value={f.id}>{f.name}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Group</Label>
              <Select
                className="w-full"
                value={editPartnerId === '' ? '' : editPartnerId}
                onChange={(e) => setEditPartnerId(e.target.value ? Number(e.target.value) : '')}
              >
                {partners.length === 0 && <option value="">(no groups in firm)</option>}
                {partners.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </Select>
            </div>
          </div>
          <p className="-mt-2 text-xs text-gray-400">
            Changing the firm moves this matter and all its memos to that firm.
          </p>
          <div>
            <p className="mb-2 text-sm font-medium text-gray-700">
              Common memo details (shared by every memo in this matter)
            </p>
            <MatterFieldsForm value={editFields} onChange={setEditFields} />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setEditing(false)} disabled={saving}>
              Cancel
            </Button>
            <Button onClick={saveEdit} disabled={saving}>
              Save Changes
            </Button>
          </div>
        </Card>
      )}

      {/* Notes — always visible and editable on the matter page. */}
      <Card className="space-y-2 p-4">
        <Label>Notes</Label>
        <Textarea
          rows={1}
          className="resize-y"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        <div>
          <Button size="sm" variant="secondary" onClick={saveNotes}>Save Notes</Button>
        </div>
      </Card>

      {memos.length === 0 ? (
        <p className="text-sm text-gray-500">No memos in this matter yet.</p>
      ) : (
        <Card className="overflow-hidden">
          <div className="flex justify-end border-b p-2">
            <ColumnsMenu prefs={tablePrefs} columns={memoColumns} />
          </div>
          <DataTable prefs={tablePrefs} columns={memoColumns} rows={memos} rowKey={(m) => m.id} />
        </Card>
      )}

      {payFor !== null && (
        <PaymentModal
          memoId={payFor}
          onClose={() => {
            setPayFor(null)
            void load()
          }}
        />
      )}
    </div>
  )
}
