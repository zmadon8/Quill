/**
 * Converts memo templates to the short tag names (L1, L16W, IF_APP …).
 * Originals are NEVER modified: each input X.docx produces "X (short tags).docx".
 *
 * Run: node scripts/convert-template-tags.mjs ["Template A.docx" "Template B.docx" …]
 * With no arguments, converts the two templates in the project root.
 */
import PizZip from 'pizzip'
import { readFileSync, writeFileSync, existsSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { convertTemplateXml } from './templateTags.mjs'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const inputs = process.argv.slice(2).length
  ? process.argv.slice(2)
  : ['Template 10-10-2026.docx', 'Template 10-10-2026 (conditional).docx']

for (const name of inputs) {
  const src = resolve(ROOT, name)
  if (!existsSync(src)) { console.log('skip (not found):', name); continue }
  const zip = new PizZip(readFileSync(src))
  let changed = 0
  for (const part of Object.keys(zip.files).filter((f) => /^word\/(document|header\d*|footer\d*)\.xml$/.test(f))) {
    const before = zip.file(part).asText()
    const after = convertTemplateXml(before)
    if (after !== before) { zip.file(part, after); changed++ }
  }
  const out = resolve(ROOT, name.replace(/\.docx$/i, ' (short tags).docx'))
  writeFileSync(out, zip.generate({ type: 'nodebuffer', compression: 'DEFLATE' }))
  console.log(`converted ${name} → ${out.split('/').pop()}  (${changed} part(s) rewritten)`)
}
