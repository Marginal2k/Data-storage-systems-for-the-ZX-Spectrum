"""Boot monoblock disks built by tools/mkmono.py in ZX-M8XXX and check memory.

python run_monotest.py [rom ...]       env FORMATS=sd,sdds,dd  VARIANTS=tiny,fast,compact,cat,catc,uni,unicat,unipad
uni*: --universal (one file for SD and DD); unipad: the BASIC part ends in the 1st half
of a 512-byte unit, so on SD the data start one sector later (PADU = 1).
v1.2 boots with RUN (auto "run"); later ROMs with LOAD *"m";1;"run" because the
emulator mis-handles their RUN auto-boot (see README).
"""
import os, sys, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
sys.stdout.reconfigure(line_buffering=True)
from zxharness import ZX
from opdtool import OPD
from mkmono import build
from run_libtest import ROMS

rnd = random.Random(3)
SCR = bytes(rnd.randrange(256) for _ in range(6912))
GAME = bytes(rnd.randrange(256) for _ in range(30000))
TAIL = bytes(rnd.randrange(256) for _ in range(1000))
BLOCKS = [(SCR, 16384), (GAME, 28000), (TAIL, 60000)]
# memory right after / before the blocks that must survive the load untouched
GUARDS = [(0x5B00, 0x5C00), (58000, 58600), (61000, 61600), (28000 - 16, 28000), (60000 - 16, 60000)]
GUARD_BYTES = {a: bytes((a + i * 7) & 255 ^ 0xA5 for i in range(b - a)) for a, b in GUARDS}

VARIANTS = {  # name: (fast, catalog, tiny, universal, rem bytes)
    'tiny': (0, 0, 1, 0, 0), 'fast': (1, 0, 0, 0, 0), 'compact': (0, 0, 0, 0, 0), 'cat': (1, 1, 0, 0, 0), 'catc': (0, 1, 0, 0, 0),
    'uni': (1, 0, 0, 1, 0), 'unicat': (1, 1, 0, 1, 0), 'unipad': (1, 0, 0, 1, 300)}
LAYOUTS = {
    'sd':   ['start', 'trackend', 'mid'],
    'sdds': ['side-cross', 'on-side1'],
    'dd':   ['start', 'trackend', 'mid', 'side-cross', 'on-side1'],
}


def pad(o, nblocks):
    """Occupy nblocks with ordinary CODE files (each < 64K)."""
    per = 60000 // o.bps
    i = 0
    while nblocks > 0:
        n = min(per, nblocks)
        o.add_code('pad%d' % i, bytes(n * o.bps - 7), 0x8000)
        nblocks -= n
        i += 1


def disk(variant, fmt, layout):
    fast, cat, tiny, uni, rem = VARIANTS[variant]
    o = OPD.new(fmt, 'MONO')
    payload, info = build(BLOCKS, start=0, name='run', fast=fast, catalog=cat, tiny=tiny,
                          tps=o.tps, spt=o.spt, bps=o.bps, reserve=GUARDS, warn=lambda m: None,
                          universal=bool(uni), rem=rem)
    if uni:
        assert variant != 'unipad' or info['padu'] == 1, info['padu']
        info['basic_sectors'] = info['basic_sectors'] * 512 // o.bps    # (counted in 512-byte units)
    nb, spt = info['basic_sectors'], o.spt
    if layout == 'trackend':      # BASIC part ends on the last sector of track 3 -> data starts next track
        pad(o, (4 * spt - 2) - nb + 1 - 7)
    elif layout == 'mid':
        pad(o, 100)
    elif layout == 'side-cross':  # BASIC ends just before the side boundary, data continues on side 1
        pad(o, (o.tps * spt - 1) - nb - 3 - 7)
    elif layout == 'on-side1':    # BASIC itself on side 1 (side bit comes from the PIA)
        pad(o, o.tps * spt + 20 - 7)
    e = o.add_raw('run', payload)
    return o, e, info


def check(zx):
    # bottom third of the screen gets the "0 OK" report: compare top 2/3 + their attributes
    return (zx.peek(16384, 4096) == SCR[:4096] and zx.peek(22528, 512) == SCR[6144:6656],
            zx.peek(28000, len(GAME)) == GAME, zx.peek(60000, len(TAIL)) == TAIL,
            all(zx.peek(a, b - a) == GUARD_BYTES[a] for a, b in GUARDS))


if __name__ == '__main__':
    roms = sys.argv[1:] or ROMS
    fmts = os.environ.get('FORMATS', 'sd,sdds,dd').split(',')
    variants = os.environ.get('VARIANTS', ','.join(VARIANTS)).split(',')
    fails = 0
    for rom in roms:
        boot = 'RUN' if 'v1.2' in rom else 'LOAD *"m";1;"run"'
        print('==', rom, '| boot:', boot)
        for fmt in fmts:
            for variant in variants:
                for layout in LAYOUTS[fmt]:
                    o, e, info = disk(variant, fmt, layout)
                    with ZX(rom=rom) as zx:
                        zx.frames(120)
                        zx.insert(bytes(o.d))
                        for a, g in GUARD_BYTES.items():
                            zx.poke(a, g)
                        zx.basic(boot)
                        # done when back in the editor's key wait (or an error report)
                        zx.run_until('(()=>{const pc=zxDebug.captureRegisters().pc;'
                                     'return (pc>=0x10A8&&pc<0x1110)||(pc>=0x15D4&&pc<0x1600);})()', 4000, 10)
                        zx.frames(30)
                        for _ in range(30):      # be sure the load has really finished
                            ok = check(zx)
                            if all(ok):
                                break
                            zx.frames(50)
                        good = all(ok)
                        fails += not good
                        last = zx.screen_text().strip().split('\n')[-1]
                        print('  %-4s %-10s %-7s file %4d-%4d data@%-12s loader %4d B @%04X %s %s [%s]' % (
                            fmt, layout, variant, e['first'], e['end'],
                            o.phys(e['first'] + info['basic_sectors']), info['loader_bytes'], info['org'],
                            'ok  ' if good else 'FAIL', '' if good else ok, last[-28:]))
    print('FAILURES:', fails)
    sys.exit(1 if fails else 0)
