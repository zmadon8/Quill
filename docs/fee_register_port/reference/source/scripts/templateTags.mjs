/**
 * Pure conversion of a memo template's document XML from the long tag names
 * (LINE_16_NUM_APPEARANCES, SHOW_APPEARANCES) to the short ones (L16, IF_APP),
 * folding the literal words "Appearances" / "Conferences" that follow the count
 * into the new singular/plural tags L16W / L19W ("1 Appearance", "2 Appearances").
 *
 * Word often splits one tag over several text runs ("{{LINE_1" + "_DATE}}"), so
 * the tag matcher tolerates XML between the braces and merges the pieces.
 */
export const FLAG_ALIASES = {
  SHOW_APPEARANCES: 'IF_APP',
  SHOW_CONFERENCES: 'IF_CONF',
  SHOW_MISC: 'IF_MISC',
  SHOW_PLAINTIFF: 'IF_PL',
  SHOW_DEFENDANT: 'IF_DEF',
  SHOW_CLIENT: 'IF_CLIENT',
}

/** Maps one tag (with optional section prefix # / ^) to its short name. */
export function shortTag(name) {
  const t = name.trim()
  const prefix = /^[#/^]/.test(t) ? t[0] : ''
  const core = prefix ? t.slice(1).trim() : t
  const line = /^LINE_(\d+[A-Z]?)_/.exec(core)
  if (line) return `${prefix}L${line[1]}`
  if (FLAG_ALIASES[core]) return `${prefix}${FLAG_ALIASES[core]}`
  return t
}

/** Builds a regex fragment matching \`word\` even when XML tags split its letters. */
const loose = (word) => word.split('').join('(?:<[^>]*>)*')

export function convertTemplateXml(xml) {
  // 1. Rename every tag, merging tags split across runs — including a split
  //    BETWEEN the two opening braces ({ … { ) or the two closing ones.
  let out = xml.replace(/\{(?:<[^>]*>)*\{((?:[^{}]|<[^>]*>)*?)\}(?:<[^>]*>)*\}/g, (_m, inner) => {
    const name = inner.replace(/<[^>]*>/g, '')
    return `{{${shortTag(name)}}}`
  })
  // 2. "{{L16}} Appearances" → "{{L16W}}" ; "{{L19}} Conferences" → "{{L19W}}".
  //    Only whitespace/XML may lie between the count tag and the word, but the
  //    word itself may be split over several runs (spell-check marks do this).
  out = out.replace(new RegExp(`(\\{\\{)L16(\\}\\})(?:<[^>]*>|\\s)*${loose('Appearances')}`, 'g'), '$1L16W$2')
  out = out.replace(new RegExp(`(\\{\\{)L19(\\}\\})(?:<[^>]*>|\\s)*${loose('Conferences')}`, 'g'), '$1L19W$2')
  return out
}
