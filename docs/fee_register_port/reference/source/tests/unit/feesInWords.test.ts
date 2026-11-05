import { describe, it, expect } from 'vitest'
import { feesInWords } from '@/services/feesInWordsService'

describe('feesInWords', () => {
  it('0 → Rupees Zero Only', () => {
    expect(feesInWords(0)).toBe('Rupees Zero Only')
  })

  it('1000 → Rupees One Thousand Only', () => {
    expect(feesInWords(1000)).toBe('Rupees One Thousand Only')
  })

  it('100000 → Rupees One Lakh Only', () => {
    expect(feesInWords(100000)).toBe('Rupees One Lakh Only')
  })

  it('1000000 → Rupees Ten Lakhs Only', () => {
    expect(feesInWords(1000000)).toBe('Rupees Ten Lakhs Only')
  })

  it('10000000 → Rupees One Crore Only', () => {
    expect(feesInWords(10000000)).toBe('Rupees One Crore Only')
  })

  it('120000 → Rupees One Lakh Twenty Thousand Only', () => {
    expect(feesInWords(120000)).toBe('Rupees One Lakh Twenty Thousand Only')
  })

  it('10000000.50 → Rupees One Crore and Fifty Paise Only', () => {
    expect(feesInWords(10000000.50)).toBe('Rupees One Crore and Fifty Paise Only')
  })

  it('60000 → Rupees Sixty Thousand Only', () => {
    expect(feesInWords(60000)).toBe('Rupees Sixty Thousand Only')
  })

  it('54000 → Rupees Fifty Four Thousand Only', () => {
    expect(feesInWords(54000)).toBe('Rupees Fifty Four Thousand Only')
  })

  it('negative number throws RangeError', () => {
    expect(() => feesInWords(-1)).toThrow(RangeError)
  })
})
