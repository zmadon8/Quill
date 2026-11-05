import { useEffect, useMemo, useState } from 'react'
import { DateInput } from '@/components/ui/DateInput'
import { MemoPayments } from '@/components/memos/MemoPayments'
import { useNavStore } from '@/stores/useNavStore'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { Select } from '@/components/ui/Select'
import { Label } from '@/components/ui/Label'
import { Card } from '@/components/ui/Card'
import { feesAppearances, feesConferences, totalFees } from '@/lib/memoCalc'
import type { MemoInput, BankAccountDTO } from '@/types/ipc'

interface Props {
  memoId?: number
  basedOnId?: number
  matterId?: number
}

type FormState = MemoInput & { memoNumber?: string | null }

const emptyForm = (matterId: number): FormState => ({
  date: '',
  matterId,
  addresseeLine1: '',
  addresseeLine2: '',
  courtName: '',
  additionalDetailsLeft: '',
  additionalDetailsRight: '',
  plaintiffName: '',
  plaintiffType: '',
  defendantName: '',
  defendantType: '',
  client: '',
  numAppearances: 0,
  datesOfAppearances: '',
  feesPerAppearance: 0,
  numConferences: 0,
  datesOfConferences: '',
  feesPerConference: 0,
  miscDraftingDescription: '',
  feesMiscDrafting: 0,
  numDrafts: 0,
})

export function MemoFormPage({ memoId, basedOnId, matterId }: Props) {
  const pop = useNavStore((s) => s.pop)
  const push = useNavStore((s) => s.push)
  const setGuard = useNavStore((s) => s.setGuard)
  const show = useToastStore((s) => s.show)
  const [form, setForm] = useState<FormState>(emptyForm(matterId ?? 0))
  const [bankAccounts, setBankAccounts] = useState<BankAccountDTO[]>([])
  const [saving, setSaving] = useState(false)
  // Tracks unsaved edits so navigating away prompts for confirmation.
  const [dirty, setDirty] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [previewNumber, setPreviewNumber] = useState<string>('')
  // Once a brand-new memo is saved, it becomes an existing memo. We track its
  // id so that staying on the page (Req #9) doesn't create duplicate memos on
  // subsequent saves/exports.
  const [savedMemoId, setSavedMemoId] = useState<number | undefined>(memoId)
  // Per-line enable toggles (Req #4). A disabled line is greyed out and its
  // values are ignored (zeroed) when the memo is saved.
  const [enableAppearances, setEnableAppearances] = useState(true)
  const [enableConferences, setEnableConferences] = useState(true)
  const [enableMisc, setEnableMisc] = useState(true)
  // Custom amounts (Req #4): when on, the user types the billable figures
  // instead of auto-calculating from counts × rates.
  const [useCustomAmounts, setUseCustomAmounts] = useState(false)
  // Whether the currently-open memo is still a draft.
  const [isDraftMemo, setIsDraftMemo] = useState(false)
  // "Custom Memo Number": when on, the user types the memo number instead of it
  // being auto-generated. A per-memo choice, independent of the matter.
  const [useCustomNumber, setUseCustomNumber] = useState(false)

  const effectiveMemoId = savedMemoId
  const isEdit = effectiveMemoId !== undefined

  // For a NEW memo, preview the memo number that would be assigned for the
  // chosen date (recomputed whenever the date changes). Editing shows the
  // already-assigned number instead.
  useEffect(() => {
    if (isEdit || !form.date || useCustomNumber) {
      setPreviewNumber('')
      return
    }
    let cancelled = false
    void (async () => {
      const res = await window.api.memos.previewNumber(form.date)
      if (!cancelled && res.ok) setPreviewNumber(res.data)
    })()
    return () => {
      cancelled = true
    }
  }, [form.date, isEdit, useCustomNumber])

  useEffect(() => {
    void (async () => {
      const banks = await window.api.settings.listBankAccounts()
      if (banks.ok) setBankAccounts(banks.data)

      if (memoId !== undefined) {
        const res = await window.api.memos.get(memoId)
        if (res.ok) {
          const m = res.data
          setUseCustomNumber(m.isCustomNumber)
          setForm({ ...m, memoNumber: m.memoNumber, customMemoNumber: m.customMemoNumber })
          // Enable a line if the loaded memo has any data for it.
          setEnableAppearances(m.numAppearances > 0 || m.feesPerAppearance > 0)
          setEnableConferences(m.numConferences > 0 || m.feesPerConference > 0)
          setEnableMisc(m.feesMiscDrafting > 0 || !!m.miscDraftingDescription)
          setIsDraftMemo(m.isDraft)
          // A memo with any custom override is in custom-amount mode.
          setUseCustomAmounts(
            m.customFeesAppearances != null || m.customFeesConferences != null ||
            m.customFeesMisc != null || m.customTotalFees != null,
          )
        } else show(errorMessage(res.error), 'error')
        return
      }
      if (basedOnId !== undefined) {
        const res = await window.api.memos.createBasedOn(basedOnId)
        if (res.ok) {
          const d = res.data
          // A new memo based on another defaults to auto-numbering.
          setForm({ ...d, customMemoNumber: '' })
          setUseCustomNumber(false)
          setEnableAppearances(d.numAppearances > 0 || d.feesPerAppearance > 0)
          setEnableConferences(d.numConferences > 0 || d.feesPerConference > 0)
          setEnableMisc(d.feesMiscDrafting > 0 || !!d.miscDraftingDescription)
          // Carry over custom-amount mode if the source memo used overrides.
          setUseCustomAmounts(
            d.customFeesAppearances != null || d.customFeesConferences != null ||
            d.customFeesMisc != null || d.customTotalFees != null,
          )
        } else show(errorMessage(res.error), 'error')
        return
      }
      // New memo: pre-fill from the matter's stored common details, falling
      // back to Settings defaults for fees / Cause Title / TDS. Fee rates are
      // seeded from the most recent memo in this matter when one exists
      // ("remember last-used values per matter").
      const settings = await window.api.settings.get()
      const matter = matterId !== undefined ? await window.api.matters.get(matterId) : null
      const md = matter && matter.ok ? matter.data : null

      // A brand-new memo starts with the Appearances / Conferences / Misc ticks
      // on or off, per Settings > Defaults > Display. (Editing and duplicating
      // a memo set the ticks from the memo's own data instead.)
      const linesOn = settings.ok ? settings.data.defaultLinesEnabled !== false : true
      setEnableAppearances(linesOn)
      setEnableConferences(linesOn)
      setEnableMisc(linesOn)

      // Last-used fee rates from the matter's most recent memo, if any.
      let lastFeesPerAppearance: number | null = null
      let lastFeesPerConference: number | null = null
      let lastFeesMisc: number | null = null
      if (matterId !== undefined) {
        const prior = await window.api.memos.listForMatter(matterId)
        if (prior.ok && prior.data.length > 0) {
          // listForMatter is ordered newest-first; take the latest.
          const latest = await window.api.memos.get(prior.data[0].id)
          if (latest.ok) {
            lastFeesPerAppearance = latest.data.feesPerAppearance
            lastFeesPerConference = latest.data.feesPerConference
            lastFeesMisc = latest.data.feesMiscDrafting
          }
        }
      }
      const firmName = md?.firmName ?? ''
      // Addressee Line 1: the firm name when the matter's toggle is on,
      // otherwise the matter's stored Addressee Line 1.
      const addressee1 = md?.addresseeUseFirmName ? firmName : md?.addresseeLine1 ?? ''

      setForm((f) => ({
        ...f,
        // A new memo starts with a BLANK date (use the Today button to fill it).
        date: '',
        addresseeLine1: addressee1,
        addresseeLine2: md?.addresseeLine2 ?? '',
        courtName: md?.courtName ?? (settings.ok ? settings.data.defaultCourtName ?? '' : ''),
        client: md?.client ?? '',
        additionalDetailsLeft:
          md?.additionalDetailsLeft || (settings.ok ? settings.data.defaultAdditionalDetailsLeft ?? '' : ''),
        additionalDetailsRight:
          md?.additionalDetailsRight || (settings.ok ? settings.data.defaultAdditionalDetailsRight ?? '' : ''),
        plaintiffName: md?.plaintiffName ?? '',
        plaintiffType: md?.plaintiffType ?? '',
        defendantName: md?.defendantName ?? '',
        defendantType: md?.defendantType ?? '',
        feesPerAppearance:
          lastFeesPerAppearance ?? (settings.ok ? settings.data.defaultFeesPerAppearance : 0),
        feesPerConference:
          lastFeesPerConference ?? (settings.ok ? settings.data.defaultFeesPerConference : 0),
        feesMiscDrafting:
          lastFeesMisc ?? (settings.ok ? settings.data.defaultFeesMiscDrafting : 0),
      }))
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memoId, basedOnId, matterId])

  const calc = useMemo(() => {
    if (useCustomAmounts) {
      const fApp = enableAppearances ? form.customFeesAppearances ?? 0 : 0
      const fConf = enableConferences ? form.customFeesConferences ?? 0 : 0
      const misc = enableMisc ? form.customFeesMisc ?? 0 : 0
      // A custom total overrides the sum when provided (> 0).
      const total = (form.customTotalFees ?? 0) > 0 ? (form.customTotalFees as number) : totalFees(fApp, fConf, misc)
      return { fApp, fConf, total }
    }
    const fApp = enableAppearances ? feesAppearances(form.numAppearances, form.feesPerAppearance) : 0
    const fConf = enableConferences ? feesConferences(form.numConferences, form.feesPerConference) : 0
    const misc = enableMisc ? form.feesMiscDrafting : 0
    const total = totalFees(fApp, fConf, misc)
    return { fApp, fConf, total }
  }, [form, enableAppearances, enableConferences, enableMisc, useCustomAmounts])

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => {
    setDirty(true)
    setForm((f) => ({ ...f, [k]: v }))
  }
  const num = (v: string) => (v === '' ? 0 : Number(v))

  // Register an unsaved-edits guard with the nav store while dirty. Returning
  // false from the guard cancels navigation (Back / tab switch / Cancel).
  useEffect(() => {
    if (!dirty) {
      setGuard(null)
      return
    }
    setGuard(() => window.confirm('You have unsaved changes. Leave this memo without saving?'))
    return () => setGuard(null)
  }, [dirty, setGuard])

  const validate = (): boolean => {
    const errs: string[] = []
    if (!form.date) errs.push('Date is required.')
    if (!form.matterId) errs.push('Matter is required.')
    if (useCustomNumber && !(form.customMemoNumber ?? '').trim()) {
      errs.push('Enter a memo number, or turn off “Custom Memo Number”.')
    }
    if (calc.total < 0) errs.push('Total fees cannot be negative.')
    setErrors(errs)
    return errs.length === 0
  }

  const buildPayload = (): MemoInput => {
    // Disabled lines (Req #4) are excluded from the memo: their numeric and
    // text values are zeroed/cleared before saving.
    const payload: MemoInput = {
      ...form,
      // Only send a custom number when the toggle is on; otherwise auto-number.
      customMemoNumber: useCustomNumber ? (form.customMemoNumber ?? '').trim() : null,
      numAppearances: enableAppearances ? form.numAppearances : 0,
      feesPerAppearance: enableAppearances ? form.feesPerAppearance : 0,
      datesOfAppearances: enableAppearances ? form.datesOfAppearances : '',
      numConferences: enableConferences ? form.numConferences : 0,
      feesPerConference: enableConferences ? form.feesPerConference : 0,
      datesOfConferences: enableConferences ? form.datesOfConferences : '',
      miscDraftingDescription: enableMisc ? form.miscDraftingDescription : '',
      feesMiscDrafting: enableMisc ? form.feesMiscDrafting : 0,
      // Custom amounts (Req #4): send overrides only when enabled, else clear.
      customFeesAppearances: useCustomAmounts ? form.customFeesAppearances ?? 0 : null,
      customFeesConferences: useCustomAmounts ? form.customFeesConferences ?? 0 : null,
      customFeesMisc: useCustomAmounts ? form.customFeesMisc ?? 0 : null,
      customTotalFees: useCustomAmounts ? form.customTotalFees ?? 0 : null,
    }
    return payload
  }

  const persist = async (asDraft = false): Promise<number | null> => {
    const payload = buildPayload()
    let res
    if (effectiveMemoId !== undefined) {
      res = await window.api.memos.update(effectiveMemoId, payload)
    } else if (asDraft) {
      res = await window.api.memos.saveDraft(payload)
    } else {
      res = await window.api.memos.create(payload)
    }
    if (res.ok) {
      const saved = res.data
      setDirty(false) // saved — no unsaved edits remain
      setSavedMemoId(saved.id)
      setIsDraftMemo(saved.isDraft)
      setForm((f) => ({ ...f, memoNumber: saved.memoNumber }))
      return saved.id
    }
    show(errorMessage(res.error), 'error')
    return null
  }

  const onSaveDraft = async () => {
    // Drafts may be incomplete; only require a matter.
    if (!form.matterId) {
      setErrors(['Matter is required.'])
      return
    }
    setSaving(true)
    try {
      const id = await persist(true)
      if (id !== null) show('Saved as draft.', 'success')
    } finally {
      setSaving(false)
    }
  }

  const onFinalizeDraft = async () => {
    if (effectiveMemoId === undefined) return
    if (!validate()) return
    setSaving(true)
    try {
      // Persist current edits, then assign a number.
      const id = await persist()
      if (id === null) return
      const res = await window.api.memos.finalizeDraft(
        id,
        useCustomNumber ? form.customMemoNumber ?? '' : undefined,
      )
      if (res.ok) {
        setIsDraftMemo(false)
        setForm((f) => ({ ...f, memoNumber: res.data.memoNumber }))
        show('Draft finalised and numbered.', 'success')
      } else show(errorMessage(res.error), 'error')
    } finally {
      setSaving(false)
    }
  }

  const onSave = async (then?: 'word') => {
    if (!validate()) return
    setSaving(true)
    try {
      const id = await persist()
      if (id === null) return
      if (then === 'word') {
        const r = await window.api.memos.exportWord(id)
        if (r.ok) {
          if (r.data.saved) show('Exported to Word.', 'success')
        } else show(errorMessage(r.error), 'error')
      } else {
        show('Memo saved.', 'success')
      }
      // Req #9: stay on the memo page after Save / Save & Export.
    } finally {
      setSaving(false)
    }
  }

  const text = (label: string, k: keyof FormState, multi = false, rows = 2) => (
    <div>
      <Label>{label}</Label>
      {multi ? (
        <Textarea rows={rows} value={(form[k] as string) ?? ''} onChange={(e) => set(k, e.target.value as never)} />
      ) : (
        <Input value={(form[k] as string) ?? ''} onChange={(e) => set(k, e.target.value as never)} />
      )}
    </div>
  )

  return (
    <div
      className="mx-auto max-w-4xl space-y-4 pb-24"
      // Keyboard-first: Cmd/Ctrl+Enter saves from anywhere in the form.
      onKeyDown={(e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !saving) {
          e.preventDefault()
          void onSave()
        }
      }}
    >
      <h2 className="text-[1.75rem] font-normal leading-tight">
        {isEdit ? `Edit Memo ${form.memoNumber ?? ''}` : 'New Memo'}
      </h2>
      <p className="text-xs text-gray-400">Tip: press ⌘/Ctrl + Enter to save.</p>

      {errors.length > 0 && (
        <Card className="border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {errors.map((e) => (
            <div key={e}>{e}</div>
          ))}
        </Card>
      )}

      <Card className="grid grid-cols-2 gap-4 p-4">
        <div>
          <Label>Date</Label>
          <DateInput value={form.date} onChange={(v) => set("date", v)} showToday />
        </div>
        <div>
          <Label>Memo Number</Label>
          <label className="mb-1 flex items-center gap-2 text-xs font-medium text-gray-600">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={useCustomNumber}
              onChange={(e) => {
                setDirty(true)
                setUseCustomNumber(e.target.checked)
              }}
            />
            Custom Memo Number (type my own instead of auto-generating)
          </label>
          {useCustomNumber ? (
            <>
              <Input
                value={form.customMemoNumber ?? ''}
                placeholder="Enter custom memo number"
                onChange={(e) => set('customMemoNumber', e.target.value)}
              />
              <p className="mt-1 text-xs text-gray-400">
                This memo will use the number you type (must be unique).
              </p>
            </>
          ) : (
            <>
              <Input
                value={isEdit ? form.memoNumber ?? '' : previewNumber || '(set a date)'}
                readOnly
                className="bg-gray-50 text-gray-500"
              />
              {!isEdit && previewNumber && (
                <p className="mt-1 text-xs text-gray-400">
                  Provisional — assigned on save; may change if other memos are saved first.
                </p>
              )}
            </>
          )}
        </div>
        {text('Addressee Line 1', 'addresseeLine1')}
        {text('Addressee Line 2', 'addresseeLine2', true, 1)}
        {text('Cause Title', 'courtName', true, 4)}
        {text('Client', 'client')}
        {text('Additional Details (Left)', 'additionalDetailsLeft', true, 1)}
        {text('Additional Details (Right)', 'additionalDetailsRight', true, 1)}
        {text('Plaintiff Name', 'plaintiffName')}
        {text('Plaintiff Type', 'plaintiffType')}
        {text('Defendant Name', 'defendantName')}
        {text('Defendant Type', 'defendantType')}
      </Card>

      <Card className="space-y-4 p-4">
        {/* Appearances line */}
        <div>
          <label className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-700">
            <input type="checkbox" className="h-4 w-4" checked={enableAppearances} onChange={(e) => { setDirty(true); setEnableAppearances(e.target.checked) }} />
            Appearances
          </label>
          <div className={`grid grid-cols-3 gap-4 ${enableAppearances ? '' : 'opacity-40'}`}>
            <div>
              <Label>No. of Appearances</Label>
              <Input type="number" min={0} disabled={!enableAppearances} value={form.numAppearances} onChange={(e) => set('numAppearances', num(e.target.value))} />
            </div>
            <div>
              <Label>Fees / Appearance</Label>
              <Input type="number" min={0} disabled={!enableAppearances} value={form.feesPerAppearance} onChange={(e) => set('feesPerAppearance', num(e.target.value))} />
            </div>
            <div>
              <Label>Dates of Appearances</Label>
              <Input disabled={!enableAppearances} value={form.datesOfAppearances ?? ''} onChange={(e) => set('datesOfAppearances', e.target.value)} />
            </div>
          </div>
        </div>

        {/* Conferences line */}
        <div>
          <label className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-700">
            <input type="checkbox" className="h-4 w-4" checked={enableConferences} onChange={(e) => { setDirty(true); setEnableConferences(e.target.checked) }} />
            Conferences
          </label>
          <div className={`grid grid-cols-3 gap-4 ${enableConferences ? '' : 'opacity-40'}`}>
            <div>
              <Label>No. of Conferences</Label>
              <Input type="number" min={0} disabled={!enableConferences} value={form.numConferences} onChange={(e) => set('numConferences', num(e.target.value))} />
            </div>
            <div>
              <Label>Fees / Conference</Label>
              <Input type="number" min={0} disabled={!enableConferences} value={form.feesPerConference} onChange={(e) => set('feesPerConference', num(e.target.value))} />
            </div>
            <div>
              <Label>Dates of Conferences</Label>
              <Input disabled={!enableConferences} value={form.datesOfConferences ?? ''} onChange={(e) => set('datesOfConferences', e.target.value)} />
            </div>
          </div>
        </div>

        {/* No. of Drafts — statistics counter only; never affects the total. */}
        <div>
          <Label>No. of Drafts (statistics only — does not affect the memo total)</Label>
          <Input
            type="number"
            min={0}
            className="w-40"
            value={form.numDrafts}
            onChange={(e) => set('numDrafts', num(e.target.value))}
          />
        </div>

        {/* Misc / Drafting line */}
        <div>
          <label className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-700">
            <input type="checkbox" className="h-4 w-4" checked={enableMisc} onChange={(e) => { setDirty(true); setEnableMisc(e.target.checked) }} />
            Misc / Drafting
          </label>
          <div className={`grid grid-cols-3 gap-4 ${enableMisc ? '' : 'opacity-40'}`}>
            <div className="col-span-2">
              <Label>Misc / Drafting Description</Label>
              <Input disabled={!enableMisc} value={form.miscDraftingDescription ?? ''} onChange={(e) => set('miscDraftingDescription', e.target.value)} />
            </div>
            <div>
              <Label>Fees for Misc / Drafting</Label>
              <Input type="number" min={0} disabled={!enableMisc} value={form.feesMiscDrafting} onChange={(e) => set('feesMiscDrafting', num(e.target.value))} />
            </div>
          </div>
        </div>
      </Card>

      <Card className="space-y-3 bg-gray-50 p-4 text-sm">
        <label className="flex items-center gap-2 font-medium text-gray-700">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={useCustomAmounts}
            onChange={(e) => {
              const on = e.target.checked
              // Req #2: when switching custom amounts ON, seed each box with the
              // currently auto-calculated figure (not 0) so the user starts from
              // the computed values and only edits what differs.
              if (on) {
                const autoApp = enableAppearances
                  ? feesAppearances(form.numAppearances, form.feesPerAppearance)
                  : 0
                const autoConf = enableConferences
                  ? feesConferences(form.numConferences, form.feesPerConference)
                  : 0
                const autoMisc = enableMisc ? form.feesMiscDrafting : 0
                setForm((f) => ({
                  ...f,
                  customFeesAppearances: f.customFeesAppearances ?? autoApp,
                  customFeesConferences: f.customFeesConferences ?? autoConf,
                  customFeesMisc: f.customFeesMisc ?? autoMisc,
                  customTotalFees: f.customTotalFees ?? 0,
                }))
              }
              setDirty(true)
              setUseCustomAmounts(on)
            }}
          />
          Enter custom amounts (override auto-calculation)
        </label>
        <p className="text-xs text-gray-500">
          Custom amounts replace the per-line calculation above. Disabled lines are excluded; the
          boxes start from the auto-calculated figures and can be edited.
        </p>

        {useCustomAmounts ? (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Fees for Appearances</Label>
              <Input type="number" min={0} value={form.customFeesAppearances ?? 0} onChange={(e) => set('customFeesAppearances', num(e.target.value))} />
            </div>
            <div>
              <Label>Fees for Conferences</Label>
              <Input type="number" min={0} value={form.customFeesConferences ?? 0} onChange={(e) => set('customFeesConferences', num(e.target.value))} />
            </div>
            <div>
              <Label>Fees for Drafts / Misc</Label>
              <Input type="number" min={0} value={form.customFeesMisc ?? 0} onChange={(e) => set('customFeesMisc', num(e.target.value))} />
            </div>
            <div>
              <Label>Total Memo Amount (0 = sum of the three)</Label>
              <Input type="number" min={0} value={form.customTotalFees ?? 0} onChange={(e) => set('customTotalFees', num(e.target.value))} />
            </div>
            <div className="col-span-2 text-base">Total Fees: <strong>₹ {calc.total.toLocaleString('en-IN')}</strong></div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            <div>Fees for Appearances: <strong>₹ {calc.fApp.toLocaleString('en-IN')}</strong></div>
            <div>Fees for Conferences: <strong>₹ {calc.fConf.toLocaleString('en-IN')}</strong></div>
            <div className="col-span-2 text-base">Total Fees: <strong>₹ {calc.total.toLocaleString('en-IN')}</strong></div>
          </div>
        )}
      </Card>

      {isEdit && !isDraftMemo && effectiveMemoId !== undefined && (
        <MemoPayments memoId={effectiveMemoId} totalFees={calc.total} />
      )}

      {isEdit && bankAccounts.length === 0 && (
        <p className="text-xs text-gray-400">Tip: add bank accounts in Settings to record them on payments.</p>
      )}

      <div className="fixed bottom-0 left-0 right-0 flex flex-wrap justify-end gap-2 border-t bg-white px-6 py-3">
        <Button variant="secondary" onClick={pop} disabled={saving}>Cancel</Button>
        {isEdit && effectiveMemoId !== undefined && (
          <Button
            variant="secondary"
            disabled={saving}
            onClick={() => {
              // Replace this view with a new memo based on it.
              const id = effectiveMemoId
              pop()
              push({ kind: 'memoForm', basedOnId: id, title: 'New Memo' })
            }}
          >
            Duplicate
          </Button>
        )}
        {/* Draft actions: show "Save as Draft" for new/draft memos; "Finalise"
            to assign a number to a draft. */}
        {(!isEdit || isDraftMemo) && (
          <Button variant="secondary" onClick={onSaveDraft} disabled={saving}>Save as Draft</Button>
        )}
        {isEdit && isDraftMemo && (
          <Button variant="indigo" onClick={onFinalizeDraft} disabled={saving}>Finalise &amp; Number</Button>
        )}
        <Button onClick={() => onSave()} disabled={saving}>Save</Button>
        <Button variant="secondary" onClick={() => onSave('word')} disabled={saving}>Save &amp; Export Word</Button>
      </div>
    </div>
  )
}
