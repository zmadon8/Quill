import { useEffect, useMemo, useState } from 'react'
import { useFirmStore } from '@/stores/useFirmStore'
import { useNavStore } from '@/stores/useNavStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { Card } from '@/components/ui/Card'
import { NewMatterDialog } from '@/components/matters/NewMatterDialog'
import { NewMemoDialog } from '@/components/memos/NewMemoDialog'
import type { FirmFilter } from '@/types/ipc'

export function FirmsPage() {
  const { firms, filter, loading, setFilter, load } = useFirmStore()
  const push = useNavStore((s) => s.push)
  const show = useToastStore((s) => s.show)
  const [newName, setNewName] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [search, setSearch] = useState('')
  const [newMatterFirmId, setNewMatterFirmId] = useState<number | null>(null)
  const [newMemoFirmId, setNewMemoFirmId] = useState<number | null>(null)

  const refreshTick = useNavStore((s) => s.refreshTick)
  useEffect(() => {
    void load()
  }, [refreshTick])

  const createFirm = async () => {
    const name = newName.trim()
    if (!name) return
    const res = await window.api.firms.create(name)
    if (res.ok) {
      setNewName('')
      setShowAdd(false)
      show('Firm created.', 'success')
      void load()
    } else {
      show(errorMessage(res.error), 'error')
    }
  }

  // Live filter on the name as you type.
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? firms.filter((f) => f.name.toLowerCase().includes(q)) : firms
  }, [firms, search])

  const toggleStatus = async (id: number, current: 'active' | 'archived') => {
    const next = current === 'active' ? 'archived' : 'active'
    const res = await window.api.firms.setStatus(id, next)
    if (res.ok) {
      show(next === 'archived' ? 'Firm archived.' : 'Firm set to active.', 'success')
      void load()
    } else {
      show(errorMessage(res.error), 'error')
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-[1.75rem] font-normal leading-tight">Firms</h2>
        <Select value={filter} onChange={(e) => setFilter(e.target.value as FirmFilter)}>
          <option value="active">Active</option>
          <option value="archived">Archived</option>
          <option value="all">All</option>
        </Select>
      </div>

      <Card className="flex items-center gap-3 p-3">
        <Input
          type="search"
          aria-label="Search firms"
          placeholder="Search firms…"
          className="min-w-0 flex-1"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Button className="shrink-0 whitespace-nowrap" onClick={() => setShowAdd(true)}>+ Add Firm</Button>
      </Card>

      {loading && firms.length === 0 ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : visible.length === 0 ? (
        <p className="text-sm text-gray-500">No firms match.</p>
      ) : (
        <Card className="divide-y">
          {visible.map((f) => (
            <div key={f.id} className="flex items-center justify-between px-4 py-3">
              <button
                className="text-left font-medium text-blue-700 hover:underline"
                onClick={() => push({ kind: 'firmDetail', firmId: f.id, title: f.name })}
              >
                {f.name}
              </button>
              <div className="flex items-center gap-3">
                <span
                  className={
                    f.status === 'active'
                      ? 'text-xs font-medium text-green-700'
                      : 'text-xs font-medium text-gray-500'
                  }
                >
                  {f.status === 'active' ? 'Active' : 'Archived'}
                </span>
                <Button size="sm" variant="secondary" onClick={() => setNewMatterFirmId(f.id)}>
                  + Matter
                </Button>
                <Button size="sm" variant="primary" onClick={() => setNewMemoFirmId(f.id)}>
                  + Memo
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => void toggleStatus(f.id, f.status)}
                >
                  {f.status === 'active' ? 'Archive' : 'Unarchive'}
                </Button>
              </div>
            </div>
          ))}
        </Card>
      )}

      {showAdd && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md space-y-3 rounded-sm border border-gray-900 bg-gray-50 p-5 shadow-[0_6px_24px_rgba(28,27,25,0.18)]">
            <h3 className="text-lg font-medium">Add Firm</h3>
            <div>
              <Label>Firm name</Label>
              <Input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void createFirm()}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  setShowAdd(false)
                  setNewName('')
                }}
              >
                Cancel
              </Button>
              <Button onClick={createFirm} disabled={!newName.trim()}>Add Firm</Button>
            </div>
          </div>
        </div>
      )}

      {newMatterFirmId !== null && (
        <NewMatterDialog
          firmId={newMatterFirmId}
          onClose={() => setNewMatterFirmId(null)}
          onCreated={() => {
            setNewMatterFirmId(null)
            void load()
          }}
        />
      )}

      {newMemoFirmId !== null && (
        <NewMemoDialog firmId={newMemoFirmId} onClose={() => setNewMemoFirmId(null)} />
      )}
    </div>
  )
}
