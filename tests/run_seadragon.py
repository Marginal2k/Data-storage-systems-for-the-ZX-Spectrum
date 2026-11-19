"""Sea Dragon on the Opus Discovery: boot the disks built by the game's build.py
(build/SeaDragon_opus_sd.opd, _dd.dsk: the same file "run" on both) in ZX-M8XXX on 48K and 128K, catch the
jump to the game's Start and compare memory with the built binaries:
  * #6000..MainBlockEnd = sd_main.C (except AvailableDevices, set by the stub)
  * on 128K: pages 3, 1, 4, 6 at #C000 = sd_p3/p1/p4/p6.C
Screenshots of the loading screen and of the game menu go to tests/seadragon_*.png.

python run_seadragon.py [rom ...]       env SD_FORMATS=sd,dd  SD_MACHINES=48k,128k
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
sys.stdout.reconfigure(line_buffering=True)
from zxharness import ZX
from run_libtest import ROMS
from zx128 import boot_128basic, menu_rows, enter_128basic, command_128

GAME = os.environ.get('SEADRAGON', os.path.join(HERE, '..', '..', 'seadragon'))   # the game's repository
BUILD = os.path.join(GAME, 'build')


def syms():
    out = {}
    for line in open(os.path.join(BUILD, 'SeaDragon.sym'), encoding='utf-8', errors='replace'):
        if ': EQU ' in line:
            n, v = line.split(': EQU ')
            out[n.strip()] = int(v.strip(), 16)
    return out


if not os.path.isfile(os.path.join(BUILD, 'SeaDragon.sym')):
    raise SystemExit('Sea Dragon build not found in %s: set SEADRAGON to the game repository and run '
                     'build.py there first' % os.path.abspath(BUILD))
S = syms()
MAIN = open(os.path.join(BUILD, 'bin', 'sd_main.C'), 'rb').read()
PAGES = {S['AY_MUSIC_PAGE']: 'sd_p3.C', S['AY_SOUND_PAGE']: 'sd_p1.C', S['IO_PAGE']: 'sd_p4.C', S['AY_MELODY_PAGE']: 'sd_p6.C'}
PAGEDATA = {p: open(os.path.join(BUILD, 'bin', f), 'rb').read() for p, f in PAGES.items()}


def run(rom, fmt, machine):
    img = os.path.join(BUILD, 'SeaDragon_opus_%s.%s' % (fmt, 'opd' if fmt == 'sd' else 'dsk'))
    boot = 'RUN' if ('v1.2' in rom and machine == '48k') else 'LOAD *"m";1;"run"'
    with ZX(rom=rom, machine=machine) as zx:
        if machine == '128k':
            # M8XXX quirk: with a 40-track drive geometry, 128 BASIC drops back to the menu. The emulated
            # drive is given 80 tracks; the disk itself (its anchor: 40 tracks) is unchanged and the loader
            # takes the geometry from it. Inserting an image may reset the machine: enter_128basic retries.
            def ins():
                if fmt == 'dd':
                    zx.insert(img)
                else:
                    raw = open(img, 'rb').read()
                    zx.insert(raw + bytes([0xE5]) * len(raw), geom=(80, 1, 18, 256))
            enter_128basic(zx, ins)
        else:
            zx.insert(img)
            zx.frames(120)
        # catch the jump to Start and snapshot memory right there
        zx.js('''(()=>{ window._sd = null; const s = zxDebug.spectrum;
            zxDebug.onAccess({onFetch: (a) => { if (a === %d && !window._sd && !s.memory.opusActive) {
                const main = Array.from(zxDebug.peekBlock(%d, %d));
                const pages = {}; for (const p of %s) { const b = zxDebug.peekBank(p); pages[p] = b ? Array.from(b) : null; }
                window._sd = {frame: s.totalFrames, main, pages, dev: zxDebug.peek(%d)}; } }}); return 1; })()''' % (
            S['Start'], S['START_ORG'], len(MAIN), list(PAGES), S['AvailableDevices']))
        f0 = zx.js('zxDebug.spectrum.totalFrames')
        if machine == '128k':           # 128 BASIC: Opus commands typed in full
            command_128(zx, lambda: zx.type(boot, hold=6, gap=6))
        else:
            zx.basic(boot)
        shot = False
        n = 0
        while n < 6000:
            zx.frames(25)
            n += 25
            if not shot and n >= 150:
                zx.screenshot(os.path.join(HERE, 'seadragon_%s_%s_loading.png' % (fmt, machine)))
                shot = True
            if zx.js('!!window._sd'):
                break
        r = zx.js('window._sd')
        zx.js('zxDebug.offAccess(), 1')
        if not r:
            print('  %-4s %-5s FAIL: Start not reached; screen: %s' % (
                fmt, machine, zx.screen_text().strip().split('\n')[-1][-40:]))
            zx.screenshot(os.path.join(HERE, 'seadragon_%s_%s_fail.png' % (fmt, machine)))
            return 1
        main = bytes(r['main'])
        dev_off = S['AvailableDevices'] - S['START_ORG']
        main_ok = main[:dev_off] == MAIN[:dev_off] and main[dev_off + 1:] == MAIN[dev_off + 1:]
        pages_ok = None
        if machine == '128k':
            pages_ok = all(r['pages'][str(p)] is not None and bytes(r['pages'][str(p)][:len(d)]) == d
                           for p, d in PAGEDATA.items())
        zx.frames(250)
        zx.screenshot(os.path.join(HERE, 'seadragon_%s_%s_game.png' % (fmt, machine)))
        good = main_ok and pages_ok is not False
        print('  %-4s %-5s %s  Start after %d frames (%.1f s)  main=%s pages=%s devices=%02X' % (
            fmt, machine, 'ok  ' if good else 'FAIL', r['frame'] - f0, (r['frame'] - f0) / 50,
            main_ok, pages_ok, r['dev']))
        return 0 if good else 1


if __name__ == '__main__':
    roms = sys.argv[1:] or ROMS
    fmts = os.environ.get('SD_FORMATS', 'sd,dd').split(',')
    machines = os.environ.get('SD_MACHINES', '48k,128k').split(',')
    fails = 0
    for rom in roms:
        print('==', rom)
        for machine in machines:
            if machine == '128k' and 'v1.2' in rom:
                print('  (v1.2 predates 128K support - skipped)')
                continue
            for fmt in fmts:
                fails += run(rom, fmt, machine)
    print('FAILURES:', fails)
    sys.exit(1 if fails else 0)
