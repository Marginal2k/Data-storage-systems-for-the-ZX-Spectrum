"""Terminator 2 on the Opus Discovery: the hi-score table is written to the disk and read back.
1) boot to the title, change the table in memory (#F758, 128K: bank 0), enter "new game" (48K: new_game, 128K: #78E6
   -> hs128), let it write; the last 512 bytes of the file T2 must be: container header (8) + table (60) + checksum
2) boot the written disk again: at the title the table in memory must be the changed one.
python run_t2hs.py [rom ...]     env T2_FORMATS, T2_MACHINES"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
sys.stdout.reconfigure(line_buffering=True)
from zxharness import ZX
from run_libtest import ROMS
from run_seadragon import boot_128basic, menu_rows
import run_t2 as t
import opdtool

RES = {l.split(': EQU 0x')[0]: int(l.split(': EQU 0x')[1], 16) for l in open(os.path.join(t.OB, 'res128.exp'))}
MAGIC = bytes([1, 0, 0, 60, 0, 0x12, 0x58, 0xF7])


def hsum(b):
    s = 0x5A5A
    for x in b: s = (s + x) & 0xFFFF
    return s


def boot(zx, rom, fmt, machine, img):
    """img: raw bytes; -> True at the title"""
    o = opdtool.OPD(img)
    g = (o.tps, o.sides, o.spt, o.bps)
    if machine == '128k':
        def ins():
            if g[0] == 40:      # (M8XXX quirk, see run_t2.py)
                zx.insert(img + bytes([0xE5]) * len(img), geom=(80, 1, 18, 256))
            else:
                zx.insert(img, geom=g)
        t.enter_128basic(zx, ins)
        t.command_128(zx, lambda: zx.type('load *"m";1;"run"', hold=6, gap=6))
    else:
        zx.insert(img, geom=g)
        zx.frames(120)
        zx.basic('RUN' if 'v1.2' in rom else 'LOAD *"m";1;"run"')
    zx.js('''(() => { window._ti = 0; window._k = 0; zxDebug.onAccess({onFetch: (a) => { if (a === 0x7EA9) window._ti = 1;
        if (a === %d || a === 0x7200) window._k = 1; }}); return 1; })()''' % t.K['kern_start'])
    n = 0
    while n < 9000 and not zx.js('window._k'):
        zx.frames(50)
        n += 50
    zx.frames(400)
    zx.key('Enter', frames=6)               # joystick selection
    n = 0
    while n < 1500 and not zx.js('window._ti'):
        zx.frames(50)
        n += 50
    zx.js('zxDebug.offAccess(), 1')
    ok = bool(zx.js('window._ti'))
    if not ok:
        zx.screenshot(os.path.join(HERE, 't2hs_%s_%s_bootfail.png' % (fmt, machine)))
    return ok


def table(zx, machine):
    if machine == '128k':
        return bytes(zx.js('Array.from(zxDebug.peekBank(0).slice(%d, %d))' % (0xF758 - 0xC000, 0xF758 - 0xC000 + 60)))
    return zx.peek(0xF758, 60)


def set_table(zx, machine, data):
    if machine == '128k':
        zx.js('(() => { const b = zxDebug.spectrum.memory.getRamBank(0); const d = %s; for (let i = 0; i < 60; i++) b[%d + i] = d[i]; return 1; })()' % (
            list(data), 0xF758 - 0xC000))
    else:
        zx.poke(0xF758, data)


def run(rom, fmt, machine):
    img0 = open(os.path.join(t.OB, 'T2_opus_%s.%s' % (fmt, 'opd' if fmt == 'sd' else 'dsk')), 'rb').read()
    img0 = bytes(opdtool.OPD(opdtool.load_image(img0)).d)
    with ZX(rom=rom, machine=machine) as zx:
        if not boot(zx, rom, fmt, machine, img0):
            print('  %-3s %-5s FAIL: no title' % (fmt, machine)); return 1
        zx.frames(50)
        old = table(zx, machine)
        new = bytearray(old)
        for i, c in enumerate(b'OPUS'):
            new[i] = c                      # (the first record starts with its name in the game's table)
        new = bytes(new)
        set_table(zx, machine, new)
        # "new game" (48K: new_game -> hs_disk_save; 128K: #78E6 -> hs128, whose first call at the start of the game took the
        # baseline checksum already). setRegisters is not always taken (inside an interrupt?): repeat until the hook ran.
        target = t.K['hs_disk_save'] if machine == '48k' else RES['hs128']
        zx.js('''(() => { window._hs = 0; zxDebug.onAccess({onFetch: (a) => { if (a === %d) window._hs = 1; }}); return 1; })()''' % target)
        for attempt in range(5):
            zx.js('zxDebug.spectrum.cpu.halted = false, zxDebug.setRegisters({pc: %d}), 1' % (t.K['new_game'] if machine == '48k' else 0x78E6))
            zx.frames(400)
            if zx.js('window._hs'):
                break
        hooked = zx.js('window._hs')
        zx.js('zxDebug.offAccess(), 1')
        raw = zx.disk(0)[:len(img0)]
    o = opdtool.OPD(raw)
    e = o.find('T2')
    f = o.file_bytes(e)
    hs = f[len(t.TFILE) - 512:len(t.TFILE)]
    if os.environ.get('T2_DEBUG'):
        print('    hs', hs[:12].hex(), 'new', new[:8], 'tab', hs[8:16], 'hook', hooked)
    wrote = hs[:8] == MAGIC and hs[8:68] == new and hs[68] | (hs[69] << 8) == hsum(hs[:68])
    rest_same = f[:len(t.TFILE) - 512] == t.TFILE[:-512]
    back = None
    if wrote:
        with ZX(rom=rom, machine=machine) as zx:
            if boot(zx, rom, fmt, machine, raw):
                zx.frames(50)
                back = table(zx, machine) == new
    good = wrote and rest_same and back
    print('  %-3s %-5s %s  written %s, rest of the file unchanged %s, read back %s' % (fmt, machine, 'ok  ' if good else 'FAIL', wrote, rest_same, back))
    return 0 if good else 1


if __name__ == '__main__':
    roms = sys.argv[1:] or ROMS
    fails = 0
    for rom in roms:
        print('==', rom)
        for machine in os.environ.get('T2_MACHINES', '48k,128k').split(','):
            if machine == '128k' and 'v1.2' in rom:
                continue
            for fmt in os.environ.get('T2_FORMATS', 'sd,dd').split(','):
                fails += run(rom, fmt, machine)
    print('FAILURES:', fails)
    sys.exit(1 if fails else 0)
