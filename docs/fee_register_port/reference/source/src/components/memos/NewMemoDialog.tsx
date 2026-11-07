import { useEffect, useMemo, useState } from 'react'
import { useNavStore } from '@/stores/useNavStore'
import { useToastStore } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { Label } from '@/components/ui/Label'
import type { FirmSummary, MatterDetail } from '@/types/ipc'

interface Props {
  /** When provided, the firm is pre-selected (e.g. the Firms "+ Memo" button). */
  firmId?: number
  onClose: () => void
}

/**
 * Lets the user pick a Firm & Matter, then opens the memo form for that matter
 * (Req #11). Only active matters are offered, since memos can only be created
 * for active matters.
 */
export function NewMemoDialog({ firmId, onClose }: Props) {
  const push = useNavStore((s) => s.push)
  const show = useToastStore((s) => s.show)
  const [firms, setFirms] = useState<FirmSummary[]>([])
  const [matters, setMatters] = useState<MatterDetail[]>([])
  const [selectedFirm, setSelectedFirm] = useState<number | ''>(firmId ?? '')
  const [selectedMatter, setSelectedMatter] = useState<number | ''>('')

  useEffect(() => {
    void (async () => {
      const f = await window.api.firms.list('active')
      if (f.ok) setFirms(f.data)
      const m = await window.api.matters.list('active')
      if (m.ok) setMatters(m.data)
    })()
  }, [])

  const firmMatters = useMemo(
    () => (selectedFirm === '' ? [] : matters.filter((m) => m.firmId === selectedFirm)),
    [matters, selectedFirm],
  )

  // Auto-select the only matter when a firm has exactly one.
  useEffect(() => {
    if (firmMatters.length === 1) setSelectedMatter(firmMatters[0].id)
    else setSelectedMatter('')
  }, [firmMatters])

  const create = () => {
    if (selectedMatter === '') {
      show('Choose a firm and matter.', 'error')
      return
    }
    const matter = matters.find((m) => m.id === selectedMatter)
    push({ kind: 'memoForm', matterId: selectedMatter, title: `New Memo — ${matter?.name ?? ''}` })
    onClose()
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div
        className="w-full max-w-md rounded-sm border border-gray-900 bg-gray-50 p-5 shadow-[0_6px_24px_rgba(28,27,25,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-3 text-xl font-medium">New Memo</h3>
        <div className="space-y-3">
          <div>
            <Label>Firm</Label>
            <Select
              className="w-full"
              value={selectedFirm}
              onChange={(e) => setSelectedFirm(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Select a firm…</option>
              {firms.map((f) => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </Select>
          </div>
          <div>
            <Label>Matter</Label>
            <Select
              className="w-full"
              value={selectedMatter}
              disabled={selectedFirm === ''}
              onChange={(e) => setSelectedMatter(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">
                {selectedFirm === '' ? 'Select a firm first' : 'Select a matter…'}
              </option>
              {firmMatters.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </Select>
            {selectedFirm !== '' && firmMatters.length === 0 && (
              <p className="mt-1 text-xs text-amber-600">
                This firm has no active matters. Add one from the firm page.
              </p>
            )}
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={create} disabled={selectedMatter === ''}>Create Memo</Button>
        </div>
      </div>
    </div>
  )
}
