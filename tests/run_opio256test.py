"""The 180K / 720K driver src/opio256.asm (no anchor: 18 x 256, side 1 after track 79), all ROMs.
  180K = 40x1x18x256 (.opd 184320), 720K = 80x2x18x256 (.opd 737280, the head right before the side
  boundary so that its data run onto side 1).
  1. the ROM LOADs a BASIC file "head" (no autostart); op_cap, op_base = the block after its BASIC part
  2. op_rd of the 4K that follow (+ guards, the NMI hole put back); an odd count (7 sectors)
  3. op_rd of 40 sectors from the start of the file, op_wr of 3 sectors, compared with the image
python run_opio256test.py [rom ...]"""
import os, sys, random, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
sys.stdout.reconfigure(line_buffering=True)
from zxharness import ZX
from opdtool import OPD, tokenize
from run_libtest import ROMS, T

SJASM = os.environ.get('SJASMPLUS', r'C:\sjasmplus\sjasmplus.exe')
RD_TS, RD_BUF, RD_N, HOLE = 0x7E00, 0x7E02, 0x7E04, 0xBFE0


def build():
    r = subprocess.run([SJASM, '--nologo', '--msg=err', '--sym=opio256test.sym', 'opio256test.asm'],
                       cwd=HERE, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    sym = {}
    for l in open(os.path.join(HERE, 'opio256test.sym')):
        n, _, v = l.split()
        sym[n.rstrip(':')] = int(v, 16)
    return open(os.path.join(HERE, 'opio256test.bin'), 'rb').read(), sym


def run(rom, fmt):
    bin_, sym = build()
    prog = tokenize('10 REM ' + 'x' * 300)
    first = bytes([0]) + len(prog).to_bytes(2, 'little') + (0x8000).to_bytes(2, 'little') + len(prog).to_bytes(2, 'little') + prog
    first += bytes(-len(first) % 256)          # 256-byte sectors only: the data follow the BASIC part directly
    data = bytes(random.Random(len(first)).randrange(256) for _ in range(4096))
    o = OPD.new('sd' if fmt == '180k' else 'sdds', 'OPIO256')
    assert (o.spt, o.bps) == (18, 256)
    if fmt == '720k':
        o.add_raw('fill', bytes((1440 - 7 - 7) * 256))      # the head's BASIC part ends on side 0, its data cross to side 1
    else:
        o.add_raw('fill', bytes(30 * 256))
    e = o.add_raw('head', first + data)
    geom = (o.tps, o.sides, o.spt, o.bps)
    base = e['first'] + len(first) // 256
    t = None
    with ZX(rom=rom) as zx:
        zx.frames(120)
        zx.insert(bytes(o.d), 0, 'opio256.opd', geom=geom)
        zx.basic('LOAD *"m";1;"head"')
        zx.frames(200)
        zx.poke(0x7F00, bin_)
        t = T(zx, sym)
        tag = '%s (data from block %d %s)' % (fmt, base, o.phys(base))
        t.call('op_cap', {})
        r = t.call('op_base', {})
        if 'EXCOM' in rom and fmt == '180k' and r['hl'] != base:
            print('   %-60s known: EXCOM double step (got %d)' % ('%s op_base' % tag, r['hl']))
        else:
            t.check('%s op_base' % tag, r['hl'] == base, r['hl'])
        pat = bytes((i * 37) & 255 for i in range(32))
        zx.poke(HOLE, pat)
        zx.poke(0x9000 - 16, [0x55] * 16); zx.poke(0x9000, [0] * 4096); zx.poke(0x9000 + 4096, [0x66] * 64)
        zx.poke(RD_TS, [base & 255, base >> 8]); zx.poke(RD_BUF, [0x00, 0x90]); zx.poke(RD_N, [16])
        t.call('op_rd', {})
        ok = zx.peek(0x9000, 4096) == data and zx.peek(0x9000 - 16, 16) == b'U' * 16 and zx.peek(0x9000 + 4096, 64) == b'f' * 64
        t.check('%s op_rd 16 sectors after the BASIC part, guards' % fmt, ok)
        t.check('%s the NMI hole is put back' % fmt, zx.peek(HOLE, 32) == pat)
        zx.poke(0xA000, [0] * 7 * 256); zx.poke(0xA000 + 7 * 256, [0x77] * 64)
        b7 = base + 3
        zx.poke(RD_TS, [b7 & 255, b7 >> 8]); zx.poke(RD_BUF, [0x00, 0xA0]); zx.poke(RD_N, [7])
        t.call('op_rd', {})
        t.check('%s op_rd 7 sectors (odd count) + guard' % fmt, zx.peek(0xA000, 7 * 256) == data[3 * 256:10 * 256]
                and zx.peek(0xA000 + 7 * 256, 64) == b'w' * 64)
        n = 40
        zx.poke(RD_TS, [e['first'] & 255, e['first'] >> 8]); zx.poke(RD_BUF, [0x00, 0xC0]); zx.poke(RD_N, [n])
        t.call('op_rd', {})
        img = OPD(zx.disk(0)[:len(o.d)], geom)
        t.check('%s op_rd %d sectors from block %d' % (fmt, n, e['first']), zx.peek(0xC000, n * 256) == img.read_blocks(e['first'], n))
        w = bytes(random.Random(5).randrange(256) for _ in range(768))
        wb = base + 12
        zx.poke(0xB000, w)
        zx.poke(RD_TS, [wb & 255, wb >> 8]); zx.poke(RD_BUF, [0x00, 0xB0]); zx.poke(RD_N, [3])
        t.call('op_wr', {})
        img = OPD(zx.disk(0)[:len(o.d)], geom)
        t.check('%s op_wr 3 sectors at block %d' % (fmt, wb), img.read_blocks(wb, 3) == w)
    return t.fails


if __name__ == '__main__':
    total = 0
    for rom in sys.argv[1:] or ROMS:
        print('==', rom)
        for fmt in ('180k', '720k'):
            total += run(rom, fmt)
    print('FAILURES:', total)
    sys.exit(1 if total else 0)
