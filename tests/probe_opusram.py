"""Which parts of the optional 2K Opus RAM (#2000-#27FF) does each ROM touch?

RAM is filled with a marker after power-up init, then the ROM loads a BASIC
file from an SD disk and a DD disk; bytes that changed (or were set during
init) are reported as ranges.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
sys.stdout.reconfigure(line_buffering=True)
from zxharness import ZX
from opdtool import OPD, tokenize
from run_libtest import ROMS

MARK = 0x5A


def ranges(flags):
    out, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append('#%04X-#%04X' % (0x2000 + start, 0x2000 + i - 1)); start = None
    return ' '.join(out) or '-'


def ram(zx):
    return bytes(zx.js('Array.from(zxDebug.spectrum.memory.opusRam)'))


for rom in (sys.argv[1:] or ROMS):
    boot = 'RUN' if 'v1.2' in rom else 'LOAD *"m";1;"run"'
    for fmt in ('sd', 'dd'):
        o = OPD.new(fmt, 'RAMPROBE')
        o.add_basic('run', tokenize('10 PRINT "OK"'), 10)
        with ZX(rom=rom) as zx:
            zx.frames(120)
            init = ram(zx)                       # what power-up init wrote (RAM starts zeroed)
            used_init = [b != 0 for b in init]
            # mark every byte the init did not set, then exercise the disk
            zx.js('(()=>{const r=zxDebug.spectrum.memory.opusRam; for(let i=0;i<2048;i++) if(!r[i]) r[i]=%d; return 1})()' % MARK)
            zx.insert(bytes(o.d))
            zx.basic(boot)
            zx.frames(400)
            after = ram(zx)
            used_run = [init[i] == 0 and after[i] != MARK for i in range(2048)]
            both = [a or b for a, b in zip(used_init, used_run)]
            free = 2048 - sum(both)
            print('%-50s %s  init: %s | load: %s | untouched %d bytes' % (
                rom[:50], fmt, ranges(used_init), ranges(used_run), free))
