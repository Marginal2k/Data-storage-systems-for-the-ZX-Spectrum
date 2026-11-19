"""Terminator 2 on the Opus Discovery: boot the disks built by the game's tools/build_opus.py
(build/opus/T2_opus_sd.opd, _dd.dsk) in ZX-M8XXX on 48K and 128K and check every block read:
at each call of the container unpacker (`process`) the bytes just read (RD_N units at RD_BUF) must
equal the file T2 at unit RD_TS - V_BASE of its data part. 48K: the kernel starts, loads the menu,
the game is started (level 1 is loaded from the disk). 128K: everything loads in one pass, JP #7200.

python run_t2.py [rom ...]       env T2_FORMATS=sd,dd  T2_MACHINES=48k,128k  T2_DIR=<T2 repo>  T2_PLAY=frames
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
sys.stdout.reconfigure(line_buffering=True)
from zxharness import ZX
from run_libtest import ROMS
from zx128 import boot_128basic, menu_rows, enter_128basic, command_128

T2 = os.environ.get('T2_DIR', os.path.join(HERE, '..', '..', 'T2'))   # the game's repository
OB = os.environ.get('T2_OB') or os.path.join(T2, 'build', 'opus')
if not os.path.isfile(os.path.join(OB, 'kern48.sym')):
    raise SystemExit('Terminator 2 build not found in %s: set T2_DIR to the game repository and run '
                     'tools/build_opus.py there first' % os.path.abspath(OB))
DUPE = os.environ.get('T2_DUPE')        # level test builds (build_opus.py --start N): the cheat on, fights won by #7E0F = 0
FIGHT = os.environ.get('T2_FIGHT')      # 1 = the starting stage is a fight


def syms(path):
    out = {}
    for line in open(path, encoding='utf-8', errors='replace'):
        if ': EQU ' in line:
            n, v = line.split(': EQU ')
            out[n.strip()] = int(v.strip(), 16)
    return out


K = syms(os.path.join(OB, 'kern48.sym'))
D = syms(os.path.join(OB, 'disk.sym'))
LAY = json.load(open(os.path.join(OB, 'layout.json')))
TFILE = open(os.path.join(OB, 'T2.bin'), 'rb').read()
DATA0 = ((LAY['head'] + 511) // 512) * 512          # the data part starts on the next 512-byte boundary of the file
NAMES = {o: n for n, o, u, s48, s128, ln in LAY['blocks']}
NAMES[LAY['hs']] = 'HS'
K4VARS = 0x5BF0


def hook(zx, machine):
    """record every block read at the entry of `process` (48K: the payload's and the kernel's; 128K: the loader's)"""
    if machine == '48k':
        pts = [(D['m48.process'], K4VARS + 6, K4VARS + 8, K4VARS + 10, D['d_base']), (K['process'], K4VARS + 6, K4VARS + 8, K4VARS + 10, K4VARS + 2)]
    else:
        pts = [(D['m128.process'], D['m128.RD_TS'], D['m128.RD_BUF'], D['m128.RD_N'], D['m128.V_BASE'])]
    rds = [K['op_rd'], D['op_rd'], D['m128.op_rd']]
    zx.js('''(() => { window._rd = []; window._ev = {}; window._pend = 0; const s = zxDebug.spectrum; const P = %s; const W = %s; const R = %s;
        const w = (a) => zxDebug.peek(a) | (zxDebug.peek(a + 1) << 8);
        zxDebug.onAccess({onFetch: (a) => { if (s.memory.opusActive) return;
            if (R.includes(a)) window._pend = 1;
            for (const [pc, ts, buf, n, base] of P) if (a === pc && window._pend) { window._pend = 0;
                const b = w(buf), u = zxDebug.peek(n);
                window._rd.push({frame: s.totalFrames, ts: w(ts), buf: b, n: u, base: w(base), hl: zxDebug.captureRegisters().hl,
                                 data: Array.from(zxDebug.peekBlock(b, u * 256))}); }
            for (const [name, pc] of W) if (a === pc && !(name in window._ev)) window._ev[name] = s.totalFrames; }}); return 1; })()''' % (
        json.dumps(pts), json.dumps([['kern', K['kern_start']], ['g7200', 0x7200], ['title', 0x7EA9]]), json.dumps(rds)))


def check(recs):
    bad = 0
    for r in recs:
        if r['hl'] != r['buf']:
            continue                    # process of a container already in memory (after the hi-score read, which has no process)
        off = r['ts'] - r['base']
        exp = TFILE[DATA0 + off * 256: DATA0 + (off + r['n']) * 256]
        ok = bytes(r['data']) == exp and r['hl'] == r['buf']
        if not ok:
            bad += 1
            diff = next((i for i in range(min(len(exp), len(r['data']))) if r['data'][i] != exp[i]), None)
            print('    READ MISMATCH %s off %d n %d buf %04X: first diff at +%s' % (NAMES.get(off, '?'), off, r['n'], r['buf'], diff))
    return bad


def run(rom, fmt, machine, play):
    img = os.path.join(OB, 'T2_opus_%s.%s' % (fmt, 'opd' if fmt == 'sd' else 'dsk'))
    via_run = os.environ.get('T2_BOOT') == 'run'      # boot the launcher "run" (one program on the disk: it starts T2 at once)
    cmd = ('RUN' if 'v1.2' in rom else 'LOAD *"m";1;"run"') if via_run else 'LOAD *"m";1;"T2"'
    tag = '%s_%s_%s%s' % (fmt, machine, rom.split()[2] if len(rom.split()) > 2 else 'x', os.environ.get('T2_TAG', ''))
    with ZX(rom=rom, machine=machine) as zx:
        if machine == '128k':
            def ins():
                if fmt == 'dd':
                    zx.insert(img)
                else:                   # M8XXX quirk: with a 40-track drive geometry 128 BASIC drops back to the menu. The emulated drive is given
                    raw = open(img, 'rb').read()  # 80 tracks; the disk itself (its anchor: 40 tracks) is unchanged, the game takes the geometry from it
                    zx.insert(raw + bytes([0xE5]) * len(raw), geom=(80, 1, 18, 256))
            enter_128basic(zx, ins)
        else:
            zx.insert(img)
            zx.frames(120)
        hook(zx, machine)
        f0 = zx.js('zxDebug.spectrum.totalFrames')
        if machine == '128k':
            def typer():
                if via_run:
                    zx.type('load *"m";1;"run"', hold=6, gap=6)
                else:
                    zx.type('load *"m";1;"', hold=6, gap=6)      # 128 BASIC: letters come out lower case, the name needs CAPS SHIFT
                    zx.js('zxDebug.keyDown("CAPS"), zxDebug.keyDown("KeyT"), 1'); zx.frames(6)
                    zx.js('zxDebug.keyUp("KeyT"), zxDebug.keyUp("CAPS"), 1'); zx.frames(6)
                    zx.type('2"', hold=6, gap=6)
            command_128(zx, typer)
        else:
            zx.basic(cmd)
        n = 0
        while n < 9000 and 'kern' not in zx.js('window._ev') and 'g7200' not in zx.js('window._ev'):
            zx.frames(50)
            n += 50
        zx.frames(400)                  # joystick selection
        zx.screenshot(os.path.join(HERE, 't2_%s_select.png' % tag))
        zx.key('Enter', frames=6)
        n = 0
        while n < 1500 and 'title' not in zx.js('window._ev'):
            zx.frames(50)
            n += 50
        ev = zx.js('window._ev')
        if 'title' not in ev:
            zx.screenshot(os.path.join(HERE, 't2_%s_fail.png' % tag))
            print('  %-3s %-5s FAIL: no title screen; events %s, reads %d' % (fmt, machine, ev, zx.js('window._rd.length')))
            return 1
        zx.frames(100)
        zx.screenshot(os.path.join(HERE, 't2_%s_title.png' % tag))
        dupe = None
        if DUPE:                        # D U P E on the TOP 10 screen (it follows PRESS FIRE): #7E33 = 7, white border
            for attempt in range(12):
                zx.frames(150)
                for k in ('KeyD', 'KeyU', 'KeyP', 'KeyE'):
                    zx.key(k, frames=4); zx.frames(6)
                zx.frames(10)
                dupe = zx.peek(0x7E33)[0]
                if dupe == 7:
                    break
                if dupe:                # toggled on and off again: once more
                    continue
        # start the game: 0 (start); 48K: the stage comes from the disk
        zx.key('0', frames=30)
        if DUPE:
            keys = ['Digit0', 'Digit7', 'Digit6', 'Digit9', 'Digit8']
            for i in range(play // 50):
                zx.js('zxDebug.keyDown("%s"), 1' % keys[i % len(keys)]); zx.frames(25)
                zx.js('zxDebug.keyUp("%s"), 1' % keys[i % len(keys)]); zx.frames(25)
                if FIGHT and i % 10 == 9:
                    zx.poke(0x7E0F, [0])    # the enemy has no energy left: the fight is won, the next stage loads
        else:
            zx.frames(play)
        zx.screenshot(os.path.join(HERE, 't2_%s_game.png' % tag))
        recs = zx.js('window._rd')
        ev = zx.js('window._ev')
        zx.js('zxDebug.offAccess(), 1')
        bad = check(recs)
        recs = [r for r in recs if r['hl'] == r['buf']]
        names = [NAMES.get(r['ts'] - r['base'], '?%d' % (r['ts'] - r['base'])) for r in recs]
        print('  %-3s %-5s %s  title after %.1f s, %d reads %s%s' % (fmt, machine, 'ok  ' if not bad else 'FAIL', (ev['title'] - f0) / 50, len(recs), ' '.join(names),
              '' if not DUPE else '; DUPE %s' % ('on' if dupe == 7 else 'NOT ON (%s)' % dupe)))
        if DUPE and dupe != 7: bad += 1
        return 1 if bad else 0


if __name__ == '__main__':
    roms = sys.argv[1:] or ROMS
    fmts = os.environ.get('T2_FORMATS', 'sd,dd').split(',')
    machines = os.environ.get('T2_MACHINES', '48k,128k').split(',')
    play = int(os.environ.get('T2_PLAY', '600'))
    fails = 0
    for rom in roms:
        print('==', rom)
        for machine in machines:
            if machine == '128k' and 'v1.2' in rom:
                print('  (v1.2 predates 128K support - skipped)')
                continue
            for fmt in fmts:
                fails += run(rom, fmt, machine, play)
    print('FAILURES:', fails)
    sys.exit(1 if fails else 0)
