"""Negative test for the guard check of run_monotest: declare the screen block
256 bytes longer than it is, so the load MUST spill into the #5B00 guard.
Expected output: the last flag (guards) is False."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import run_monotest as m
from zxharness import ZX

m.BLOCKS[0] = (m.SCR + bytes(256), 16384)
o, e, info = m.disk('tiny', 'dd', 'start')
with ZX(rom='Opus Discovery 1 v1.2 (1985)(Opus Supplies).rom') as zx:
    zx.frames(120)
    zx.insert(bytes(o.d))
    for a, g in m.GUARD_BYTES.items():
        zx.poke(a, g)
    zx.basic('RUN')
    zx.frames(600)
    r = m.check(zx)
    print('negative check (guards must be False):', r, 'OK' if r[-1] is False else 'CHECK IS BROKEN')
