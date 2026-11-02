"""Generates a.html to e.html for the Export button mockups. Run from this folder: python3 gen.py"""
DL = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 11l5 5 5-5M5 20h14"/></svg>'
DOC = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h8l5 5v13H6zM14 3v5h5M9 13h7M9 17h7"/></svg>'
CARET = '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
ARROW = '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M6 1.5v8M2.5 6.5L6 10l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
CONTENTS = '<button type="button" class="contents-button contents-icon" aria-label="Contents" title="Contents"><svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><g fill="currentColor"><circle cx="5" cy="6" r="1.6"/><circle cx="5" cy="12" r="1.6"/><circle cx="5" cy="18" r="1.6"/></g><path d="M10 6h10M10 12h10M10 18h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>'
HEAD_ICONS = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M15 15l5.5 5.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'
HOME = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M3 11.5L12 4l9 7.5M5.5 10v10h13V10M10 20v-6h4v6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
BACK = '<svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true"><path d="M14 8H2M7 3L2 8l5 5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
FWD = '<svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true"><path d="M2 8h12M9 3l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'

OPTS = {
    'a': ('Text "Export"', '<a class="button export-link a-export" href="#" title="Download what is on this page as a Word file">Export</a>', ''),
    'b': ('Download arrow, icon only', '<span class="exp-wrap"><a class="button export-link b-export" href="#" aria-label="Export" title="Export">%s</a><span class="tip">Export</span></span>' % DL, ''),
    'c': ('"Export" with a down arrow', '<a class="button export-link c-export" href="#" title="Download what is on this page as a Word file">Export ' + ARROW + '</a>', ''),
    'd': ('"Save as Word" with a document icon', '<a class="button export-link d-export" href="#" aria-label="Save as Word" title="Save as Word">%s<span class="long">Save as Word</span></a>' % DOC, ''),
    'e': ('Split button "Export" with a menu', '<span class="exp-wrap"><span class="split"><a class="button export-link main" href="#" title="Export this page">Export</a><button type="button" class="more" aria-haspopup="menu" aria-expanded="true" aria-label="More export choices">' + CARET + '</button></span><span class="menu" role="menu"><a role="menuitem" href="#">This page<small>Fraud</small></a><a role="menuitem" href="#">Full diary<small>one file</small></a><a role="menuitem" href="#">By Subject<small>.zip</small></a></span></span>', ''),
}

def page(key):
    title, ctl, _ = OPTS[key]
    rows = ''.join('<div class="fake-row">(%d) Fraud vitiates arbitrability only if it goes to the agreement itself<small><i>Example v Sample</i> [2020] EWCA Civ %d</small></div>' % (i, 100 + i * 7) for i in range(1, 5))
    return '''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Export option %s</title>
<link rel="stylesheet" href="../../../../static/css/tokens.css">
<link rel="stylesheet" href="../../../../static/css/site.css">
<link rel="stylesheet" href="export-button.css">
</head><body><div class="page">
<header class="site-header"><div class="brand-row"><span class="brand"><a href="#">Case Law Diary</a></span><span class="history-buttons"><button type="button" class="back-button" aria-label="Back">%s</button><button type="button" class="forward-button" aria-label="Forward">%s</button></span></div>
<nav class="program-nav" aria-label="Main"><a href="#">Review</a><a href="#">Export</a><a href="#">Help</a><button type="button" class="icon-tool" aria-label="Search">%s</button><a class="home-button" href="#" aria-label="Home">%s</a></nav></header>
<div class="crumb-row"><nav class="breadcrumb" aria-label="You are here"><a href="#">Home</a><span class="sep">&rsaquo;</span><a href="#">Arbitration</a><span class="sep">&rsaquo;</span><span aria-current="page">Fraud</span></nav>
<div style="margin-left:auto;display:flex;align-items:center;gap:.5rem"><button type="button" class="mock-edit">Edit</button>%s%s</div></div>
<main id="main"><div class="reading" style="max-width:46rem"><h1>Fraud</h1>%s</div></main>
</div></body></html>''' % (key.upper(), BACK, FWD, HEAD_ICONS, HOME, ctl, CONTENTS, rows)

for k in OPTS:
    open(k + '.html', 'w').write(page(k))
ix = '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Export button mockups</title><style>body{font:17px/1.6 Georgia,serif;max-width:760px;margin:40px auto;padding:0 20px}</style></head><body><h1>Export button: five options</h1><p>Static mockups only; the live app is unchanged (it now uses option A).</p><ul>'
for k, (t, _, __) in OPTS.items():
    ix += '<li><a href="%s.html">Option %s</a>: %s</li>' % (k, k.upper(), t)
open('index.html', 'w').write(ix + '</ul><p><a href="README.md">README</a></p></body></html>')
