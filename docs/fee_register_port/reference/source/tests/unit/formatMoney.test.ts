import { describe, it, expect } from 'vitest'
import { formatMoney, formatMoneyUnit } from '@/lib/formatMoney'

describe('formatMoney', () => {
  it('groups with Indian digits and no decimals', () => {
    expect(formatMoney(312451)).toBe('3,12,451')
    expect(formatMoney(1234567)).toBe('12,34,567')
    expect(formatMoney(0)).toBe('0')
  })
  it('rounds and defends against non-finite input', () => {
    expect(formatMoney(100.6)).toBe('101')
    expect(formatMoney(null)).toBe('0')
    expect(formatMoney(undefined)).toBe('0')
    expect(formatMoney(NaN)).toBe('0')
  })
})

describe('formatMoneyUnit', () => {
  it('shows 0 and single-digit amounts as the real number in truncated mode', () => {
    expect(formatMoneyUnit(0, 'truncated')).toBe('0')
    expect(formatMoneyUnit(7, 'truncated')).toBe('7')
    expect(formatMoneyUnit(-3, 'truncated')).toBe('-3')
  })

  it('uses custom suffixes for thousands / lacs / crores', () => {
    const custom = { thousands: 'K', lac: 'Lakh', crore: 'Cr' }
    expect(formatMoneyUnit(5300, 'truncated', custom)).toBe('5.3K')
    expect(formatMoneyUnit(670000, 'truncated', custom)).toBe('6.7 Lakh')
    expect(formatMoneyUnit(35000000, 'truncated', custom)).toBe('3.5 Cr')
  })

  it("'full' matches formatMoney (grouped integer, no suffix)", () => {
    expect(formatMoneyUnit(312451, 'full')).toBe('3,12,451')
  })

  it("'truncated' uses thousands below 1 lac", () => {
    expect(formatMoneyUnit(5300, 'truncated')).toBe('5.3k') // user example
    expect(formatMoneyUnit(99999, 'truncated')).toBe('100k') // 99.999 → 100 (rounds, still < 1 lac boundary by abs)
    expect(formatMoneyUnit(5000, 'truncated')).toBe('5k') // trailing zeros trimmed
    expect(formatMoneyUnit(10, 'truncated')).toBe('0.01k') // 10 is the first value that is scaled
  })

  it("'truncated' uses lacs from 1 lac up to (but not including) 1 crore", () => {
    expect(formatMoneyUnit(670000, 'truncated')).toBe('6.7 lac') // user example
    expect(formatMoneyUnit(100000, 'truncated')).toBe('1 lac') // exactly 1 lac
    expect(formatMoneyUnit(312451, 'truncated')).toBe('3.12 lac') // 3.12451 → 3.12
    expect(formatMoneyUnit(9999999, 'truncated')).toBe('100 lac') // just below 1 crore
  })

  it("'truncated' uses crores at 1 crore and above", () => {
    expect(formatMoneyUnit(35000000, 'truncated')).toBe('3.5 cr') // user example 3,50,00,000
    expect(formatMoneyUnit(10000000, 'truncated')).toBe('1 cr') // exactly 1 crore
    expect(formatMoneyUnit(123456789, 'truncated')).toBe('12.35 cr') // 12.3456789 → 12.35
  })

  it('truncated scales negatives by magnitude too', () => {
    expect(formatMoneyUnit(-5300, 'truncated')).toBe('-5.3k')
    expect(formatMoneyUnit(-35000000, 'truncated')).toBe('-3.5 cr')
  })

  it('defaults to full and handles non-finite input', () => {
    expect(formatMoneyUnit(312451)).toBe('3,12,451')
    expect(formatMoneyUnit(null, 'truncated')).toBe('0')
  })
})
