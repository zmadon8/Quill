import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { Label } from '@/components/ui/Label'
import type { MatterMemoDefaults } from '@/types/ipc'

export type MatterFields = Required<{
  addresseeLine1: string
  addresseeLine2: string
  addresseeUseFirmName: boolean
  courtName: string
  client: string
  additionalDetailsLeft: string
  additionalDetailsRight: string
  plaintiffName: string
  plaintiffType: string
  defendantName: string
  defendantType: string
  notes: string
  shortName: string
}>

export const emptyMatterFields = (): MatterFields => ({
  addresseeLine1: '',
  addresseeLine2: '',
  addresseeUseFirmName: false,
  courtName: '',
  client: '',
  additionalDetailsLeft: '',
  additionalDetailsRight: '',
  plaintiffName: '',
  plaintiffType: '',
  defendantName: '',
  defendantType: '',
  notes: '',
  shortName: '',
})

/** Builds MatterFields from a stored matter's memo-default values. */
export const matterFieldsFrom = (d: MatterMemoDefaults): MatterFields => ({
  addresseeLine1: d.addresseeLine1 ?? '',
  addresseeLine2: d.addresseeLine2 ?? '',
  addresseeUseFirmName: d.addresseeUseFirmName ?? false,
  courtName: d.courtName ?? '',
  client: d.client ?? '',
  additionalDetailsLeft: d.additionalDetailsLeft ?? '',
  additionalDetailsRight: d.additionalDetailsRight ?? '',
  plaintiffName: d.plaintiffName ?? '',
  plaintiffType: d.plaintiffType ?? '',
  defendantName: d.defendantName ?? '',
  defendantType: d.defendantType ?? '',
  notes: d.notes ?? '',
  shortName: d.shortName ?? '',
})

interface Props {
  value: MatterFields
  onChange: (next: MatterFields) => void
  /**
   * Whether to render the Notes field. Notes live on the Matter detail page as
   * a dedicated, always-visible editor, so this form hides them (both when
   * creating and when editing a matter) to avoid duplication.
   */
  showNotes?: boolean
}

/**
 * Renders the matter-level memo-default fields shared by every memo in the
 * matter. Used both when creating a matter and when editing one.
 */
export function MatterFieldsForm({ value, onChange, showNotes = false }: Props) {
  const set = <K extends keyof MatterFields>(k: K, v: MatterFields[K]) =>
    onChange({ ...value, [k]: v })

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="col-span-2 flex items-center gap-2 rounded-sm bg-gray-100 px-3 py-2">
        <input
          id="useFirmName"
          type="checkbox"
          className="h-4 w-4"
          checked={value.addresseeUseFirmName}
          onChange={(e) => set('addresseeUseFirmName', e.target.checked)}
        />
        <Label htmlFor="useFirmName" className="mb-0 cursor-pointer">
          Use the firm&apos;s name as Addressee Line 1
        </Label>
      </div>

      <div className={value.addresseeUseFirmName ? 'opacity-50' : ''}>
        <Label>Addressee Line 1</Label>
        <Input
          value={value.addresseeLine1}
          disabled={value.addresseeUseFirmName}
          placeholder={value.addresseeUseFirmName ? '(firm name)' : ''}
          onChange={(e) => set('addresseeLine1', e.target.value)}
        />
      </div>
      <div>
        <Label>Addressee Line 2</Label>
        <Input value={value.addresseeLine2} onChange={(e) => set('addresseeLine2', e.target.value)} />
      </div>

      <div className="col-span-2">
        <Label>Cause Title</Label>
        <Textarea rows={2} value={value.courtName} onChange={(e) => set('courtName', e.target.value)} />
      </div>

      <div className="col-span-2">
        <Label>Client</Label>
        <Input value={value.client} onChange={(e) => set('client', e.target.value)} />
      </div>

      <div>
        <Label>Additional Details (Left)</Label>
        <Textarea
          rows={2}
          value={value.additionalDetailsLeft}
          onChange={(e) => set('additionalDetailsLeft', e.target.value)}
        />
      </div>
      <div>
        <Label>Additional Details (Right)</Label>
        <Textarea
          rows={2}
          value={value.additionalDetailsRight}
          onChange={(e) => set('additionalDetailsRight', e.target.value)}
        />
      </div>

      <div>
        <Label>Plaintiff Name</Label>
        <Input value={value.plaintiffName} onChange={(e) => set('plaintiffName', e.target.value)} />
      </div>
      <div>
        <Label>Plaintiff Type</Label>
        <Input value={value.plaintiffType} onChange={(e) => set('plaintiffType', e.target.value)} />
      </div>
      <div>
        <Label>Defendant Name</Label>
        <Input value={value.defendantName} onChange={(e) => set('defendantName', e.target.value)} />
      </div>
      <div>
        <Label>Defendant Type</Label>
        <Input value={value.defendantType} onChange={(e) => set('defendantType', e.target.value)} />
      </div>

      {showNotes && (
        <div className="col-span-2">
          <Label>Notes</Label>
          <Textarea rows={1} className="resize-y" value={value.notes} onChange={(e) => set('notes', e.target.value)} />
        </div>
      )}
    </div>
  )
}
