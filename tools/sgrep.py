#!/usr/bin/env python3
"""sgrep.py ROOT PATTERN [PATTERN...] : search printable strings (>=5) in all files, print unique hits per file."""
import os, re, sys
root, pats = sys.argv[1], [re.compile(p.encode(), re.I) for p in sys.argv[2:]]
strre = re.compile(rb'[\x20-\x7e]{5,}')
limit = int(os.environ.get('LIMIT', '40'))
walk = [(os.path.dirname(root), [], [os.path.basename(root)])] if os.path.isfile(root) else os.walk(root)
for dp, dn, fn in walk:
    for f in fn:
        p = os.path.join(dp, f)
        if os.path.islink(p): continue
        try: data = open(p, 'rb').read()
        except Exception: continue
        hits = {}
        for m in strre.finditer(data):
            s = m.group()
            for pat in pats:
                if pat.search(s):
                    hits.setdefault(s, m.start()); break
        if hits:
            print('##', os.path.relpath(p, root), len(hits))
            for s, o in list(hits.items())[:limit]:
                print('   %08x %s' % (o, s.decode()[:160]))
