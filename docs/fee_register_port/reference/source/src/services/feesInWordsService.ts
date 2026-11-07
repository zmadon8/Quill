/**
 * feesInWordsService.ts
 * Pure TypeScript — converts a non-negative decimal (INR) to Indian-English words.
 * Uses the Indian numbering system: crore / lakh / thousand / hundred.
 * Output is always prefixed with "Rupees" and suffixed with "Only".
 *
 * Examples:
 *   120000        → "Rupees One Lakh Twenty Thousand Only"
 *   10000000.50   → "Rupees One Crore and Fifty Paise Only"
 *   0             → "Rupees Zero Only"
 */

const ONES: readonly string[] = [
  '',
  'One',
  'Two',
  'Three',
  'Four',
  'Five',
  'Six',
  'Seven',
  'Eight',
  'Nine',
  'Ten',
  'Eleven',
  'Twelve',
  'Thirteen',
  'Fourteen',
  'Fifteen',
  'Sixteen',
  'Seventeen',
  'Eighteen',
  'Nineteen',
]

const TENS: readonly string[] = [
  '',
  '',
  'Twenty',
  'Thirty',
  'Forty',
  'Fifty',
  'Sixty',
  'Seventy',
  'Eighty',
  'Ninety',
]

/**
 * Converts an integer in the range 1–999 to English words.
 * Returns an empty string for 0.
 */
function convertHundreds(n: number): string {
  if (n === 0) return ''

  const parts: string[] = []

  if (n >= 100) {
    parts.push(`${ONES[Math.floor(n / 100)]} Hundred`)
    n = n % 100
  }

  if (n > 0) {
    if (n < 20) {
      parts.push(ONES[n])
    } else {
      const tens = TENS[Math.floor(n / 10)]
      const unit = ONES[n % 10]
      parts.push(unit ? `${tens} ${unit}` : tens)
    }
  }

  return parts.join(' ')
}

/**
 * Converts a non-negative integer in the range 0–9,99,99,99,999 to Indian-English words.
 * Returns "Zero" for 0.
 */
function integerToWords(n: number): string {
  if (n === 0) return 'Zero'

  const parts: string[] = []

  // Crores (up to 99,99,99,999 → 999 crore)
  const crores = Math.floor(n / 10_000_000)
  if (crores > 0) {
    const croreWords = convertHundreds(crores)
    parts.push(`${croreWords} ${crores === 1 ? 'Crore' : 'Crores'}`)
    n = n % 10_000_000
  }

  // Lakhs (0–99)
  const lakhs = Math.floor(n / 100_000)
  if (lakhs > 0) {
    const lakhWords = convertHundreds(lakhs)
    parts.push(`${lakhWords} ${lakhs === 1 ? 'Lakh' : 'Lakhs'}`)
    n = n % 100_000
  }

  // Thousands (0–99)
  const thousands = Math.floor(n / 1_000)
  if (thousands > 0) {
    const thousandWords = convertHundreds(thousands)
    parts.push(`${thousandWords} Thousand`)
    n = n % 1_000
  }

  // Hundreds, tens, units (0–999)
  if (n > 0) {
    parts.push(convertHundreds(n))
  }

  return parts.join(' ')
}

/**
 * Converts a non-negative decimal amount (INR) to Indian-English words.
 *
 * @param amount - A non-negative number representing rupees (and optional paise).
 * @returns A string in the form "Rupees <words> Only" or
 *          "Rupees <rupee words> and <paise words> Paise Only".
 */
export function feesInWords(amount: number): string {
  if (amount < 0) {
    throw new RangeError('feesInWords: amount must be non-negative')
  }

  // Round to 2 decimal places to avoid floating-point noise
  const rounded = Math.round(amount * 100) / 100

  const rupees = Math.floor(rounded)
  // Compute paise as an integer (0–99) to avoid floating-point issues
  const paise = Math.round((rounded - rupees) * 100)

  const rupeeWords = integerToWords(rupees)

  if (paise === 0) {
    return `Rupees ${rupeeWords} Only`
  }

  const paiseWords = convertHundreds(paise)

  if (rupees === 0) {
    return `Rupees Zero and ${paiseWords} Paise Only`
  }

  return `Rupees ${rupeeWords} and ${paiseWords} Paise Only`
}
