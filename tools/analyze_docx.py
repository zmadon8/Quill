#!/usr/bin/env python3
"""Read-only analysis of 'Case Law Diary.docx'. Never writes to the docx.

Usage: python3 tools/analyze_docx.py [path.docx] [--dump]
Prints counts per level and per Subject, and a catalogue of messy patterns.
"""
import sys, re, zipfile, collections
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
args = [a for a in sys.argv[1:] if not a.startswith('--')]
PATH = args[0] if args else 'Case Law Diary.docx'
DUMP = '--dump' in sys.argv


def load():
    z = zipfile.ZipFile(PATH)
    num = ET.fromstring(z.read('word/numbering.xml'))
    doc = ET.fromstring(z.read('word/document.xml'))
    return z, num, doc


def numbering_map(num):
    """numId -> (abstractNumId, {ilvl: (numFmt, lvlText)}) """
    absn = {}
    for a in num.findall(W + 'abstractNum'):
        lv = {}
        for l in a.findall(W + 'lvl'):
            f = l.find(W + 'numFmt'); t = l.find(W + 'lvlText')
            lv[l.get(W + 'ilvl')] = (f.get(W + 'val') if f is not None else '',
                                      t.get(W + 'val') if t is not None else '')
        absn[a.get(W + 'abstractNumId')] = lv
    out = {}
    for n in num.findall(W + 'num'):
        aid = n.find(W + 'abstractNumId').get(W + 'val')
        out[n.get(W + 'numId')] = (aid, absn.get(aid, {}))
    return out


def paragraphs(doc, nmap):
    rows = []
    for p in doc.iter(W + 'p'):
        s = p.find(W + 'pPr/' + W + 'pStyle')
        np_ = p.find(W + 'pPr/' + W + 'numPr')
        nid = il = None
        if np_ is not None:
            a = np_.find(W + 'numId'); b = np_.find(W + 'ilvl')
            nid = a.get(W + 'val') if a is not None else None
            il = b.get(W + 'val') if b is not None else '0'
        text = ''.join(t.text or '' for t in p.iter(W + 't'))
        fmt = txt = ''
        aid = ''
        if nid in nmap:
            aid, lv = nmap[nid]
            fmt, txt = lv.get(il or '0', ('', ''))
        rows.append(dict(style=s.get(W + 'val') if s is not None else 'Normal',
                         numId=nid, ilvl=il, abs=aid, fmt=fmt, lvlText=txt, text=text))
    return rows


def classify(r):
    """Level from style + list format (not from ilvl)."""
    if r['text'].strip() == '':
        return 'empty'
    if r['style'] == 'Heading1':
        return 'subject'
    if r['style'] == 'Heading2':
        return 'topic'
    f = r['fmt']
    if f == 'decimal':
        return 'subtopic'
    if f in ('lowerRoman', 'upperRoman'):
        return 'item'
    if f == 'bullet':
        return 'bullet'
    return 'unclassified'


def main():
    z, num, doc = load()
    nmap = numbering_map(num)
    rows = paragraphs(doc, nmap)
    for r in rows:
        r['level'] = classify(r)
    if DUMP:
        for i, r in enumerate(rows):
            print(i, r['style'], r['numId'], r['ilvl'], r['abs'], r['fmt'], repr(r['lvlText']), r['text'], sep='\t')
        return
    print('Package parts with notes:', [n for n in z.namelist() if 'footnote' in n or 'endnote' in n])
    fn = ET.fromstring(z.read('word/footnotes.xml'))
    real_fn = [f for f in fn.findall(W + 'footnote') if f.get(W + 'type') in (None, 'normal')]
    print('Real footnotes defined:', len(real_fn),
          '| footnote references in body:', len(list(doc.iter(W + 'footnoteReference'))))
    print('Tables:', len(list(doc.iter(W + 'tbl'))), '| Images:', len(list(doc.iter(W + 'drawing'))) + len(list(doc.iter(W + 'pict'))))
    print('Paragraphs:', len(rows))
    print('Styles:', dict(collections.Counter(r['style'] for r in rows)))
    print('ilvl values on numbered paragraphs:', dict(collections.Counter(r['ilvl'] for r in rows if r['numId'])))
    print('Paragraphs without numPr:', sum(1 for r in rows if not r['numId']))
    print()
    print('== numFmt/lvlText by role (style, fmt, lvlText) -> count, distinct numIds, distinct abstractNums')
    g = collections.defaultdict(lambda: [0, set(), set()])
    for r in rows:
        k = (r['style'], r['fmt'], r['lvlText'], r['level'])
        g[k][0] += 1; g[k][1].add(r['numId']); g[k][2].add(r['abs'])
    for k, v in sorted(g.items(), key=lambda kv: -kv[1][0]):
        print(k, v[0], 'numIds:', len(v[1]), 'abstractNums:', len(v[2]))
    print()
    print('== Overall level counts')
    print(dict(collections.Counter(r['level'] for r in rows)))

    # walk the structure
    subjects = []  # dicts
    cur = None; topic = None
    for i, r in enumerate(rows):
        lv = r['level']
        if lv == 'subject':
            cur = dict(name=r['text'].strip(), misc=r['text'].strip().lower() == 'miscellaneous', topics=[], c=collections.Counter(), pre=[])
            subjects.append(cur); topic = None
            continue
        if cur is None:
            continue
        if lv == 'topic':
            topic = dict(name=r['text'].strip(), c=collections.Counter())
            cur['topics'].append(topic); cur['c']['topic'] += 1
            continue
        cur['c'][lv] += 1
        if topic: topic['c'][lv] += 1
        else: cur['pre'].append(r['text'])
    print()
    print('== Per Heading 1 (as in document)')
    cols = ['topic', 'subtopic', 'item', 'bullet', 'unclassified', 'empty']
    print('Subject'.ljust(40), *[c[:8].rjust(8) for c in cols])
    for s in subjects:
        print(s['name'][:39].ljust(40), *[str(s['c'][c]).rjust(8) for c in cols])
    print('Total'.ljust(40), *[str(sum(s['c'][c] for s in subjects)).rjust(8) for c in cols])
    normal = [s for s in subjects if not s['misc']]
    misc = [s for s in subjects if s['misc']]
    other = [t for s in misc for t in s['topics']]
    print()
    print('Heading 1 total:', len(subjects), '| excluding Miscellaneous:', len(normal))
    print('Miscellaneous Topics (become Other Subjects):', len(other))
    print('REAL SUBJECT COUNT =', len(normal), '+', len(other), '=', len(normal) + len(other))
    print('Content directly under Miscellaneous before first Topic:', sum(len(s['pre']) for s in misc))
    print()
    print('== Other Subjects (Miscellaneous topics)')
    print('Name'.ljust(50), *[c[:8].rjust(8) for c in cols[1:]])
    for t in other:
        print(t['name'][:49].ljust(50), *[str(t['c'][c]).rjust(8) for c in cols[1:]])
    # numId usage
    print()
    print('== List usage')
    use = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        if r['numId'] and r['level'] in ('subtopic', 'item', 'bullet', 'unclassified'):
            use[(r['abs'], r['fmt'], r['lvlText'])][r['numId']] += 1
    for k, v in sorted(use.items(), key=lambda kv: -sum(kv[1].values())):
        pass
    summ = collections.defaultdict(lambda: [0, 0])
    for (aid, fmt, txt), v in use.items():
        summ[(fmt, txt)][0] += len(v); summ[(fmt, txt)][1] += sum(v.values())
    for k, v in summ.items():
        print(k, 'distinct lists:', v[0], 'paragraphs:', v[1])
    sizes = collections.Counter()
    for (aid, fmt, txt), v in use.items():
        for n, c in v.items():
            sizes[(fmt, c)] += 1
    print('List length distribution (fmt, items in list) -> number of lists, first rows:')
    for k in sorted(sizes)[:0]: pass

    # Pattern catalogue on content lines (items/bullets/unclassified/subtopic)
    content = [r for r in rows if r['level'] in ('item', 'bullet', 'unclassified')]
    print()
    print('Content lines (items+bullets+unclassified):', len(content))
    pats = collections.OrderedDict()
    def add(name, cond, src=None):
        hits = [r['text'] for r in (src or content) if cond(r['text'])]
        pats[name] = hits
    def unbalanced(t):
        return t.count('[') != t.count(']') or t.count('(') != t.count(')')
    add('Multiple inline citations marked (i)/(ii) in one line', lambda t: bool(re.search(r'\(i\)', t)) and bool(re.search(r'\(ii\)', t)))
    add('Unbalanced brackets/parentheses', unbalanced)
    add('Two or more " - " in one line', lambda t: t.count(' - ') >= 2)
    add('No " - " at all', lambda t: ' - ' not in t)
    add('Whole line in square brackets', lambda t: t.strip().startswith('[') and t.strip().endswith(']'))
    add('Contains [NO LONGER GOOD LAW]', lambda t: 'NO LONGER GOOD LAW' in t.upper())
    add('Other ALL-CAPS bracket flags', lambda t: bool(re.search(r'\[[A-Z][A-Z \-:\.]{5,}\]', t)) and 'NO LONGER GOOD LAW' not in t.upper())
    add('Ends with colon', lambda t: t.rstrip().endswith(':'))
    add('Contains semicolon separating citations', lambda t: ' ; ' in t or '; ' in t)
    add('Curly quotes', lambda t: bool(re.search('[\u2018\u2019\u201c\u201d]', t)))
    add('Straight quotes', lambda t: "'" in t or '"' in t)
    add('Ampersand', lambda t: '&' in t)
    add('Leading/trailing spaces', lambda t: t != t.strip())
    add('Double spaces', lambda t: '  ' in t)
    add('Non-breaking space or tab', lambda t: '\u00a0' in t or '\t' in t)
    add('Has a [citation] with SCC', lambda t: 'SCC' in t)
    add('Has no citation brackets at all', lambda t: '[' not in t)
    add('Very long (>400 chars)', lambda t: len(t) > 400)
    add('Very short (<12 chars)', lambda t: len(t.strip()) < 12)
    print()
    print('== Pattern catalogue (count, up to 3 verbatim examples)')
    for k, h in pats.items():
        print(f'\n[{k}] count={len(h)}')
        for e in h[:3]:
            print('   >', e[:300])
    # Sub-topics too
    st = [r for r in rows if r['level'] == 'subtopic']
    print('\nSub-topic names (distinct):', len(set(r['text'].strip() for r in st)), 'of', len(st))
    print('Sub-topics ending with colon:', sum(1 for r in st if r['text'].strip().endswith(':')))
    print('Sub-topics containing " - ":', sum(1 for r in st if ' - ' in r['text']))
    print('Topics with a numbering list attached (Heading2 numPr):', sum(1 for r in rows if r['level'] == 'topic' and r['numId']))
    print('Subjects with numPr:', sum(1 for r in rows if r['level'] == 'subject' and r['numId']))
    print('Topics without any sub-topic or item (empty topics):', sum(1 for s in subjects for t in s['topics'] if not (t['c']['subtopic'] or t['c']['item'] or t['c']['bullet'] or t['c']['unclassified'])))
    print('Topics with items directly (no sub-topic):', sum(1 for s in subjects for t in s['topics'] if t['c']['item'] and not t['c']['subtopic']))
    print('Topics with sub-topics:', sum(1 for s in subjects for t in s['topics'] if t['c']['subtopic']))

    # ---- structure checks and proposed import rules
    print()
    print('== Structure checks')
    sub_without_items = 0; two_item_lists_in_row = 0
    seen_sub = False; prev = None; prev_item_num = None
    for i, r in enumerate(rows):
        lv = r['level']
        if lv == 'topic':
            seen_sub = False; prev = None; prev_item_num = None; continue
        if lv == 'subtopic':
            if prev == 'subtopic': sub_without_items += 1
            seen_sub = True; prev_item_num = None
        elif lv == 'item':
            if seen_sub and prev_item_num is not None and r['numId'] != prev_item_num:
                two_item_lists_in_row += 1
            prev_item_num = r['numId']
        if lv in ('subtopic', 'item', 'unclassified'): prev = lv
    print('Sub-topics immediately followed by another sub-topic (no items):', sub_without_items)
    for i, r in enumerate(rows):
        pass
    print('Item list switching numId inside one sub-topic or topic (possible split list):', two_item_lists_in_row)
    # items sitting before the first sub-topic in a topic that also has sub-topics
    first_item_before_sub = 0
    seq = []
    for r in rows:
        if r['level'] == 'topic':
            if seq and 'subtopic' in seq and seq.index('item') < seq.index('subtopic') if ('item' in seq and 'subtopic' in seq) else False:
                first_item_before_sub += 1
            seq = []
        elif r['level'] in ('item', 'subtopic'):
            seq.append(r['level'])
    if 'item' in seq and 'subtopic' in seq and seq.index('item') < seq.index('subtopic'):
        first_item_before_sub += 1
    print('Topics where plain items appear BEFORE the first sub-topic:', first_item_before_sub)
    print('Topics ending with a colon:', sum(1 for r in rows if r['level'] == 'topic' and r['text'].strip().endswith(':')))
    tn = collections.Counter()
    cs = None
    for r in rows:
        if r['level'] == 'subject': cs = r['text'].strip()
        if r['level'] == 'topic': tn[(cs, r['text'].strip())] += 1
    print('Duplicate Topic names inside one Heading 1:', [k for k, v in tn.items() if v > 1])
    print('Empty paragraphs (position: previous text):')
    for i, r in enumerate(rows):
        if r['level'] == 'empty':
            print('  ', i, 'after', repr(rows[i-1]['text'][:50]) if i else None)
    print('Unclassified (list is (a),(b) letters) lines:')
    for i, r in enumerate(rows):
        if r['level'] == 'unclassified':
            print('  ', i, r['text'][:160])
    print('Topic names that are also Heading 1 names or duplicated among Other Subjects:',
          [k for k, v in collections.Counter(t['name'] for s in misc for t in s['topics']).items() if v > 1])

    # ---- Proposed deterministic split of Text / Citation
    def split_rule(t):
        """Return ('split', text, cit) or ('whole', reason)."""
        if t != t.strip(): return ('whole', 'leading or trailing spaces')
        if t.count('[') != t.count(']') or t.count('(') != t.count(')'):
            return ('whole', 'unbalanced brackets')
        if t.strip().startswith('[') and t.strip().endswith(']'):
            return ('whole', 'whole line in brackets')
        if re.search(r'\(ii\)', t):
            return ('whole', 'several citations marked (i), (ii)')
        if ' - ' not in t: return ('whole', 'no " - " separator')
        if t.count(' - ') > 1: return ('whole', 'more than one " - "')
        a, b = t.split(' - ')
        if not a.strip() or not b.strip(): return ('whole', 'empty side')
        if re.search(r'NO LONGER GOOD LAW', t, re.I): return ('whole', 'carries a flag')
        if '[' not in b and not re.search(r'\d{4}\)? ?\d* ?[A-Za-z]', b): return ('whole', 'right side does not look like a citation')
        if '  ' in t: return ('whole', 'double spaces')
        return ('split', a, b)
    res = collections.Counter(); why = collections.Counter(); ex = {}
    for r in content:
        out = split_rule(r['text'])
        res[out[0]] += 1
        if out[0] == 'whole':
            why[out[1]] += 1; ex.setdefault(out[1], r['text'])
    print()
    print('== Proposed rule result on', len(content), 'item lines:', dict(res))
    for k, v in why.most_common():
        print('  whole-line because', k, ':', v, '| e.g.', ex[k][:160])
    # lines that would trigger needs_review at all (any reason except plain "no separator" short titles)
    nr = sum(1 for r in content if split_rule(r['text'])[0] == 'whole')
    print('Item lines imported whole (needs_review=Yes):', nr, 'of', len(content))
    print('Sub-topic lines needing review (contain " - " or end with colon or unbalanced):',
          sum(1 for r in rows if r['level'] == 'subtopic' and (' - ' in r['text'] or r['text'].strip().endswith(':') or r['text'].count('[') != r['text'].count(']'))))
    print('Total paragraph count of text to rebuild:', sum(1 for r in rows if r['level'] != 'empty'))

if __name__ == '__main__':
    main()
