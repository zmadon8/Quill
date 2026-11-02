import os
PEN='<svg class="pen" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20l1-5L16 4l4 4L9 19z"/><path d="M14 6l4 4"/></svg>'
def ctl(opt,on,ctx):
    up=' up' if ctx=='index' else ''
    if opt=='a':
        return ('<button type="button" class="a-pill" title="Finish editing">%s<span>Editing</span><span class="dot">&middot;</span><span>Done</span></button>'%PEN) if on else '<button type="button" class="a-edit" title="Edit this page">%s<span>Edit</span></button>'%PEN
    if opt=='b':
        r,e=('false','true') if on else ('true','false')
        return '<div class="seg%s" role="group" aria-label="Mode"><button type="button" aria-pressed="%s">Read</button><button type="button" aria-pressed="%s">%s<span>Edit</span></button></div>'%(' on' if on else '',r,e,PEN)
    if opt=='c':
        return '<button type="button" class="c-edit" %s>%s<span>%s</span></button>'%('disabled' if on else '',PEN,'Editing this page' if on else 'Edit page')
    if opt=='d':
        return ('<button type="button" class="fab on" title="Done"><svg class="pen" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg><span>Done</span></button>' if on else '<button type="button" class="fab" title="Edit this page" aria-label="Edit this page">%s</button>'%PEN.replace('width="18" height="18"','width="26" height="26"'))
    if opt=='e':
        if on: return '<span class="e-wrap"><span class="e-badge">Editing</span><button type="button" class="e-icon on" aria-label="Finish editing" title="Done">%s</button></span>'%PEN
        return '<span class="e-wrap"><button type="button" class="e-icon" aria-label="Edit this page">%s</button><span class="tip%s">Edit this page</span></span>'%(PEN,up)
def banner(opt,on):
    if opt=='c' and on:
        return '<div class="edit-banner"><b>Editing</b><span>&middot;</span><button type="button">Undo</button><span>&middot;</span><button type="button" class="solid">Done</button></div>'
    return ''
ROWS=[('Arbitration','12 items'),('Contract','31 items'),('Evidence','8 items'),('Insolvency','19 items'),('Tort','27 items'),('Trusts','14 items')]
def page(opt,ctx,on):
    ban=banner(opt,on)
    bar=ctl(opt,on,ctx) if ctx=='reading' else ''
    if opt=='d': bar=''
    crumb=('<a href="#">Home</a><span class="sep">&rsaquo;</span><a href="#">Arbitration</a><span class="sep">&rsaquo;</span><span aria-current="page">Fraud</span>' if ctx=='reading' else '<span aria-current="page">Home</span>')
    if ctx=='reading':
        body='<h1>Fraud</h1>'+''.join('<div class="fake-row">(%d) Fraud vitiates arbitrability only if it goes to the agreement itself<small><i>Example v Sample</i> [2020] EWCA Civ %d</small></div>'%(i,100+i*7) for i in range(1,5))
    else:
        body='<h1>Index of Subjects</h1>'+''.join('<div class="fake-row">%s<small>%s</small></div>'%r for r in ROWS)
        body+='<div class="edit-foot">%s</div>'%(ctl(opt,on,ctx) if opt!='d' else '')
    fl=ctl('d',on,ctx) if opt=='d' else ''
    return '''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Option %s, %s, edit %s</title>
<link rel="stylesheet" href="../../../../static/css/tokens.css">
<link rel="stylesheet" href="../../../../static/css/site.css">
<link rel="stylesheet" href="../edit-button.css">
</head><body class="%s">
%s<div class="page">
<div class="crumb-row"><nav class="breadcrumb" aria-label="You are here">%s</nav><div class="bar-tools" style="margin-left:auto;display:flex;align-items:center;gap:.5rem">%s</div></div>
<main id="main"><div class="reading" style="max-width:46rem">%s</div></main>
</div>%s</body></html>'''%(opt.upper(),ctx,'on' if on else 'off','has-banner' if ban else '',ban,crumb,bar,body,fl)
for o in 'abcde':
    for c in ('reading','index'):
        for on in (False,True):
            open('pages/%s-%s-%s.html'%(o,c,'on' if on else 'off'),'w').write(page(o,c,on))
TITLES={'a':'Quiet link, then oxblood pill','b':'Segmented control Read | Edit','c':'Outlined button plus top banner','d':'Floating pencil button','e':'Icon only with tooltip and badge'}
for o in 'abcde':
    h='<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Option %s</title><style>body{font:16px/1.5 Georgia,serif;margin:20px;background:#f8f6f1;color:#1e1c19}h2{font-weight:400}.g{display:grid;grid-template-columns:1fr 1fr;gap:16px}iframe{width:100%%;height:360px;border:1px solid #d9d3c5;background:#fff}.p{width:390px;height:560px}</style></head><body><p><a href="index.html">All options</a></p><h1>Option %s: %s</h1>'%(o.upper(),o.upper(),TITLES[o])
    for c,name in (('reading','Reading page, sticky bar'),('index','Bottom of Index of Subjects')):
        h+='<h2>%s</h2><div class="g">'%name
        for on in ('off','on'):
            h+='<div><b>Edit %s</b><br><iframe src="pages/%s-%s-%s.html"></iframe></div>'%(on,o,c,on)
        h+='</div><div class="g">'
        for on in ('off','on'):
            h+='<div><b>Phone, edit %s</b><br><iframe class="p" src="pages/%s-%s-%s.html"></iframe></div>'%(on,o,c,on)
        h+='</div>'
    open(o+'.html','w').write(h+'</body></html>')
ix='<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Edit button mockups</title><style>body{font:17px/1.6 Georgia,serif;max-width:760px;margin:40px auto;padding:0 20px}</style></head><body><h1>Edit button: five options</h1><p>Static mockups only; the live app is unchanged. Each page shows reading page and Index of Subjects bottom, Edit off and on, desktop and phone.</p><ul>'
for o in 'abcde': ix+='<li><a href="%s.html">Option %s</a>: %s</li>'%(o,o.upper(),TITLES[o])
open('index.html','w').write(ix+'</ul><p><a href="README.md">README</a></p></body></html>')
