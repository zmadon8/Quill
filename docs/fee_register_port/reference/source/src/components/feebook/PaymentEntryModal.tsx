import { useEffect, useMemo, useState } from 'react'
import { DateInput } from '@/components/ui/DateInput'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { confirmDialog } from '@/stores/useConfirmStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Label } from '@/components/ui/Label'
import { PayeeSuggestions } from '@/components/feebook/PayeeSuggestions'
import { todayIso } from '@/lib/formatDate'
import { formatMoney } from '@/lib/formatMoney'
import { prefillPayment } from '@/lib/paymentPrefill'
import type { DefaultPaymentAmount, PaymentInput, BankAccountDTO, MemoListItem, PaymentAllocationInput, PaymentDTO } from '@/types/ipc'

interface Props {
  /** When set, the modal edits this payment (including its memo allocations). */
  paymentId?: number
  /** New payment only: pre-select these memos, each for its remaining due. */
  initialMemoIds?: number[]
  onClose: () => void
  onSaved: () => void
}

function round2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100
}
function computeAutoTds(amount: number, rate: number): number {
  if (!(rate > 0) || rate >= 100) return 0
  return round2((amount * 100) / (100 - rate) - amount)
}

const MODES = ['Cheque', 'NEFT / RTGS', 'UPI', 'Cash', 'Bank transfer']

// Each allocated memo carries its own TDS rate. When autoTds is on the row's
// TDS is computed from its amount and rate; otherwise it is typed.
type AllocRow = {
  memoId: number | ''
  amount: number
  tdsRate: number
  autoTds: boolean
  tdsAmount: number
}

/** The TDS actually applied to an allocation row (auto from rate, or manual). */
function rowTds(r: AllocRow): number {
  return r.autoTds ? computeAutoTds(r.amount, r.tdsRate) : round2(r.tdsAmount)
}

/**
 * Records OR edits a payment and allocates it across zero, one, or several
 * memos. Only outstanding (not fully paid, not written-off) memos are offered
 * as targets, plus any memo the payment is already applied to when editing.
 */
export function PaymentEntryModal({ paymentId, initialMemoIds, onClose, onSaved }: Props) {
  const isEdit = paymentId !== undefined
  const show = useToastStore((s) => s.show)
  const [banks, setBanks] = useState<BankAccountDTO[]>([])
  const [memos, setMemos] = useState<MemoListItem[]>([])
  const [amount, setAmount] = useState(0)
  const [tdsRate, setTdsRate] = useState(0)
  const [defaultRate, setDefaultRate] = useState(0)
  const [prefillMode, setPrefillMode] = useState<DefaultPaymentAmount>('zero')
  const [autoTds, setAutoTds] = useState(true)
  const [tdsAmount, setTdsAmount] = useState(0)
  const [dateOfPayment, setDate] = useState(todayIso())
  const [payee, setPayee] = useState('')
  const [bankAccountId, setBankAccountId] = useState<number | null>(null)
  const [paymentDetails, setDetails] = useState('')
  const [paymentMode, setMode] = useState('')
  const [allocs, setAllocs] = useState<AllocRow[]>([])
  const [existing, setExisting] = useState<PaymentDTO | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    void (async () => {
      const b = await window.api.settings.listBankAccounts()
      if (b.ok) setBanks(b.data)
      const s = await window.api.settings.get()
      if (s.ok) {
        setDefaultRate(s.data.defaultTdsRate)
        if (!isEdit) setTdsRate(s.data.defaultTdsRate)
      }
      let own = new Set<number>()
      let rate = s.ok ? s.data.defaultTdsRate : 0
      const mode: DefaultPaymentAmount = s.ok ? s.data.defaultPaymentAmount ?? 'zero' : 'zero'
      setPrefillMode(mode)
      if (isEdit) {
        const p = await window.api.payments.get(paymentId!)
        if (p.ok) {
          const d = p.data
          setExisting(d)
          setAmount(d.amount)
          setTdsRate(d.tdsRate)
          rate = d.tdsRate
          setAutoTds(d.autoTds)
          setTdsAmount(d.tdsAmount)
          setDate(d.dateOfPayment)
          setPayee(d.payee ?? '')
          setBankAccountId(d.bankAccountId)
          setDetails(d.paymentDetails ?? '')
          setMode(d.paymentMode ?? '')
          own = new Set(d.allocations.map((a) => a.memoId))
          setAllocs(
            d.allocations.map((a) => ({
              memoId: a.memoId,
              amount: a.amount,
              tdsRate: d.tdsRate,
              autoTds: false,
              tdsAmount: a.tdsAmount,
            })),
          )
        } else show(errorMessage(p.error), 'error')
      }
      const m = await window.api.memos.list({})
      if (m.ok) {
        setMemos(m.data.filter((x) => (x.status === 'Unpaid' && !x.writtenOff) || own.has(x.id) || (initialMemoIds ?? []).includes(x.id)))
        if (!isEdit && initialMemoIds && initialMemoIds.length > 0) {
          const rows: AllocRow[] = []
          for (const id of initialMemoIds) {
            const memo = m.data.find((x) => x.id === id)
            if (!memo) continue
            const pre = prefillPayment(mode, memo.amountDue, rate)
            rows.push({ memoId: id, amount: pre.amount, tdsRate: rate, autoTds: pre.autoTds, tdsAmount: pre.tdsAmount })
          }
          setAllocs(rows)
          setAmount(round2(rows.reduce((a, r) => a + r.amount, 0)))
          // "Full" means exactly the memo amount was received: no TDS on top.
          if (mode === 'full') {
            setAutoTds(false)
            setTdsAmount(0)
          }
        }
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paymentId])

  const effectiveTds = autoTds ? computeAutoTds(amount, tdsRate) : tdsAmount
  const gross = round2(amount + effectiveTds)
  const n = (v: string) => (v === '' ? 0 : Number(v))

  // What this payment currently contributes to each memo (edit mode), so the
  // "remaining due" shown/prefilled excludes the payment being edited.
  const ownGross = useMemo(() => {
    const map = new Map<number, number>()
    for (const a of existing?.allocations ?? []) map.set(a.memoId, a.grossAmount)
    return map
  }, [existing])

  const options = useMemo(
    () =>
      memos.map((m) => ({
        id: m.id,
        label: `${m.memoNumber} — ${m.matterName} (₹ ${formatMoney(m.totalFees)})`,
      })),
    [memos],
  )

  // Matters of the memos picked below (plus the payment's own, when editing).
  const suggestMatterIds = allocs
    .filter((r) => r.memoId !== '')
    .map((r) => memos.find((m) => m.id === r.memoId)?.matterId)
    .filter((id): id is number => id !== undefined)

  const allocatedGross = round2(allocs.reduce((a, r) => a + r.amount + rowTds(r), 0))
  const remaining = round2(gross - allocatedGross)

  const addRow = () =>
    setAllocs((rs) => [...rs, { memoId: '', amount: 0, tdsRate: defaultRate || tdsRate, autoTds: true, tdsAmount: 0 }])
  const removeRow = (i: number) => setAllocs((rs) => rs.filter((_, idx) => idx !== i))
  const setRow = (i: number, patch: Partial<AllocRow>) =>
    setAllocs((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))

  /** Picking a memo prefills the amount: its remaining due, less TDS. */
  const pickMemo = (i: number, memoId: number | '') => {
    if (memoId === '') {
      setRow(i, { memoId })
      return
    }
    const memo = memos.find((m) => m.id === memoId)
    const due = memo ? Math.max(0, round2(memo.amountDue + (ownGross.get(memoId) ?? 0))) : 0
    const next = allocs.map((r, idx) => {
      if (idx !== i) return r
      const pre = prefillPayment(prefillMode, due, r.tdsRate)
      return { ...r, memoId, autoTds: pre.autoTds, tdsAmount: pre.tdsAmount, amount: pre.amount }
    })
    setAllocs(next)
    // With a prefill chosen in Settings, the Amount Received box follows the
    // memos picked (new payments only; an edit keeps the amount it already has).
    if (!isEdit && prefillMode !== 'zero') {
      setAmount(round2(next.reduce((a, r) => a + r.amount, 0)))
      if (prefillMode === 'full') {
        setAutoTds(false)
        setTdsAmount(0)
      }
    }
  }

  const save = async () => {
    if (!(amount > 0) || !dateOfPayment) {
      show('Enter an amount greater than 0 and a date.', 'error')
      return
    }
    const allocations: PaymentAllocationInput[] = allocs
      .filter((r) => r.memoId !== '')
      .map((r) => ({ memoId: r.memoId as number, amount: r.amount, tdsAmount: rowTds(r) }))

    const input: PaymentInput = {
      amount,
      tdsRate,
      autoTds,
      tdsAmount: effectiveTds,
      dateOfPayment,
      payee,
      bankAccountId,
      paymentDetails,
      paymentMode,
      // On edit an empty array means "now unaccounted"; on add it is omitted.
      allocations: isEdit ? allocations : allocations.length > 0 ? allocations : undefined,
    }
    setSaving(true)
    try {
      const res = isEdit
        ? await window.api.payments.update(paymentId!, input)
        : await window.api.payments.add(input)
      if (res.ok) {
        show(
          isEdit
            ? 'Payment updated.'
            : allocations.length === 0
              ? 'Unaccounted payment recorded.'
              : 'Payment recorded.',
          'success',
        )
        onSaved()
      } else {
        show(errorMessage(res.error), 'error')
      }
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!isEdit) return
    const ok = await confirmDialog({
      title: 'Delete this payment?',
      message:
        'This permanently removes the payment and its allocation(s). Any memo it was ' +
        'applied to will show the reduced paid amount.',
      confirmLabel: 'Delete Payment',
      destructive: true,
    })
    if (!ok) return
    const res = await window.api.payments.delete(paymentId!)
    if (res.ok) {
      show('Payment deleted.', 'success')
      onSaved()
    } else show(errorMessage(res.error), 'error')
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-5xl overflow-y-auto rounded-sm border border-gray-900 bg-gray-50 p-6 shadow-[0_6px_24px_rgba(28,27,25,0.18)]" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-xl font-medium">{isEdit ? 'Edit Payment' : 'Add Payment'}</h3>
          <button className="text-gray-400 hover:text-gray-700" aria-label="Close" onClick={onClose}>×</button>
        </div>
        <p className="mb-3 text-sm text-gray-500">
          Record a payment and allocate it to one, several, or no memos. Leave the allocation list
          empty to record it as unaccounted.
        </p>

        <div className="grid grid-cols-2 gap-3 rounded border bg-gray-50 p-3">
          <div>
            <Label>Amount Received</Label>
            <Input type="number" min={0} value={amount} onChange={(e) => setAmount(n(e.target.value))} />
          </div>
          <div>
            <Label>Date</Label>
            <DateInput value={dateOfPayment} onChange={(v) => setDate(v)} showToday />
          </div>
          <div>
            <Label>TDS Rate (%)</Label>
            <Input type="number" min={0} max={99} value={tdsRate} onChange={(e) => setTdsRate(n(e.target.value))} />
          </div>
          <div>
            <Label>TDS</Label>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={0}
                value={autoTds ? effectiveTds : tdsAmount}
                disabled={autoTds}
                className={autoTds ? 'bg-gray-100 text-gray-500' : ''}
                onChange={(e) => setTdsAmount(n(e.target.value))}
              />
              <label className="flex shrink-0 items-center gap-1 text-xs text-gray-600">
                <input type="checkbox" checked={autoTds} onChange={(e) => setAutoTds(e.target.checked)} />
                auto
              </label>
            </div>
          </div>
          <div className="col-span-2 rounded bg-white px-3 py-2 text-sm">
            Gross Payment (Amount + TDS): <strong>₹ {formatMoney(gross)}</strong>
          </div>
          <div>
            <Label>Payee</Label>
            <Input value={payee} onChange={(e) => setPayee(e.target.value)} />
            <PayeeSuggestions matterIds={suggestMatterIds} current={payee} onPick={setPayee} />
          </div>
          <div>
            <Label>Bank Account</Label>
            <Select className="w-full" value={bankAccountId ?? ''} onChange={(e) => setBankAccountId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">—</option>
              {banks.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          </div>
          <div>
            <Label>Payment Mode</Label>
            <Input
              list="payment-modes"
              value={paymentMode}
              placeholder="Cheque, NEFT, UPI, Cash…"
              onChange={(e) => setMode(e.target.value)}
            />
            <datalist id="payment-modes">
              {MODES.map((m) => <option key={m} value={m} />)}
            </datalist>
          </div>
          <div>
            <Label>Payment Details (internal)</Label>
            <Input value={paymentDetails} onChange={(e) => setDetails(e.target.value)} />
          </div>
        </div>

        <div className="mt-4 rounded border p-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium text-gray-700">Allocate to memos</p>
            <Button size="sm" variant="secondary" onClick={addRow}>+ Memo</Button>
          </div>
          {allocs.length === 0 ? (
            <p className="text-xs text-gray-400">No allocations — this will be an unaccounted payment.</p>
          ) : (
            <div className="space-y-2">
              {allocs.map((r, i) => (
                <div key={i} className="flex flex-wrap items-end gap-2">
                  <div className="min-w-[320px] flex-[3]">
                    <Label>Memo</Label>
                    <Select
                      className="w-full"
                      value={r.memoId}
                      onChange={(e) => pickMemo(i, e.target.value ? Number(e.target.value) : '')}
                    >
                      <option value="">Select…</option>
                      {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
                    </Select>
                  </div>
                  <div className="w-32">
                    <Label>Amount</Label>
                    <Input type="number" min={0} value={r.amount} onChange={(e) => setRow(i, { amount: n(e.target.value) })} />
                  </div>
                  <div className="w-20">
                    <Label>Rate %</Label>
                    <Input
                      type="number"
                      min={0}
                      max={99}
                      value={r.tdsRate}
                      onChange={(e) => setRow(i, { tdsRate: n(e.target.value) })}
                    />
                  </div>
                  <div className="w-44">
                    <Label>TDS</Label>
                    <div className="flex items-center gap-1">
                      <Input
                        type="number"
                        min={0}
                        value={r.autoTds ? rowTds(r) : r.tdsAmount}
                        disabled={r.autoTds}
                        className={r.autoTds ? 'bg-gray-100 text-gray-500' : ''}
                        onChange={(e) => setRow(i, { tdsAmount: n(e.target.value) })}
                      />
                      <label className="flex shrink-0 items-center gap-0.5 text-xs text-gray-600">
                        <input
                          type="checkbox"
                          checked={r.autoTds}
                          onChange={(e) => setRow(i, { autoTds: e.target.checked })}
                        />
                        auto
                      </label>
                    </div>
                  </div>
                  <button
                    className="pb-2 text-gray-400 hover:text-red-600"
                    aria-label="Remove allocation"
                    onClick={() => removeRow(i)}
                  >
                    ×
                  </button>
                </div>
              ))}
              <p className={`text-xs ${remaining === 0 ? 'text-gray-500' : 'text-amber-700'}`}>
                Allocated ₹ {formatMoney(allocatedGross)} of ₹ {formatMoney(gross)} (gross). Remaining ₹ {formatMoney(remaining)}.
              </p>
            </div>
          )}
        </div>

        <div className="mt-4 flex items-center justify-between gap-2">
          {isEdit ? (
            <Button variant="danger" onClick={remove} disabled={saving}>Delete Payment</Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose} disabled={saving}>Cancel</Button>
            <Button onClick={save} disabled={saving}>{isEdit ? 'Save Changes' : 'Record Payment'}</Button>
          </div>
        </div>
      </div>
    </div>
  )
}
