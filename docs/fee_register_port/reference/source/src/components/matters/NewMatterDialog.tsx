import { useEffect, useState } from 'react'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Label } from '@/components/ui/Label'
import { MatterFieldsForm, emptyMatterFields, type MatterFields } from './MatterFieldsForm'
import type { FirmDetail } from '@/types/ipc'

interface Props {
  firmId: number
  onClose: () => void
  onCreated: () => void
}

export function NewMatterDialog({ firmId, onClose, onCreated }: Props) {
  const [firm, setFirm] = useState<FirmDetail | null>(null)
  const [name, setName] = useState('')
  const [partnerId, setPartnerId] = useState<number | null>(null)
  // New matters default to using the firm's name as Addressee Line 1.
  const [fields, setFields] = useState<MatterFields>({
    ...emptyMatterFields(),
    addresseeUseFirmName: true,
  })
  const show = useToastStore((s) => s.show)

  useEffect(() => {
    void (async () => {
      const res = await window.api.firms.get(firmId)
      if (res.ok) {
        setFirm(res.data)
        if (res.data.partners.length) setPartnerId(res.data.partners[0].id)
      }
      // Req #1: pre-fill the matter's Cause Title from the Settings default.
      const s = await window.api.settings.get()
      if (s.ok && s.data.defaultCourtName) {
        setFields((f) => ({ ...f, courtName: s.data.defaultCourtName ?? '' }))
      }
    })()
  }, [firmId])

  const create = async () => {
    if (!name.trim() || partnerId === null) {
      show('Enter a matter name and select a partner.', 'error')
      return
    }
    const res = await window.api.matters.create({
      name: name.trim(),
      firmId,
      partnerId,
      ...fields,
    })
    if (res.ok) {
      show('Matter created.', 'success')
      onCreated()
    } else {
      show(errorMessage(res.error), 'error')
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-sm border border-gray-900 bg-gray-50 p-5 shadow-[0_6px_24px_rgba(28,27,25,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-3 text-xl font-medium">New Matter {firm ? `— ${firm.name}` : ''}</h3>
        {firm && firm.partners.length === 0 ? (
          <p className="text-sm text-red-600">Add a partner to this firm first.</p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Matter Name</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
              </div>
              <div>
                <Label>Group</Label>
                <Select
                  className="w-full"
                  value={partnerId ?? ''}
                  onChange={(e) => setPartnerId(Number(e.target.value))}
                >
                  {firm?.partners.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            <div>
              <Label>Short Name (used in the Word export)</Label>
              <Input
                value={fields.shortName}
                placeholder="Leave blank to use the full matter name"
                onChange={(e) => setFields({ ...fields, shortName: e.target.value })}
              />
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">
                Common memo details (shared by every memo in this matter)
              </p>
              <MatterFieldsForm value={fields} onChange={setFields} />
            </div>
          </div>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={create} disabled={!firm || firm.partners.length === 0}>
            Create
          </Button>
        </div>
      </div>
    </div>
  )
}
