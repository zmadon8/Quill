import { describe, it } from 'vitest'
import * as fc from 'fast-check'
import { feesInWords } from '@/services/feesInWordsService'

describe('feesInWords — property tests', () => {
  it('Property 14: always starts with "Rupees" and ends with "Only" for any non-negative integer', () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 9999999999 }), (amount) => {
        const result = feesInWords(amount)
        return result.startsWith('Rupees') && result.endsWith('Only')
      }),
      { numRuns: 200 },
    )
  })

  it('Property 14b: holds for decimal amounts (paise) as well', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 999999999 }),
        fc.integer({ min: 0, max: 99 }),
        (rupees, paise) => {
          const amount = rupees + paise / 100
          const result = feesInWords(amount)
          return result.startsWith('Rupees') && result.endsWith('Only')
        },
      ),
      { numRuns: 200 },
    )
  })
})
