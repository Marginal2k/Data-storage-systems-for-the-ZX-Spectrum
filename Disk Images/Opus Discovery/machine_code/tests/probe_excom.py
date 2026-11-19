import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
sys.stdout.reconfigure(line_buffering=True)
from zxharness import ZX
from opdtool import OPD, tokenize
rom = 'Opus Discovery EXCOM v2.28 Paul Cheffing (19xx)(Opus).rom'
for fmt, pads in (('sd', [0, 1, 10, 40, 60, 62, 100]), ('dd', [0, 30, 100])):
    for n in pads:
        o = OPD.new(fmt, 'X')
        if n: o.add_code('pad0', bytes(n * o.bps - 7), 0x8000)
        o.add_basic('run', tokenize('10 PRINT "LOADED"'), 10)
        with ZX(rom=rom) as zx:
            zx.frames(120); zx.insert(bytes(o.d))
            zx.basic('LOAD *"m";1;"run"'); zx.frames(300)
            last = zx.screen_text().strip().split('\n')[-1]
            print(fmt, 'pad blocks', n, '->', last)
