import { describe, it, expect } from 'vitest'
// @ts-expect-error — plain ESM script module without type declarations
import { convertTemplateXml, shortTag } from '../../scripts/templateTags.mjs'

describe('template tag conversion', () => {
  it('shortens line tags and section flags', () => {
    expect(shortTag('LINE_1_DATE')).toBe('L1')
    expect(shortTag('LINE_18A_FEES_APPEARANCES')).toBe('L18A')
    expect(shortTag('#SHOW_APPEARANCES')).toBe('#IF_APP')
    expect(shortTag('/SHOW_CLIENT')).toBe('/IF_CLIENT')
    expect(shortTag('SOMETHING_ELSE')).toBe('SOMETHING_ELSE')
  })

  it('merges a tag that Word split across text runs', () => {
    const xml = '<w:t>Date: {{LINE_1</w:t></w:r><w:r><w:t>_DATE}}</w:t>'
    expect(convertTemplateXml(xml)).toBe('<w:t>Date: {{L1}}</w:t>')
  })

  it('folds the literal words into the singular/plural tags', () => {
    const xml = '<w:t>Fees for {{LINE_16_NUM_APPEARANCES}} Appearances on {{LINE_17_DATES_APPEARANCES}}.</w:t>'
    expect(convertTemplateXml(xml)).toBe('<w:t>Fees for {{L16W}} on {{L17}}.</w:t>')
    const split = '{{LINE_19_NUM_CONFERENCES}}</w:t></w:r><w:r><w:t xml:space="preserve"> Conferences on'
    expect(convertTemplateXml(split)).toBe('{{L19W}} on')
  })

  it('merges a tag whose two opening braces are in different runs', () => {
    const xml = '<w:t>{</w:t></w:r><w:proofErr w:type=\"gramEnd\"/><w:r><w:t>{/SHOW_APPEARANCES}}</w:t>'
    expect(convertTemplateXml(xml)).toBe('<w:t>{{/IF_APP}}</w:t>')
  })

  it('folds a plural word that sits in its own run after a separate space run', () => {
    const xml =
      '<w:t>Fees for {{LINE_16_NUM_APPEARANCES}}</w:t></w:r><w:r><w:t xml:space=\"preserve\"> </w:t></w:r>' +
      '<w:r><w:t>Appearance</w:t></w:r><w:r><w:t>s on {{LINE_17_DATES_APPEARANCES}}</w:t>'
    const out = convertTemplateXml(xml)
    expect(out).toContain('{{L16W}}')
    expect(out).not.toMatch(/Appearance/)
    expect(out).toContain(' on {{L17}}')
  })
})
