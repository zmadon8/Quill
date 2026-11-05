import { useEffect, useState, useCallback } from 'react'
import { useNavStore } from '@/stores/useNavStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { Select } from '@/components/ui/Select'
import { Card } from '@/components/ui/Card'
import { NewMatterDialog } from '@/components/matters/NewMatterDialog'
import { LedgerExportDialog } from '@/components/firms/LedgerExportDialog'
import { useOutstandingStore } from '@/stores/useOutstandingStore'
import { useNavStore as useNav } from '@/stores/useNavStore'
import { StatusDot } from '@/components/ui/StatusDot'
import type { FirmDetail, MatterFilter } from '@/types/ipc'

export function FirmDetailPage({ firmId }: { firmId: number }) {
  const requestViewFirm = useOutstandingStore((s) => s.requestViewFirm)
  const setTab = useNav((s) => s.setTab)
  const [detail, setDetail] = useState<FirmDetail | null>(null)
  const [filter, setFilter] = useState<MatterFilter>('active')
  const [showLedger, setShowLedger] = useState(false)
  const [name, setName] = useState('')
  const [notes, setNotes] = useState('')
  const [newPartner, setNewPartner] = useState('')
  const [showNewMatter, setShowNewMatter] = useState(false)
  const [editingPartnerId, setEditingPartnerId] = useState<number | null>(null)
  const [editingPartnerName, setEditingPartnerName] = useState('')
  const push = useNavStore((s) => s.push)
  const show = useToastStore((s) => s.show)

  const load = useCallback(async () => {
    const res = await window.api.firms.get(firmId)
    if (res.ok) {
      setDetail(res.data)
      setName(res.data.name)
      setNotes(res.data.notes ?? '')
    } else {
      show(errorMessage(res.error), 'error')
    }
  }, [firmId])

  const refreshTick = useNavStore((s) => s.refreshTick)
  useEffect(() => {
    void load()
  }, [load, refreshTick])

  if (!detail) return <p className="text-sm text-gray-500">Loading…</p>

  const matters = detail.matters.filter((m) =>
    filter === 'all' ? true : filter === 'active' ? !m.isArchived : m.isArchived,
  )
  // group by partner
  const partnerName = (id: number) => detail.partners.find((p) => p.id === id)?.name ?? '(unknown)'
  const byPartner = new Map<number, typeof matters>()
  for (const m of matters) {
    const arr = byPartner.get(m.partnerId) ?? []
    arr.push(m)
    byPartner.set(m.partnerId, arr)
  }
  const partnerIds = [...byPartner.keys()].sort((a, b) =>
    partnerName(a).toLowerCase().localeCompare(partnerName(b).toLowerCase()),
  )

  const rename = async () => {
    const res = await window.api.firms.update(firmId, { name: name.trim() })
    if (res.ok) show('Firm updated.', 'success')
    else show(errorMessage(res.error), 'error')
  }

  const saveNotes = async () => {
    const res = await window.api.firms.update(firmId, { notes })
    if (res.ok) show('Notes saved.', 'success')
    else show(errorMessage(res.error), 'error')
  }

  const addPartner = async () => {
    const n = newPartner.trim()
    if (!n) return
    const res = await window.api.firms.addPartner(firmId, n)
    if (res.ok) {
      setNewPartner('')
      void load()
    } else show(errorMessage(res.error), 'error')
  }

  const removePartner = async (pid: number) => {
    const res = await window.api.firms.removePartner(firmId, pid)
    if (res.ok) void load()
    else show(errorMessage(res.error), 'error')
  }

  const startEditPartner = (pid: number, current: string) => {
    setEditingPartnerId(pid)
    setEditingPartnerName(current)
  }

  const saveEditPartner = async () => {
    if (editingPartnerId === null) return
    const n = editingPartnerName.trim()
    if (!n) return
    const res = await window.api.firms.updatePartner(firmId, editingPartnerId, n)
    if (res.ok) {
      setEditingPartnerId(null)
      setEditingPartnerName('')
      show('Group updated.', 'success')
      void load()
    } else show(errorMessage(res.error), 'error')
  }

  const toggleArchive = async (matterId: number, archived: boolean) => {
    const res = archived
      ? await window.api.matters.unarchive(matterId)
      : await window.api.matters.archive(matterId)
    if (res.ok) void load()
    else show(errorMessage(res.error), 'error')
  }

  const viewOutstanding = () => {
    requestViewFirm(firmId)
    setTab('outstanding')
  }

  const exportStatement = async () => {
    const res = await window.api.memos.exportStatementExcel({ firmId })
    if (!res.ok) show(errorMessage(res.error), 'error')
    else if (res.data.saved) show('Statement exported.', 'success')
  }

  const toggleFirmArchive = async () => {
    if (!detail) return
    const next = detail.status === 'archived' ? 'active' : 'archived'
    const res = await window.api.firms.setStatus(firmId, next)
    if (res.ok) {
      show(next === 'archived' ? 'Firm archived.' : 'Firm unarchived.', 'success')
      void load()
    } else show(errorMessage(res.error), 'error')
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-[1.75rem] font-normal leading-tight">
          {detail.name}
          {detail.status === 'archived' && (
            <span className="ml-2 text-sm text-gray-400">(archived)</span>
          )}
        </h2>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={exportStatement}>Statement (Excel)</Button>
          <Button variant="secondary" onClick={() => setShowLedger(true)}>Ledger (Excel)</Button>
          <Button variant="secondary" onClick={viewOutstanding}>
            View Outstanding for this Firm
          </Button>
          <Button variant="ghost" onClick={toggleFirmArchive}>
            {detail.status === 'archived' ? 'Unarchive Firm' : 'Archive Firm'}
          </Button>
        </div>
      </div>

      <Card className="grid grid-cols-1 gap-6 p-4 md:grid-cols-2">
        {/* Left half: firm name + notes */}
        <div className="space-y-3">
          <div>
            <p className="mb-1 text-sm font-medium text-gray-700">Firm Name</p>
            <div className="flex items-center gap-2">
              <Input value={name} onChange={(e) => setName(e.target.value)} />
              <Button onClick={rename}>Save</Button>
            </div>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium text-gray-700">Notes</p>
            <Textarea rows={1} className="resize-y" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <div className="mt-1">
              <Button size="sm" variant="secondary" onClick={saveNotes}>Save Notes</Button>
            </div>
          </div>
        </div>

        {/* Right half: add partner + partner list */}
        <div className="space-y-3 md:border-l md:pl-6">
          <p className="mb-1 text-sm font-medium text-gray-700">Add Group</p>
          <div className="flex items-center gap-2">
            <Input
              placeholder="New group"
              value={newPartner}
              onChange={(e) => setNewPartner(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void addPartner()}
            />
            <Button variant="secondary" onClick={addPartner}>
              Add
            </Button>
          </div>
          <p className="mb-1 text-sm font-medium text-gray-700">Groups</p>
          <div className="flex flex-wrap gap-2">
            {detail.partners.length === 0 && (
              <span className="text-sm text-gray-400">No groups yet.</span>
            )}
            {detail.partners.map((p) =>
              editingPartnerId === p.id ? (
                <span key={p.id} className="flex items-center gap-1 rounded bg-gray-100 px-2 py-1 text-sm">
                  <Input
                    className="h-7 w-40 py-0 text-sm"
                    value={editingPartnerName}
                    onChange={(e) => setEditingPartnerName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void saveEditPartner()
                      if (e.key === 'Escape') setEditingPartnerId(null)
                    }}
                    autoFocus
                  />
                  <button className="text-blue-600 hover:underline" onClick={() => void saveEditPartner()}>
                    Save
                  </button>
                  <button className="text-gray-400 hover:text-gray-700" onClick={() => setEditingPartnerId(null)}>
                    Cancel
                  </button>
                </span>
              ) : (
                <span key={p.id} className="flex items-center gap-1 rounded bg-gray-100 px-2 py-1 text-sm">
                  {p.name}
                  <button
                    className="text-gray-400 hover:text-blue-600"
                    title="Edit name"
                    onClick={() => startEditPartner(p.id, p.name)}
                  >
                    ✎
                  </button>
                  <button
                    className="text-gray-400 hover:text-red-600"
                    title="Remove"
                    onClick={() => removePartner(p.id)}
                  >
                    ×
                  </button>
                </span>
              ),
            )}
          </div>
        </div>
      </Card>

      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Matters</h3>
        <div className="flex items-center gap-2">
          <Select value={filter} onChange={(e) => setFilter(e.target.value as MatterFilter)}>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
            <option value="all">All</option>
          </Select>
          <Button size="sm" onClick={() => setShowNewMatter(true)}>
            + New Matter
          </Button>
        </div>
      </div>

      {partnerIds.length === 0 ? (
        <Card className="p-6 text-center text-sm text-gray-500">
          No matters yet — add one with “+ New Matter” to start billing this firm.
        </Card>
      ) : (
        partnerIds.map((pid) => (
          <Card key={pid} className="p-3">
            <p className="mb-2 text-sm font-semibold text-gray-700">{partnerName(pid)}</p>
            <div className="divide-y">
              {byPartner.get(pid)!.map((m) => (
                <div key={m.id} className="flex items-center justify-between py-2">
                  <div className="flex items-center gap-2">
                    {/* Rolled-up status dot(s): primary status, plus a grey dot
                        when any memo in the matter is written off. */}
                    <span className="flex items-center gap-1">
                      {m.memoStatus && <StatusDot status={m.memoStatus} />}
                      {m.hasWrittenOff && <StatusDot status="Written Off" />}
                    </span>
                    <button
                      className="text-left text-blue-700 hover:underline"
                      onClick={() => push({ kind: 'matterDetail', matterId: m.id, title: m.name })}
                    >
                      {m.name}
                      {m.isArchived && <span className="ml-2 text-xs text-gray-400">(archived)</span>}
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    {!m.isArchived && (
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={() =>
                          push({ kind: 'memoForm', matterId: m.id, title: `New Memo — ${m.name}` })
                        }
                      >
                        + Memo
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => toggleArchive(m.id, m.isArchived)}>
                      {m.isArchived ? 'Unarchive' : 'Archive'}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ))
      )}

      {showNewMatter && (
        <NewMatterDialog
          firmId={firmId}
          onClose={() => setShowNewMatter(false)}
          onCreated={() => {
            setShowNewMatter(false)
            void load()
          }}
        />
      )}
      {showLedger && (
        <LedgerExportDialog
          firmId={firmId}
          firmName={detail.name}
          partners={detail.partners}
          matters={detail.matters}
          onClose={() => setShowLedger(false)}
        />
      )}
    </div>
  )
}
