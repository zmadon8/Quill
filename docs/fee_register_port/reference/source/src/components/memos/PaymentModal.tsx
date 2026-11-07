import { useEffect, useMemo, useState, useCallback } from 'react'
import { DateInput } from '@/components/ui/DateInput'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Label } from '@/components/ui/Label'
import { PayeeSuggestions } from '@/components/feebook/PayeeSuggestions'
import { displayDate, todayIso } from '@/lib/formatDate'
import { prefillPayment } from '@/lib/paymentPrefill'
import type { PaymentDTO, PaymentInput, BankAccountDTO, MemoDetail, DefaultPaymentAmount } from '@/types/ipc'

interface Props {
  memoId: number
  onClose: () => void
}

/** Local draft shape: payment input plus the auto-TDS toggle and rate. */
type Draft = {
  amount: number
  tdsRate: number
  autoTds: boolean
  tdsAmount: number
  dateOfPayment: string
  payee: string
  bankAccountId: number | null
  paymentDetails: string
  paymentMode: string
}

const emptyDraft = (tdsRate: number): Draft => ({
  amount: 0,
  tdsRate,
  autoTds: true,
  tdsAmount: 0,
  dateOfPayment: todayIso(), // pre-fill today's date
  payee: '',
  bankAccountId: null,
  paymentDetails: '',
  paymentMode: '',
})

function round2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100
}

/** TDS = amount * 100 / (100 - rate) - amount. 0 for rate 0 or >= 100. */
function computeAutoTds(amount: number, rate: number): number {
  if (!(rate > 0) || rate >= 100) return 0
  return round2((amount * 100) / (100 - rate) - amount)
}

export function PaymentModal({ memoId, onClose }: Props) {
  const show = useToastStore((s) => s.show)
  const [memo, setMemo] = useState<MemoDetail | null>(null)
  const [payments, setPayments] = useState<PaymentDTO[]>([])
  const [banks, setBanks] = useState<BankAccountDTO[]>([])
  const [defaultTdsRate, setDefaultTdsRate] = useState(0)
  const [prefillMode, setPrefillMode] = useState<DefaultPaymentAmount>('zero')
  const [draft, setDraft] = useState<Draft>(emptyDraft(0))
  const [editingId, setEditingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    const m = await window.api.memos.get(memoId)
    if (m.ok) setMemo(m.data)
    const p = await window.api.payments.listForMemo(memoId)
    if (p.ok) setPayments(p.data)
  }, [memoId])

  useEffect(() => {
    void load()
    void (async () => {
      const b = await window.api.settings.listBankAccounts()
      if (b.ok) setBanks(b.data)
      const s = await window.api.settings.get()
      if (s.ok) {
        setDefaultTdsRate(s.data.defaultTdsRate)
        setPrefillMode(s.data.defaultPaymentAmount ?? 'zero')
        setDraft((d) => (editingId === null ? { ...d, tdsRate: s.data.defaultTdsRate } : d))
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load])

  // Effective TDS: auto-computed from rate when autoTds is on, else manual.
  const effectiveTds = draft.autoTds ? computeAutoTds(draft.amount, draft.tdsRate) : draft.tdsAmount
  const grossPayment = round2(draft.amount + effectiveTds)

  // Gross paid so far (amount + tds) across saved payments, for the summary.
  const grossPaidSoFar = useMemo(
    () => round2(payments.reduce((a, p) => a + p.grossAmount, 0)),
    [payments],
  )

  // Prefill "Amount Received" for the next NEW payment from the Settings
  // default, using what is still due on the memo. Only the amount / TDS boxes
  // are touched, so anything else already typed is kept. Runs once the memo and
  // its payments are loaded, and again after each payment is saved or deleted.
  useEffect(() => {
    if (editingId !== null || !memo) return
    const due = Math.max(0, round2(memo.totalFees - grossPaidSoFar))
    const pre = prefillPayment(prefillMode, due, defaultTdsRate)
    setDraft((d) => ({ ...d, amount: pre.amount, autoTds: pre.autoTds, tdsAmount: pre.tdsAmount }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memo, grossPaidSoFar, prefillMode, defaultTdsRate, editingId])

  const resetDraft = () => {
    setDraft(emptyDraft(defaultTdsRate))
    setEditingId(null)
  }

  const submit = async () => {
    if (!(draft.amount > 0) || !draft.dateOfPayment) {
      show('Enter an amount greater than 0 and a date.', 'error')
      return
    }
    const input: PaymentInput = {
      amount: draft.amount,
      tdsRate: draft.tdsRate,
      autoTds: draft.autoTds,
      tdsAmount: effectiveTds,
      dateOfPayment: draft.dateOfPayment,
      payee: draft.payee,
      bankAccountId: draft.bankAccountId,
      paymentDetails: draft.paymentDetails,
      paymentMode: draft.paymentMode,
    }
    const res = editingId
      ? await window.api.payments.update(editingId, input)
      : await window.api.payments.addToMemo(memoId, input)
    if (res.ok) {
      resetDraft()
      void load()
    } else {
      show(errorMessage(res.error), 'error')
    }
  }

  const edit = (p: PaymentDTO) => {
    setEditingId(p.id)
    setDraft({
      amount: p.amount,
      tdsRate: p.tdsRate,
      autoTds: p.autoTds,
      tdsAmount: p.tdsAmount,
      dateOfPayment: p.dateOfPayment,
      payee: p.payee ?? '',
      bankAccountId: p.bankAccountId,
      paymentDetails: p.paymentDetails ?? '',
      paymentMode: p.paymentMode ?? '',
    })
  }

  const remove = async (id: number) => {
    if (!confirm('Delete this payment? This cannot be undone.')) return
    const res = await window.api.payments.delete(id)
    if (res.ok) void load()
    else show(errorMessage(res.error), 'error')
  }

  const n = (v: string) => (v === '' ? 0 : Number(v))

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-sm border border-gray-900 bg-gray-50 p-6 shadow-[0_6px_24px_rgba(28,27,25,0.18)]" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-xl font-medium">Payments {memo ? `— ${memo.memoNumber}` : ''}</h3>
          <button className="text-gray-400 hover:text-gray-700" onClick={onClose}>×</button>
        </div>

        {memo && (
          <p className="mb-3 text-sm text-gray-600">
            Gross received ₹ {grossPaidSoFar.toLocaleString('en-IN')} of ₹ {memo.totalFees.toLocaleString('en-IN')}
            {grossPaidSoFar >= memo.totalFees && memo.totalFees > 0 && (
              <span className="ml-2 font-medium text-green-700">Fully paid</span>
            )}
          </p>
        )}

        {payments.length > 0 && (
          <div className="mb-4 divide-y rounded border">
            {payments.map((p) => (
              <div key={p.id} className="flex items-center justify-between px-3 py-2 text-sm">
                <span>₹ {p.amount.toLocaleString('en-IN')}</span>
                <span className="text-gray-500">+ TDS ₹ {p.tdsAmount.toLocaleString('en-IN')}</span>
                <span className="font-medium">= ₹ {p.grossAmount.toLocaleString('en-IN')}</span>
                <span className="text-gray-500">{displayDate(p.dateOfPayment)}</span>
                <span className="text-gray-500">{p.payee || '—'}</span>
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => edit(p)}>Edit</Button>
                  <Button size="sm" variant="ghost" onClick={() => remove(p.id)}>Delete</Button>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 rounded border bg-gray-50 p-3">
          <div>
            <Label>Amount Received</Label>
            <Input type="number" min={0} value={draft.amount} onChange={(e) => setDraft({ ...draft, amount: n(e.target.value) })} />
          </div>
          <div>
            <Label>Date</Label>
            <DateInput value={draft.dateOfPayment} onChange={(v) => setDraft({ ...draft, dateOfPayment: v })} showToday />
          </div>
          <div>
            <Label>TDS Rate (%)</Label>
            <Input type="number" min={0} max={99} value={draft.tdsRate} onChange={(e) => setDraft({ ...draft, tdsRate: n(e.target.value) })} />
          </div>
          <div>
            <Label>TDS</Label>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={0}
                value={draft.autoTds ? effectiveTds : draft.tdsAmount}
                disabled={draft.autoTds}
                className={draft.autoTds ? 'bg-gray-100 text-gray-500' : ''}
                onChange={(e) => setDraft({ ...draft, tdsAmount: n(e.target.value) })}
              />
              <label className="flex shrink-0 items-center gap-1 text-xs text-gray-600">
                <input
                  type="checkbox"
                  checked={draft.autoTds}
                  onChange={(e) => setDraft({ ...draft, autoTds: e.target.checked })}
                />
                auto
              </label>
            </div>
          </div>
          <div className="col-span-2 rounded bg-white px-3 py-2 text-sm">
            Gross Payment (Amount + TDS): <strong>₹ {grossPayment.toLocaleString('en-IN')}</strong>
          </div>
          <div>
            <Label>Payee</Label>
            <Input value={draft.payee} onChange={(e) => setDraft({ ...draft, payee: e.target.value })} />
            <PayeeSuggestions
              matterIds={memo ? [memo.matterId] : []}
              current={draft.payee}
              onPick={(payee) => setDraft({ ...draft, payee })}
            />
          </div>
          <div>
            <Label>Bank Account</Label>
            <Select
              className="w-full"
              value={draft.bankAccountId ?? ''}
              onChange={(e) => setDraft({ ...draft, bankAccountId: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">—</option>
              {banks.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          </div>
          <div>
            <Label>Payment Mode</Label>
            <Input list="payment-modes" value={draft.paymentMode} placeholder="Cheque, NEFT, UPI, Cash…" onChange={(e) => setDraft({ ...draft, paymentMode: e.target.value })} />
            <datalist id="payment-modes">
              {['Cheque', 'NEFT / RTGS', 'UPI', 'Cash', 'Bank transfer'].map((m) => <option key={m} value={m} />)}
            </datalist>
          </div>
          <div>
            <Label>Payment Details (internal)</Label>
            <Input value={draft.paymentDetails} onChange={(e) => setDraft({ ...draft, paymentDetails: e.target.value })} />
          </div>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          {editingId && <Button variant="ghost" onClick={resetDraft}>Cancel edit</Button>}
          <Button onClick={submit}>{editingId ? 'Update Payment' : 'Add Payment'}</Button>
        </div>
      </div>
    </div>
  )
}
