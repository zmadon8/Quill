import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Money } from '@/components/ui/Money'
import { PaymentEntryModal } from '@/components/feebook/PaymentEntryModal'
import { displayDate } from '@/lib/formatDate'
import type { PaymentDTO } from '@/types/ipc'

/**
 * Payments made against one memo, shown on the memo page. "+ Payment" records
 * a new one for this memo; "Edit" opens the full payment editor (amount, TDS,
 * mode, bank, and how it is split across memos). Each row shows this memo's
 * share of the payment.
 */
export function MemoPayments({
  memoId,
  totalFees,
  onChanged,
}: {
  memoId: number
  totalFees: number
  /** Called after a payment is added, edited or deleted. */
  onChanged?: () => void
}) {
  const [payments, setPayments] = useState<PaymentDTO[]>([])
  const [adding, setAdding] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)

  const load = useCallback(async () => {
    const res = await window.api.payments.listForMemo(memoId)
    if (res.ok) setPayments(res.data)
  }, [memoId])

  useEffect(() => {
    void load()
  }, [load])

  const paid = payments.reduce((a, p) => a + p.grossAmount, 0)
  const due = Math.max(0, totalFees - paid)
  const done = () => {
    setAdding(false)
    setEditId(null)
    void load()
    onChanged?.()
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Payments</h3>
        <Button size="sm" variant="success" onClick={() => setAdding(true)}>+ Payment</Button>
      </div>

      {payments.length === 0 ? (
        <p className="text-sm text-gray-500">No payments recorded against this memo yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className="px-3 py-2 text-left">Date</th>
              <th className="px-3 py-2 text-left">Payee</th>
              <th className="px-3 py-2 text-left">Mode</th>
              <th className="px-3 py-2 text-right">Paid</th>
              <th className="px-3 py-2 text-right">TDS</th>
              <th className="px-3 py-2 text-right">Paid + TDS</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y">
            {payments.map((p) => (
              <tr key={p.id}>
                <td className="px-3 py-2">{displayDate(p.dateOfPayment)}</td>
                <td className="px-3 py-2">{p.payee || '—'}</td>
                <td className="px-3 py-2">{p.paymentMode || '—'}</td>
                <td className="px-3 py-2 text-right tabular-nums">₹ <Money v={p.amount} /></td>
                <td className="px-3 py-2 text-right tabular-nums">₹ <Money v={p.tdsAmount} /></td>
                <td className="px-3 py-2 text-right tabular-nums">₹ <Money v={p.grossAmount} /></td>
                <td className="px-3 py-2 text-right">
                  <Button size="sm" variant="secondary" onClick={() => setEditId(p.id)}>Edit</Button>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td className="px-3 py-2 font-semibold" colSpan={5}>
                Memo ₹ <Money v={totalFees} /> · Paid ₹ <Money v={paid} />
              </td>
              <td className="px-3 py-2 text-right font-bold tabular-nums">Due ₹ <Money v={due} /></td>
              <td />
            </tr>
          </tfoot>
        </table>
      )}

      {adding && <PaymentEntryModal initialMemoIds={[memoId]} onClose={() => setAdding(false)} onSaved={done} />}
      {editId !== null && <PaymentEntryModal paymentId={editId} onClose={() => setEditId(null)} onSaved={done} />}
    </Card>
  )
}
