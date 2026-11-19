#!/usr/bin/env python3
"""mkmono - build an Opus Discovery monoblock (one BASIC file = loader + code).

  mkmono.py OUT.opd --block screen.scr@16384 --block game.bin@24576 --start 32768
            [--name run] [--clear 24575] [--sp 0] [--compact] [--catalog]
            [--tiny [--step 7]] [--org 0] [--disk base.opd|.dsk] [--fmt sd|sdds|dd] [--label NAME]
OUT: .opd for SD (the standard 184320-byte image) or .dsk; DD (--fmt dd) only as .dsk.

Blocks are loaded in the given order, byte-exact: on disk each block starts
on a sector boundary, and the loader cuts its last sector to the real length,
so not a single byte after a block is written.

The loader body is moved to free UNCONTENDED memory (#8000+, outside every
block, the stack under CLEAR and --reserve areas): its NMI handler must keep
up with one byte per 32 us, which the ULA can break in #4000-#7FFF.
--org 0 keeps it in place in the REM (contended; a warning is printed).
The default name "run" makes the disk boot with RUN (or LOAD *"m";1;"run").
"""
import argparse, os, struct, subprocess, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'src')
sys.path.insert(0, HERE)
from opdtool import OPD, tokenize, basic_line

SJASM = os.environ.get('SJASMPLUS', r'C:\sjasmplus\sjasmplus.exe')


def num(x):
    return int(x, 0)


def assemble(cfg, main='mono.asm'):
    tmp = tempfile.mkdtemp(prefix='mkmono_')
    try:
        for f in ('mono.asm', 'monotiny.asm', 'opuslib.asm'):
            shutil.copy(os.path.join(SRC, f), tmp)
        open(os.path.join(tmp, 'mono_cfg.inc'), 'w').write(cfg)
        r = subprocess.run([SJASM, '--nologo', '--msg=err', '--sym=mono.sym', main], cwd=tmp,
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit('sjasmplus failed:\n' + r.stdout + r.stderr)
        sym = {}
        for l in open(os.path.join(tmp, 'mono.sym')):
            n, _, v = l.split()
            sym[n.rstrip(':')] = int(v, 16)
        return open(os.path.join(tmp, 'mono.bin'), 'rb').read(), sym
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


PROG = 23755                  # start of BASIC on a 48K with the Opus


def free_gap(busy, size, lo=0x8000, hi=0x10000):
    """Highest address A in [lo,hi) with [A, A+size) clear of every busy range."""
    edges = sorted((max(a, lo), min(b, hi)) for a, b in busy if b > lo and a < hi)
    top = hi
    for a, b in reversed([(lo, lo)] + edges):
        if b <= top and top - b >= size:
            return top - size
        top = min(top, a)
    return None


def check_blocks(blocks):
    rs = sorted((a, a + len(d)) for d, a in blocks)
    for (a1, b1), (a2, b2) in zip(rs, rs[1:]):
        if a2 < b1:
            raise SystemExit('blocks overlap: #%04X-#%04X and #%04X-#%04X' % (a1, b1 - 1, a2, b2 - 1))
    for a, b in rs:
        if a < 0x4000 or b > 0x10000:
            raise SystemExit('block #%04X-#%04X is outside RAM' % (a, b - 1))


def build(blocks, start=0, name='run', clear=None, sp=0, fast=True, catalog=False,
          org=None, tps=40, autostart=10, buf=None, tiny=False, step=7, spt=18, bps=256,
          reserve=(), warn=print):
    """blocks: list of (bytes, address). Returns (file payload incl. header, info).
    org: None = choose free uncontended memory, 0 = in place in the REM."""
    check_blocks(blocks)
    from math import gcd
    if tiny and gcd(step, spt) != 1:
        raise SystemExit('--step %d must be coprime with %d sectors/track' % (step, spt))
    spg = bps // 256
    if buf is None:   # catalog buffer: the first block's area (it gets loaded over anyway)
        d0, a0 = blocks[0]
        buf = a0 if len(d0) >= bps and a0 >= 0x4000 else 0x5B00
        if buf == 0x5B00 and bps > 256 and catalog:
            raise SystemExit('--catalog on %d-byte sectors: give --buf (a free %d-byte area)' % (bps, bps))
    table = ' : '.join('DB %d : DW %d : DW %d' % ((len(d) + bps - 1) // bps, a, len(d) % bps)
                       for d, a in blocks) + ' : DB 0'
    if clear is None:
        lo = min(a for d, a in blocks)
        clear = lo - 1 if lo > 24000 else 0
    nb, auto = 0, org is None
    if auto:
        org = 0
    for _ in range(4):
        cfg = '\n'.join([
            'LDR_ORG = %d' % org, 'MONO_FAST = %d' % fast, 'MONO_POS = %d' % catalog,
            'MONO_TPS = %d' % tps, 'MONO_SPT = %d' % spt, 'MONO_SPG = %d' % spg, 'MONO_BUF = %d' % buf, 'MONO_START = %d' % start, 'MONO_SP = %d' % sp,
            'MONO_NB = %d' % nb, '        DEFINE MONO_NAME "%s"' % name.ljust(10)[:10],
            '        DEFINE MONO_STEP %d' % step,
            '        MACRO MONO_TABLE', '        ' + table, '        ENDM', ''])
        code, sym = assemble(cfg, 'monotiny.asm' if tiny else 'mono.asm')
        line20 = ('20 ' + ('CLEAR %d: ' % clear if clear else '') +
                  'RANDOMIZE USR (PEEK 23635+256*PEEK 23636+5)')
        prog = basic_line(10, bytes([0xEA]) + code) + tokenize(line20)
        new_nb = (7 + len(prog) + bps - 1) // bps
        if auto:                          # place the body: size does not depend on org
            body = len(code) - 15         # minus the relocating stub
            ramtop = clear or 0xFF57
            busy = [(a, a + len(d)) for d, a in blocks] + list(reserve)
            busy.append((ramtop - 511, ramtop + 1))           # machine + GOSUB stack
            if not start:
                busy.append((0xFF58, 0x10000))                # UDGs, BASIC comes back
            want = free_gap(busy, body)
            auto = False
            if want is not None:
                org = want
                continue                  # assemble again at the chosen address
            warn('warning: no free uncontended memory for the %d-byte loader body - it stays in the '
                 'REM (contended #5CD0..): on real hardware the NMI handler may miss bytes' % body)
        if new_nb == nb or not catalog or tiny:
            nb = new_nb
            break
        nb = new_nb
    basic_end = PROG + len(prog) + 256    # program + vars + workspace, roughly
    if not org or not start:
        for d, a in blocks:
            if a < basic_end and a + len(d) > PROG:
                warn('warning: block #%04X-#%04X overlaps the BASIC loader (#%04X-#%04X)%s' % (
                    a, a + len(d) - 1, PROG, basic_end,
                    '' if org else ' while the loader runs in place - give --org'))
    payload = struct.pack('<BHHH', 0, len(prog), autostart, len(prog)) + prog
    payload += b'\0' * (nb * bps - len(payload))
    for d, a in blocks:
        payload += d + b'\0' * (-len(d) % bps)
    info = dict(loader_bytes=len(code), basic_len=len(prog), basic_sectors=nb,
                total_sectors=len(payload) // bps, clear=clear, sym=sym, org=org or 23760 + 15)
    return payload, info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out')
    ap.add_argument('--block', action='append', required=True, help='file@address')
    ap.add_argument('--start', type=num, default=0, help='JP address after loading (0 = back to BASIC)')
    ap.add_argument('--sp', type=num, default=0)
    ap.add_argument('--clear', type=num, default=None)
    ap.add_argument('--name', default='run')
    ap.add_argument('--org', type=num, default=None, help='where the loader body runs (default: free uncontended memory; 0 = in place in the REM)')
    ap.add_argument('--reserve', action='append', default=[], help='A-B: memory the loader must not use (hex with #/0x or decimal)')
    ap.add_argument('--compact', action='store_true', help='small sequential reader instead of the fast one')
    ap.add_argument('--catalog', action='store_true', help='find own position via the catalog')
    ap.add_argument('--tiny', action='store_true', help='minimal standalone loader (src/monotiny.asm)')
    ap.add_argument('--step', type=num, default=7, help='--tiny: physical sector step of the disk format (7 = Opus ROM format, 1 = sequential)')
    ap.add_argument('--buf', type=num, default=None, help='one-sector buffer for --catalog (default: the address of the first block, else #5B00)')
    ap.add_argument('--disk', help='add to this existing image instead of a new one')
    ap.add_argument('--fmt', default='sd', help='new image format: sd (40x1x18x256), sdds (80x2x18x256), dd (80x2x10x512)')
    ap.add_argument('--label', default='')
    a = ap.parse_args()
    blocks = []
    for b in a.block:
        f, addr = b.rsplit('@', 1)
        blocks.append((open(f, 'rb').read(), num(addr)))
    img = OPD(a.disk) if a.disk else OPD.new(a.fmt, a.label or a.name)
    reserve = []
    for r in a.reserve:
        lo, hi = r.split('-')
        reserve.append((num(lo.replace('#', '0x')), num(hi.replace('#', '0x')) + 1))
    payload, info = build(blocks, a.start, a.name, a.clear, a.sp, not a.compact, a.catalog, a.org, img.tps,
                          buf=a.buf, tiny=a.tiny, step=a.step, spt=img.spt, bps=img.bps, reserve=reserve)
    e = img.add_raw(a.name, payload)
    img.save(a.out)
    print('%s: "%s" blocks %d-%d; loader %d bytes (body runs at #%04X), BASIC %d bytes (%d sectors), '
          '%d sectors total, CLEAR %s' % (
              a.out, a.name, e['first'], e['end'], info['loader_bytes'], info['org'], info['basic_len'],
              info['basic_sectors'], info['total_sectors'], info['clear'] or '-'))


if __name__ == '__main__':
    main()
