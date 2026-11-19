"""Functional tests of src/opuslib.asm in ZX-M8XXX (headless).

python run_libtest.py [rom ...]     (default: all Opus ROMs)
Each ROM is tested with OD_FAST=1 and OD_FAST=0 builds.
"""
import os, sys, subprocess, random, struct
sys.stdout.reconfigure(line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
from zxharness import ZX
from opdtool import OPD

ROMS = ['Opus Discovery 1 v1.2 (1985)(Opus Supplies).rom',
        'Opus Discovery 1 v2.2 (1985)(Opus Supplies).rom',
        'Opus Discovery 1 v2.22 (1985)(Opus Supplies).rom',
        'Opus Discovery EXCOM v2.28 Paul Cheffing (19xx)(Opus).rom',
        'Opus Discovery QuickDOS v2.31 (19xx)(Opus).rom']


def build(fast):
    for attempt in range(4):        # Windows may hold the output file for a moment
        if subprocess.run(['sh', os.path.join(HERE, 'build.sh'), str(fast)], stdout=subprocess.DEVNULL).returncode == 0:
            break
        import time; time.sleep(1)
    else:
        raise RuntimeError('build.sh %d failed' % fast)
    sym = {}
    for l in open(os.path.join(HERE, 'libtest.sym')):
        n, _, v = l.split()
        sym[n.rstrip(':')] = int(v, 16)
    return open(os.path.join(HERE, 'libtest.bin'), 'rb').read(), sym


def make_disks():
    rnd = random.Random(1)
    ss = OPD.new(False, 'TESTSS')
    files = {}
    for name, size in [('small', 100), ('one', 249), ('two', 250), ('big', 9000), ('bigger', 30000), ('slot', 2000)]:
        data = bytes(rnd.randrange(256) for _ in range(size))
        files[name] = data
        ss.add_code(name, data, 0x8000)
    ds = OPD.new(True, 'TESTDS')
    # fill side 0 with a filler so that 'cross' spans the side boundary (block 1439)
    ds.add_raw('filler', bytes(rnd.randrange(256) for _ in range((1439 - 7 - 10) * 256)))
    dsfiles = {'cross': bytes(rnd.randrange(256) for _ in range(20 * 256))}
    e = ds.add_code('cross', dsfiles['cross'], 0x9000)
    assert e['first'] < 1439 < e['end'], e
    return ss, files, ds, dsfiles


class T:
    def __init__(self, zx, sym):
        self.zx, self.sym, self.fails = zx, sym, 0

    def call(self, name, regs, frames=4000):
        zx, s = self.zx, self.sym
        zx.poke(s['res_flag'], [0])
        sp = 0x7DF0
        zx.poke(sp, [s['done'] & 255, s['done'] >> 8])
        r = dict(regs); r.update(pc=s[name], sp=sp)
        zx.js('window.zxDebug.setRegisters(%s), true' % str(r).replace("'", '"'))
        n = zx.run_until('window.zxDebug.peek(%d)===0xAA' % s['res_flag'], frames, 5)
        if n is None:
            raise RuntimeError('%s did not return, pc=%04x' % (name, zx.regs()['pc']))
        b = zx.peek(s['res_af'], 8)
        af, hl, de, bc = struct.unpack('<HHHH', b)
        return dict(a=af >> 8, cy=af & 1, hl=hl, de=de, bc=bc, frames=n)

    def check(self, what, ok, extra=''):
        print('   %-48s %s %s' % (what, 'ok' if ok else 'FAIL', extra))
        if not ok: self.fails += 1


def run(rom, fast, oram=True):
    bin_, sym = build(fast)
    ss, files, ds, dsfiles = make_disks()
    with ZX(rom=rom, opus_ram=oram) as zx:
        zx.frames(120)
        zx.insert(bytes(ss.d), 0, 'ss.opd')
        zx.poke(0x6000, bin_)
        t = T(zx, sym)
        r = t.call('od_read', dict(hl=0, bc=1 << 8, de=0x9000))
        st = zx.peek(sym['od_ram'], 1)[0], int.from_bytes(zx.peek(sym['od_buf'], 2), 'little'), \
            int.from_bytes(zx.peek(sym['od_hrd'], 2), 'little')
        want = (1, 0x2200, 0x2100) if oram else (0, 0x7800, sym['od_nmird'])
        t.check('Opus RAM %s: od_ram/od_buf/handler = %s' % ('present' if oram else 'absent', want),
                not r['cy'] and st == want, tuple(hex(x) for x in st))
        unit, tps = sym['od_unit'], sym['od_tps']

        # 1. catalog via od_read
        r = t.call('od_read', dict(hl=0, bc=7 << 8, de=0x9000))
        t.check('od_read catalog (7 blocks)', not r['cy'] and zx.peek(0x9000, 7 * 256) == ss.read_blocks(0, 7), r)
        # 2. a long file crossing several tracks
        e = ss.find('bigger')
        n = e['end'] - e['first'] + 1
        r = t.call('od_read', dict(hl=e['first'], bc=n << 8, de=0x8000))
        t.check('od_read %d blocks from %d' % (n, e['first']),
                not r['cy'] and zx.peek(0x8000, n * 256) == ss.read_blocks(e['first'], n) and r['de'] == 0x8000 + n * 256, r)
        # 3. od_load by name, with guard bytes around
        for name in ['small', 'one', 'two', 'big']:
            zx.poke(0xA000 - 16, [0x55] * 16)
            zx.poke(0xA000, [0] * len(files[name]))
            zx.poke(0xA000 + len(files[name]), [0x66] * 300)
            zx.poke(0x7D00, list(name.ljust(10).encode()))
            r = t.call('od_load', dict(hl=0x7D00, de=0xA000))
            got = zx.peek(0xA000, len(files[name]))
            g1 = zx.peek(0xA000 - 16, 16) == b'\x55' * 16
            g2 = zx.peek(0xA000 + len(files[name]), 300) == b'\x66' * 300
            t.check('od_load "%s" (%d bytes) + guards' % (name, len(files[name])),
                    not r['cy'] and got == files[name] and g1 and g2 and r['hl'] == len(files[name]) and r['a'] == 3,
                    '' if (g1 and g2) else 'guards %s %s' % (g1, g2))
        zx.poke(0x7D00, list(b'nosuchfile'))
        r = t.call('od_load', dict(hl=0x7D00, de=0xA000))
        t.check('od_load missing file -> CY', r['cy'] == 1)
        # 4. write blocks, compare image
        data = bytes(random.Random(5).randrange(256) for _ in range(40 * 256))
        zx.poke(0x9000, data)
        r = t.call('od_write', dict(hl=600, bc=40 << 8, de=0x9000))
        img = OPD(zx.disk(0))
        t.check('od_write 40 blocks @600', not r['cy'] and img.read_blocks(600, 40) == data, r)
        BPS, BLK, GEOM, TAG, SLOTLEN = 256, 600, None, '', 1500
        # exact tail: od_read with od_tail must not write past the last wanted byte
        for tail in (1, 100, BPS - 1):
            zx.poke(0x9000, [0] * (3 * BPS)); zx.poke(0x9000 + 2 * BPS + tail, [0x77] * (BPS + 64))
            zx.poke(sym['od_tail'], [tail & 255, tail >> 8])
            r = t.call('od_read', dict(hl=BLK, bc=3 << 8, de=0x9000))
            img = OPD(zx.disk(0), GEOM) if GEOM else OPD(zx.disk(0))
            exp = img.read_blocks(BLK, 3)[:2 * BPS + tail]
            t.check('%sod_read 3 blocks, tail %d bytes, guard after' % (TAG, tail),
                    not r['cy'] and zx.peek(0x9000, len(exp)) == exp
                    and zx.peek(0x9000 + len(exp), BPS + 64) == b'\x77' * (BPS + 64)
                    and zx.peek(sym['od_tail'], 2) == b'\0\0', r)

        # 5. od_save into existing slot, then od_load it back
        payload = bytes(random.Random(7).randrange(256) for _ in range(1500))
        zx.poke(0xB000, payload)
        zx.poke(0x7D00, list(b'slot      '))
        r = t.call('od_save', dict(hl=0x7D00, de=0xB000, bc=len(payload)))
        img = OPD(zx.disk(0))
        fb = img.file_bytes(img.find('slot'))
        t.check('od_save "slot" 1500 bytes', not r['cy'] and fb[:7] == struct.pack('<BHHH', 3, 1500, 0xB000, 0x8000)
                and fb[7:7 + 1500] == payload, r)
        zx.poke(0xB000, [0] * 1500)
        r = t.call('od_load', dict(hl=0x7D00, de=0))
        t.check('od_load "slot" back to header address', not r['cy'] and zx.peek(0xB000, 1500) == payload and r['de'] == 0xB000)
        r = t.call('od_save', dict(hl=0x7D00, de=0xB000, bc=5000))
        t.check('od_save too big -> CY', r['cy'] == 1)
        # od_save must not modify memory at all (it only reads it)
        before = zx.peek(0xB000 - 64, SLOTLEN + 2 * BPS)
        zx.poke(0x7D00, list(b'slot      '))
        r = t.call('od_save', dict(hl=0x7D00, de=0xB000, bc=SLOTLEN))
        t.check('%sod_save leaves RAM untouched' % TAG, not r['cy'] and zx.peek(0xB000 - 64, SLOTLEN + 2 * BPS) == before, r)

        # 6. double-sided disk in drive 2, read across the side boundary.
        # (M8XXX keeps ONE geometry per controller, set by the last image
        #  inserted, so from here on both drives hold DS images.)
        zx.insert(bytes(ds.d), 1, 'ds.opd')
        ds1 = OPD.new(True, 'DS1')
        ds1.add_code('big', files['big'], 0x8000)
        zx.insert(bytes(ds1.d), 0, 'ds1.opd')
        zx.poke(unit, [2]); zx.poke(tps, [80])
        e = ds.find('cross')
        n = e['end'] - e['first'] + 1
        r = t.call('od_read', dict(hl=e['first'], bc=n << 8, de=0x8000))
        t.check('drive 2 DS read across side 0/1 (%d-%d)' % (e['first'], e['end']),
                not r['cy'] and zx.peek(0x8000, n * 256) == ds.read_blocks(e['first'], n), r)
        data = bytes(random.Random(9).randrange(256) for _ in range(6 * 256))
        zx.poke(0x9000, data)
        r = t.call('od_write', dict(hl=1436, bc=6 << 8, de=0x9000))
        img = OPD(zx.disk(1))
        t.check('drive 2 DS write across side boundary', not r['cy'] and img.read_blocks(1436, 6) == data, r)
        # 7. back to drive 1 (track register swap) and read again
        zx.poke(unit, [1])
        e = ds1.find('big')
        n = e['end'] - e['first'] + 1
        r = t.call('od_read', dict(hl=e['first'], bc=n << 8, de=0x8000))
        t.check('back to drive 1 (DS)', not r['cy'] and zx.peek(0x8000, n * 256) == ds1.read_blocks(e['first'], n), r)
        r = t.call('od_read', dict(hl=1500, bc=3 << 8, de=0x8001))
        t.check('unaligned buffer, drive 1 side 1', not r['cy'] and zx.peek(0x8001, 768) == ds1.read_blocks(1500, 3), r)
        # 8. no disk -> error, not hang
        zx.js('window.zxDebug.spectrum.opus.ejectDisk(0), true')
        r = t.call('od_read', dict(hl=0, bc=1 << 8, de=0x9000), frames=20000)
        t.check('no disk -> CY (no hang)', r['cy'] == 1, 'frames=%d' % r['frames'])
        return t.fails


def run_dd(rom, fast, oram=True):
    """DD format: 80 tracks x 2 sides x 10 x 512, geometry read by od_geom."""
    bin_, sym = build(fast)
    rnd = random.Random(11)
    dd = OPD.new('dd', 'DDTEST')
    files = {}
    for name, size in [('small', 100), ('one', 505), ('two', 506), ('big', 20000)]:
        files[name] = bytes(rnd.randrange(256) for _ in range(size))
        dd.add_code(name, files[name], 0x8000)
    per = 60000 // 512           # filler so that 'cross' spans the side boundary (block 799)
    left, i = 794 - (dd.files()[-1]['end'] + 1), 0
    while left > 0:
        n = min(per, left); dd.add_code('fill%d' % i, bytes(n * 512 - 7), 0x8000); left -= n; i += 1
    files['cross'] = bytes(rnd.randrange(256) for _ in range(12 * 512 - 7))
    e = dd.add_code('cross', files['cross'], 0x9000)
    assert e['first'] < 799 < e['end'], e
    files['slot'] = bytes(3000)
    dd.add_code('slot', files['slot'], 0xB000)
    with ZX(rom=rom, opus_ram=oram) as zx:
        zx.frames(120)
        zx.insert(bytes(dd.d), 0, 'dd.opd')
        zx.poke(0x6000, bin_)
        t = T(zx, sym)
        r = t.call('od_read', dict(hl=0, bc=1 << 8, de=0x9000))
        st = zx.peek(sym['od_ram'], 1)[0], int.from_bytes(zx.peek(sym['od_buf'], 2), 'little'), \
            int.from_bytes(zx.peek(sym['od_hrd'], 2), 'little')
        want = (1, 0x2200, 0x2100) if oram else (0, 0x7800, sym['od_nmird'])
        t.check('Opus RAM %s: od_ram/od_buf/handler = %s' % ('present' if oram else 'absent', want),
                not r['cy'] and st == want, tuple(hex(x) for x in st))
        r = t.call('od_geom', {})
        g = zx.peek(sym['od_tps'], 3)
        t.check('od_geom -> tps/spt/spg = 80/10/2', not r['cy'] and tuple(g) == (80, 10, 2) and r['a'] == 0x90, (r, tuple(g)))
        r = t.call('od_read', dict(hl=0, bc=7 << 8, de=0x8000))
        t.check('DD od_read catalog (7 x 512)', not r['cy'] and zx.peek(0x8000, 7 * 512) == dd.read_blocks(0, 7) and r['de'] == 0x8000 + 3584, r)
        e = dd.find('cross'); n = e['end'] - e['first'] + 1
        r = t.call('od_read', dict(hl=e['first'], bc=n << 8, de=0x8001))
        t.check('DD od_read across sides (%d-%d), unaligned' % (e['first'], e['end']),
                not r['cy'] and zx.peek(0x8001, n * 512) == dd.read_blocks(e['first'], n), r)
        for name in ['small', 'one', 'two', 'big', 'cross']:
            ln = len(files[name])
            zx.poke(0x9000 - 16, [0x55] * 16); zx.poke(0x9000, [0] * ln); zx.poke(0x9000 + ln, [0x66] * 600)
            zx.poke(0x7D00, list(name.ljust(10).encode()))
            r = t.call('od_load', dict(hl=0x7D00, de=0x9000))
            g1 = zx.peek(0x9000 - 16, 16) == b'U' * 16
            g2 = zx.peek(0x9000 + ln, 600) == b'f' * 600
            t.check('DD od_load "%s" (%d bytes) + guards' % (name, ln),
                    not r['cy'] and zx.peek(0x9000, ln) == files[name] and g1 and g2 and r['hl'] == ln,
                    '' if (g1 and g2) else 'guards %s %s' % (g1, g2))
        data = bytes(random.Random(5).randrange(256) for _ in range(12 * 512))
        zx.poke(0x9000, data)
        r = t.call('od_write', dict(hl=795, bc=12 << 8, de=0x9000))
        img = OPD(zx.disk(0), (80, 2, 10, 512))
        t.check('DD od_write 12 blocks across sides', not r['cy'] and img.read_blocks(795, 12) == data, r)
        BPS, BLK, GEOM, TAG, SLOTLEN = 512, 797, (80, 2, 10, 512), 'DD ', 2900
        # exact tail: od_read with od_tail must not write past the last wanted byte
        for tail in (1, 100, BPS - 1):
            zx.poke(0x9000, [0] * (3 * BPS)); zx.poke(0x9000 + 2 * BPS + tail, [0x77] * (BPS + 64))
            zx.poke(sym['od_tail'], [tail & 255, tail >> 8])
            r = t.call('od_read', dict(hl=BLK, bc=3 << 8, de=0x9000))
            img = OPD(zx.disk(0), GEOM) if GEOM else OPD(zx.disk(0))
            exp = img.read_blocks(BLK, 3)[:2 * BPS + tail]
            t.check('%sod_read 3 blocks, tail %d bytes, guard after' % (TAG, tail),
                    not r['cy'] and zx.peek(0x9000, len(exp)) == exp
                    and zx.peek(0x9000 + len(exp), BPS + 64) == b'\x77' * (BPS + 64)
                    and zx.peek(sym['od_tail'], 2) == b'\0\0', r)

        payload = bytes(random.Random(7).randrange(256) for _ in range(2900))
        zx.poke(0xB000, payload); zx.poke(0x7D00, list(b'slot      '))
        r = t.call('od_save', dict(hl=0x7D00, de=0xB000, bc=len(payload)))
        img = OPD(zx.disk(0), (80, 2, 10, 512))
        fb = img.file_bytes(img.find('slot'))
        t.check('DD od_save "slot" 2900 bytes', not r['cy'] and fb[7:7 + 2900] == payload, r)
        r = t.call('od_save', dict(hl=0x7D00, de=0xB000, bc=3100))
        t.check('DD od_save too big -> CY', r['cy'] == 1)
        # od_save must not modify memory at all (it only reads it)
        before = zx.peek(0xB000 - 64, SLOTLEN + 2 * BPS)
        zx.poke(0x7D00, list(b'slot      '))
        r = t.call('od_save', dict(hl=0x7D00, de=0xB000, bc=SLOTLEN))
        t.check('%sod_save leaves RAM untouched' % TAG, not r['cy'] and zx.peek(0xB000 - 64, SLOTLEN + 2 * BPS) == before, r)

        return t.fails


if __name__ == '__main__':
    roms = sys.argv[1:] or ROMS
    total = 0
    for rom in roms:
        for oram in (True, False):
            for fast in (1, 0):
                tag = 'Opus RAM' if oram else 'no Opus RAM'
                print('== %s  OD_FAST=%d  %s' % (rom, fast, tag))
                total += run(rom, fast, oram)
                print('== %s  OD_FAST=%d  DD 80x2x10x512  %s' % (rom, fast, tag))
                total += run_dd(rom, fast, oram)
    print('FAILURES:', total)
    sys.exit(1 if total else 0)
