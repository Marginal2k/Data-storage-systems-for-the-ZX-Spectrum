"""Raw files (no 7-byte header: everything is in the catalogue entry): od_rload / od_rsave of opuslib.
SD (16 entries per catalogue block) and DD (32), Opus RAM present / absent, OD_FAST 1 / 0.
  * od_rload of raw files (6912 = exactly 27 / 14 blocks, 1 byte, 1000) with guard bytes; length returned
  * od_rsave of a new file into a gap in the middle of the disk: the entries after it move on, across a
    catalogue block boundary; every other file unchanged; the catalogue as opdtool would make it
  * od_rsave over an existing file, shorter (the entry's length and last block updated), longer than it has -> #FF
  * no room on the disk -> #FD; catalogue full -> #FC; missing file -> CY
python run_rawtest.py [rom ...]"""
import os, sys, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
sys.stdout.reconfigure(line_buffering=True)
from zxharness import ZX
from opdtool import OPD
from run_libtest import ROMS, build, T


def make(fmt):
    rnd = random.Random(3)
    o = OPD.new(fmt, 'RAWTEST')
    files = {}
    names = ['f%02d' % i for i in range(20)]          # 20 small files: the catalogue spills into its 2nd block on SD
    for n in names:
        files[n] = bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 3 * o.bps)))
        o.add_raw(n, files[n])
    files['scr'] = bytes(rnd.randrange(256) for _ in range(6912))
    o.add_raw('scr', files['scr'])
    files['one'] = b'\x5a'
    o.add_raw('one', files['one'])
    files['slot'] = bytes(rnd.randrange(256) for _ in range(3000))
    o.add_raw('slot', files['slot'])
    # a gap of 40 blocks after f03: move f04.. on (rebuild the disk with a spacer, then drop the spacer's entry)
    p = OPD.new(fmt, 'RAWTEST')
    for n in names[:4]:
        p.add_raw(n, files[n])
    p.add_raw('spacer', bytes(40 * o.bps))
    for n in names[4:] + ['scr', 'one', 'slot']:
        p.add_raw(n, files[n])
    cat = bytearray(p.read_blocks(0, p.cat_blocks()))
    i = next(k for k in range(0, len(cat), 16) if cat[k + 6:k + 16] == b'spacer    ')
    del cat[i:i + 16]
    cat += b'\xe5' * 16
    p.write_blocks(0, bytes(cat))
    assert not p.find('spacer')
    return p, files


def entries(o):
    return [(e['name'].rstrip(), e['first'], e['end']) for e in o.files()]


def run(rom, fast, oram, fmt):
    bin_, sym = build(fast)
    o, files = make(fmt)
    geom = (o.tps, o.sides, o.spt, o.bps)
    with ZX(rom=rom, opus_ram=oram) as zx:
        zx.frames(120)
        zx.insert(bytes(o.d), 0, 'raw.opd', geom=geom)
        zx.poke(0x6000, bin_)
        t = T(zx, sym)
        t.call('od_geom', {})
        tag = '%s %s' % (fmt.upper(), 'RAM' if oram else 'noRAM')

        def name(n):
            zx.poke(0x7D00, list(n.ljust(10).encode()))

        def img():
            return OPD(zx.disk(0)[:len(o.d)], geom)

        for n in ('scr', 'one', 'f07', 'f19'):
            d = files[n]
            zx.poke(0xA000 - 16, [0x55] * 16); zx.poke(0xA000, [0] * len(d)); zx.poke(0xA000 + len(d), [0x66] * 600)
            name(n)
            r = t.call('od_rload', dict(hl=0x7D00, de=0xA000))
            g = zx.peek(0xA000 - 16, 16) == b'U' * 16 and zx.peek(0xA000 + len(d), 600) == b'f' * 600
            t.check('%s od_rload "%s" (%d bytes) + guards' % (tag, n, len(d)),
                    not r['cy'] and zx.peek(0xA000, len(d)) == d and g and r['hl'] == len(d) and r['de'] == 0xA000, r)
        name('nosuch')
        r = t.call('od_rload', dict(hl=0x7D00, de=0xA000))
        t.check('%s od_rload missing -> CY' % tag, r['cy'] == 1)

        # a new file: 20 blocks, goes into the 40-block gap after f03
        new = bytes(random.Random(8).randrange(256) for _ in range(20 * o.bps - 100))
        zx.poke(0xB000 - 64, [0x33] * 64); zx.poke(0xB000, new); zx.poke(0xB000 + len(new), [0x44] * 64)
        before = zx.peek(0xB000 - 64, len(new) + 128)
        name('newraw')
        r = t.call('od_rsave', dict(hl=0x7D00, de=0xB000, bc=len(new)))
        i = img()
        ref = OPD(bytes(o.d), geom)
        e3 = ref.find('f03')
        want = entries(ref)
        want.insert(4, ('newraw', e3['end'] + 1, e3['end'] + 20))
        same = all(i.file_bytes(i.find(n)) == d for n, d in files.items())
        t.check('%s od_rsave new file into the gap (%d bytes)' % (tag, len(new)),
                not r['cy'] and r['hl'] == e3['end'] + 1 and entries(i) == want and i.file_bytes(i.find('newraw')) == new
                and same and zx.peek(0xB000 - 64, len(new) + 128) == before, (r, entries(i)[3:6]))
        # read it back
        zx.poke(0x9000, [0] * len(new))
        r = t.call('od_rload', dict(hl=0x7D00, de=0x9000))
        t.check('%s od_rload the new file' % tag, not r['cy'] and zx.peek(0x9000, len(new)) == new and r['hl'] == len(new), r)
        # overwrite shorter
        short = new[:1000]
        r = t.call('od_rsave', dict(hl=0x7D00, de=0xB000, bc=1000))
        i = img()
        e = i.find('newraw')
        t.check('%s od_rsave shorter: length and last block updated' % tag,
                not r['cy'] and i.file_bytes(e) == short and e['end'] - e['first'] + 1 == (1000 + o.bps - 1) // o.bps
                and all(i.file_bytes(i.find(n)) == d for n, d in files.items()), r)
        # longer than the slot has
        name('slot')
        r = t.call('od_rsave', dict(hl=0x7D00, de=0xB000, bc=8000))
        t.check('%s od_rsave longer than the file -> #FF' % tag, r['cy'] == 1 and r['a'] == 0xFF, r)
        # no room
        name('huge')
        r = t.call('od_rsave', dict(hl=0x7D00, de=0x8000, bc=65000))
        free = o.blocks - img().files()[-1]['end'] - 1
        if free * o.bps < 65000:
            t.check('%s od_rsave with no room -> #FD (free %d blocks)' % (tag, free), r['cy'] == 1 and r['a'] == 0xFD, r)
        # catalogue full: fill it with 1-block files
        n = 0
        while True:
            name('z%03d' % n)
            r = t.call('od_rsave', dict(hl=0x7D00, de=0x8000, bc=1))
            if r['cy']:
                break
            n += 1
        i = img()
        cap = i.cat_blocks() * i.bps // 16 - 2           # entry 0 and the end marker
        t.check('%s catalogue full after %d new files -> #FC; all files intact' % (tag, n),
                r['a'] == 0xFC and len(i.files()) == cap and all(i.file_bytes(i.find(k)) == d for k, d in files.items()), (r, len(i.files()), cap))
        return t.fails


if __name__ == '__main__':
    total = 0
    for rom in sys.argv[1:] or ROMS:
        for oram in (True, False):
            for fast in (1, 0):
                for fmt in ('sd', 'dd'):
                    print('== %s  OD_FAST=%d  %s %s' % (rom, fast, fmt, 'Opus RAM' if oram else 'no Opus RAM'))
                    total += run(rom, fast, oram, fmt)
    print('FAILURES:', total)
    sys.exit(1 if total else 0)
