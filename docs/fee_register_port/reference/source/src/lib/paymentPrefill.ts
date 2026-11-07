import type { DefaultPaymentAmount } from '@/types/ipc'

const round2 = (n: number): number => Math.round((n + Number.EPSILON) * 100) / 100

export interface PaymentPrefill {
  /** Value for the "Amount Received" box (net of TDS). */
  amount: number
  /** Whether TDS should be auto-computed on top of the amount. */
  autoTds: boolean
  /** TDS to use when autoTds is false. */
  tdsAmount: number
}

/**
 * What to put in "Amount Received" for a memo that still has `due` outstanding,
 * according to the Settings default:
 *   zero      - 0
 *   full      - the whole amount due; no TDS is added on top (the memo is paid
 *               in full by exactly this amount)
 *   netOfTds  - the amount due less TDS at `tdsRate`, worked out the same way as
 *               the Net of TDS column on the Memos page. Auto-TDS then adds the
 *               TDS back, so amount + TDS equals the amount due.
 */
export function prefillPayment(mode: DefaultPaymentAmount, due: number, tdsRate: number): PaymentPrefill {
  const d = Math.max(0, round2(due))
  if (mode === 'full') return { amount: d, autoTds: false, tdsAmount: 0 }
  if (mode === 'netOfTds') {
    const less = tdsRate > 0 && tdsRate < 100 ? round2((d * tdsRate) / 100) : 0
    return { amount: round2(d - less), autoTds: true, tdsAmount: 0 }
  }
  return { amount: 0, autoTds: true, tdsAmount: 0 }
}
