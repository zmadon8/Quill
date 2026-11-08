/**
 * Adds docxtemplater conditional sections to the user's memo template so that
 * disabled fee lines (Appearances / Conferences / Misc) are removed entirely
 * from the exported Word document.
 *
 * Strategy: each fee line is its own table row (<w:tr>). To delete a whole row
 * conditionally, docxtemplater wants the opening section tag {{#SHOW_X}} inside
 * the first cell of the row and the closing tag {{/SHOW_X}} inside the last
 * cell. When the flag is false, the entire row is dropped.
 *
 * We locate each fee row by a stable placeholder it contains, then inject a
 * tag run at the row boundary. The injection is idempotent — running twice does
 * not double-wrap (it checks for an existing tag first).
 *
 * Input : "Template 8-10-2026.docx" (next to this project root)
 * Output: "Template 8-10-2026 (conditional).docx"
 *
 * Run: node scripts/add-template-conditionals.mjs
 */
import PizZip from 'pizzip'
import { readFileSync, writeFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..')
// Allow the input/output paths to be overridden via CLI args.
const IN = resolve(ROOT, process.argv[2] ?? 'Template 10-10-2026.docx')
const OUT = resolve(ROOT, process.argv[3] ?? 'Template 10-10-2026 (conditional).docx')

const zip = new PizZip(readFileSync(IN))
let xml = zip.file('word/document.xml').asText()

// A bare text run carrying just a tag (keeps the row's existing formatting
// intact; the tag text itself is consumed by docxtemplater and leaves nothing).
const tagRun = (tag) =>
  `<w:r><w:t xml:space="preserve">${tag}</w:t></w:r>`

/**
 * Wrap a whole <w:tr> that contains `anchorToken` with {{#flag}} ... {{/flag}}.
 * The open tag is inserted as the first run of the first cell's first paragraph;
 * the close tag as the last run of the last cell's last paragraph.
 */
function wrapRow(anchorToken, flag) {
  if (xml.includes(`{{#${flag}}}`)) return // already wrapped (idempotent)

  // Find the <w:tr ...> ... </w:tr> that contains the anchor token.
  const tokenIdx = xml.indexOf(anchorToken)
  if (tokenIdx === -1) throw new Error(`Anchor not found: ${anchorToken}`)

  const trStart = xml.lastIndexOf('<w:tr ', tokenIdx)
  const trEndClose = xml.indexOf('</w:tr>', tokenIdx)
  if (trStart === -1 || trEndClose === -1) throw new Error(`Row not found for ${anchorToken}`)

  const rowOpenEnd = xml.indexOf('>', trStart) + 1 // end of the <w:tr ...> tag
  const rowInner = xml.slice(rowOpenEnd, trEndClose)

  // Insert the open tag as the first run inside the first <w:p> of the row, and
  // the close tag as the last run inside the last <w:p> of the row.
  const firstPOpen = rowInner.indexOf('<w:p ')
  const firstPOpenEnd = rowInner.indexOf('>', rowInner.indexOf('<w:pPr', firstPOpen) === -1 ? firstPOpen : firstPOpen)
  // Simpler + robust: inject right after the first <w:p ...> ... first </w:pPr>
  // if present, else right after the first <w:p ...> open tag.
  let injected = rowInner
  const pOpenMatch = /<w:p\b[^>]*>/.exec(injected)
  const pStart = pOpenMatch.index + pOpenMatch[0].length
  const pprClose = injected.indexOf('</w:pPr>', pStart)
  const openInsertAt = pprClose !== -1 ? pprClose + '</w:pPr>'.length : pStart
  injected =
    injected.slice(0, openInsertAt) + tagRun(`{{#${flag}}}`) + injected.slice(openInsertAt)

  // Close tag: before the last </w:p> in the row.
  const lastPClose = injected.lastIndexOf('</w:p>')
  injected = injected.slice(0, lastPClose) + tagRun(`{{/${flag}}}`) + injected.slice(lastPClose)

  xml = xml.slice(0, rowOpenEnd) + injected + xml.slice(trEndClose)
}

wrapRow('{{LINE_16_NUM_APPEARANCES}}', 'SHOW_APPEARANCES')
wrapRow('{{LINE_19_NUM_CONFERENCES}}', 'SHOW_CONFERENCES')
wrapRow('{{LINE_22_MISC_DESC}}', 'SHOW_MISC')
// Req #7: hide Plaintiff / Defendant / Client lines when blank.
wrapRow('{{LINE_11_PLAINTIFF}}', 'SHOW_PLAINTIFF')
wrapRow('{{LINE_13_DEFENDANT}}', 'SHOW_DEFENDANT')
wrapRow('{{LINE_15_CLIENT}}', 'SHOW_CLIENT')

zip.file('word/document.xml', xml)
writeFileSync(OUT, zip.generate({ type: 'nodebuffer', compression: 'DEFLATE' }))
console.log(`Wrote ${OUT}`)
