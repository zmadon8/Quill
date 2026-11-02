"""Generates a.html, b.html, c.html and index.html for the search results mockups. Run from this folder: python3 gen.py
Results are real lines from the owner's Word file (Case Law Diary.docx)."""
import html

E = html.escape
Q1 = 'fraud arbitrable'
Q2 = '2018 9 SCC 49'
# (Subject, Topic, proposition, [citations], matched field, snippet segments [(text, hit)], needs_review, flag)
R1 = [
    ('Arbitration', 'Arbitrability', 'Mere, but not serious, allegations of fraud arbitrable',
     ['A. Ayyasamy (2016) 10 SCC 386', 'Ameet Lalchand Shah (2018) 15 SCC 678', 'Rashid Raza v. Sadaf Akhtar (2019) 8 SCC 710'],
     'Text', [('Mere, but not serious, allegations of ', 0), ('fraud', 1), (' ', 0), ('arbitrable', 1)], False, ''),
    ('Arbitration', 'Arbitrability', 'Serious issue of fraud involving criminal wrongdoing not arbitrable',
     ['N. Radhakrishnan (2010) 1 SCC 72'],
     'Text', [('Serious issue of ', 0), ('fraud', 1), (' involving criminal wrongdoing not ', 0), ('arbitrable', 1)], True, ''),
]
R2 = [
    ('Arbitration', 'Jurisdiction of Courts', 'Exclusive Jurisdiction clause must be honoured',
     ['Emkay Global (2018) 9 SCC 49', 'Indus Mobile (2017) 7 SCC 678 @ paras 2-4 & 19'],
     'Citation', [('Emkay Global (', 0), ('2018) 9 SCC 49', 1), (')', 0)], False, ''),
    ('Arbitration', 'Section 34: Appeal from Award', 'Need not look at anything that was not before the Arbitrator',
     ['Emkay Global (2018) 9 SCC 49'],
     'Citation', [('Emkay Global (', 0), ('2018) 9 SCC 49', 1), (')', 0)], True, ''),
]
BOX = '<div class="m-box"><input type="search" value="%s" aria-label="Search the diary"><button type="submit" class="primary">Search</button></div>'

def chips(items):
    return ''.join('<span class="chip">%s<button type="button" aria-label="Remove filter %s">&times;</button></span>' % (E(t), E(t)) for t in items)

def line(n, items):
    return '<div class="m-line"><strong>%d result%s</strong>%s</div>' % (n, '' if n == 1 else 's', chips(items))

def snip(seg):
    return ''.join('<mark>%s</mark>' % E(t) if h else E(t) for t, h in seg)

def pills(r):
    return ('<span class="pill rev">For review</span>' if r[6] else '') + ('<span class="pill flag">%s</span>' % E(r[7]) if r[7] else '')

def cites(r):
    return ' ; '.join('<span class="cite">%s</span>' % E(c) for c in r[3])

def empty(q):
    return '<div class="empty-box"><strong>No results for &ldquo;%s&rdquo;</strong>Try fewer words, or remove a filter. Parts of words count, and brackets and full stops are ignored.<br><a href="#">Clear all filters</a></div>' % E(q)

def layout_a(rs):
    out = '<ol class="cards">'
    for r in rs:
        out += ('<li class="card"><div class="top"><span class="badge">Item</span>%s<span class="crumbs">%s &rsaquo; %s</span></div>'
                '<h3><a href="#">%s</a></h3><div>%s</div><p class="snip"><b>Matched in %s:</b> %s</p></li>') % (
            pills(r), E(r[0]), E(r[1]), E(r[2]), cites(r), r[4].lower(), snip(r[5]))
    return out + '</ol>'

def layout_b(rs):
    groups = {}
    for r in rs:
        groups.setdefault(r[0], {}).setdefault(r[1], []).append(r)
    out = ''
    for subj, topics in groups.items():
        n = sum(len(v) for v in topics.values())
        out += '<details class="grp" open><summary>%s<span class="count">%d</span></summary><div class="sub">' % (E(subj), n)
        for topic, rows in topics.items():
            out += '<h4>%s &middot; %d</h4>' % (E(topic), len(rows))
            for r in rows:
                out += '<div class="row"><a href="#">%s</a> %s<p class="snip">%s &middot; %s</p></div>' % (E(r[2]), pills(r), cites(r), snip(r[5]))
        out += '</div></details>'
    return out

def layout_c(rs):
    items = ''
    for i, r in enumerate(rs):
        items += '<a class="item%s" href="#"><span class="t">%s</span><span class="crumbs">%s &rsaquo; %s</span></a>' % (' sel' if i == 0 else '', E(r[2]), E(r[0]), E(r[1]))
    r = rs[0]
    detail = ('<div class="detail"><div class="top"><span class="badge">Item</span> %s</div><h3>%s</h3>'
              '<dl><dt>Where</dt><dd>%s &rsaquo; %s</dd><dt>Citations</dt><dd>%s</dd><dt>Matched in</dt><dd>%s: %s</dd></dl>'
              '<p><a class="button" href="#">Open in context</a></p></div>') % (
        pills(r), E(r[2]), E(r[0]), E(r[1]), '<br>'.join('<span class="cite">%s</span>' % E(c) for c in r[3]), r[4].lower(), snip(r[5]))
    return '<div class="two"><div class="list">%s</div>%s</div>' % (items, detail)

LAYOUTS = {
    'a': ('Cards', layout_a, ['Subject: Arbitration']),
    'b': ('Grouped by Subject and Topic', layout_b, ['Subject: Arbitration']),
    'c': ('Two panes: list and detail', layout_c, ['Subject: Arbitration']),
}

def page(key):
    name, fn, base_chips = LAYOUTS[key]
    body = '<h1>Search</h1>'
    body += '<h2 class="mock-h">1. Query &ldquo;%s&rdquo; with a Subject filter</h2>' % Q1 + BOX % Q1 + line(len(R1), base_chips) + fn(R1)
    body += '<h2 class="mock-h">2. Query &ldquo;%s&rdquo; with Citations only and For review only</h2>' % Q2 + BOX % Q2 + line(len(R2), ['Citations only', 'For review only']) + fn(R2)
    body += '<h2 class="mock-h">3. Nothing found</h2>' + BOX % 'fraud arbitrable zzz' + line(0, ['Subject: Arbitration']) + empty('fraud arbitrable zzz')
    return '''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Search results, layout %s: %s</title>
<link rel="stylesheet" href="../../../../static/css/tokens.css">
<link rel="stylesheet" href="../../../../static/css/site.css">
<link rel="stylesheet" href="search-results.css">
</head><body><div class="page"><main id="main"><div class="home-column" style="max-width:56rem">%s</div></main></div></body></html>''' % (key.upper(), name, body)

for k in LAYOUTS:
    open(k + '.html', 'w').write(page(k))
ix = '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Search results mockups</title><style>body{font:17px/1.6 Georgia,serif;max-width:760px;margin:40px auto;padding:0 20px}</style></head><body><h1>Search results: three layouts</h1><p>Static mockups only; the live Search page is unchanged. Real lines from the owner&rsquo;s Word file.</p><ul>'
for k, (n, _, __) in LAYOUTS.items():
    ix += '<li><a href="%s.html">Layout %s</a>: %s</li>' % (k, k.upper(), n)
open('index.html', 'w').write(ix + '</ul><p><a href="README.md">README</a></p></body></html>')
