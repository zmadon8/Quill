import { describe, it, expect } from 'vitest'
import { prefillPayment } from '@/lib/paymentPrefill'

describe('prefillPayment', () => {
  it('zero leaves the box at 0', () => {
    expect(prefillPayment('zero', 50000, 10)).toEqual({ amount: 0, autoTds: true, tdsAmount: 0 })
  })
  it('full uses the whole amount due and adds no TDS', () => {
    expect(prefillPayment('full', 50000, 10)).toEqual({ amount: 50000, autoTds: false, tdsAmount: 0 })
  })
  it('netOfTds is the amount due less TDS at the rate, as on the Memos page', () => {
    expect(prefillPayment('netOfTds', 50000, 10)).toEqual({ amount: 45000, autoTds: true, tdsAmount: 0 })
    expect(prefillPayment('netOfTds', 12345, 10).amount).toBe(11110.5)
  })
  it('netOfTds with no TDS rate equals the amount due', () => {
    expect(prefillPayment('netOfTds', 8000, 0).amount).toBe(8000)
  })
  it('never goes negative for an overpaid memo', () => {
    expect(prefillPayment('full', -300, 10).amount).toBe(0)
    expect(prefillPayment('netOfTds', -300, 10).amount).toBe(0)
  })
})
