"""The launcher "run" (tools/mkshell.py): a disk with "run" and two BASIC programs (+ a CODE file that must not be listed).
Boot it (RUN on v1.2, LOAD *"m";1;"run" otherwise), check the menu text, choose the 2nd program, check it ran.
Then a disk with one program: no menu, the program starts at once.     python run_shell.py [rom ...]"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
sys.stdout.reconfigure(line_buffering=True)
from zxharness import ZX
from run_libtest import ROMS
import opdtool, mkshell

RUN = mkshell.run_file(mkshell.assemble())


def basic_file(src, autostart=10):
    prog = opdtool.tokenize(src)
    return bytes([0]) + len(prog).to_bytes(2, 'little') + autostart.to_bytes(2, 'little') + len(prog).to_bytes(2, 'little') + prog


def disk(fmt, progs):
    o = opdtool.OPD.new(fmt, 'SHELLTEST')
    o.add_raw('run', RUN)
    o.add_raw('data', bytes([3]) + (10).to_bytes(2, 'little') + (32768).to_bytes(2, 'little') + bytes(2) + bytes(range(10)))   # CODE: not listed
    for name, text in progs:
        o.add_raw(name, basic_file('10 POKE 23296,%d: PRINT "%s"' % (text, name)))
    return bytes(o.d), (o.tps, o.sides, o.spt, o.bps)


def boot(zx, rom):
    zx.basic('RUN' if 'v1.2' in rom else 'LOAD *"m";1;"run"')


def one(rom, fmt):
    fails = 0
    with ZX(rom=rom, machine='48k') as zx:
        img, g = disk(fmt, [('alpha', 11), ('beta', 22)])
        zx.insert(img, geom=g)
        zx.frames(120)
        zx.poke(23296, [0])
        boot(zx, rom)
        zx.frames(400)
        txt = zx.screen_text()
        menu = '1  alpha' in txt and '2  beta' in txt and 'data' not in txt and 'run' not in txt.split('\n', 2)[-1]
        zx.screenshot(os.path.join(HERE, 'shell_%s_%s_menu.png' % (fmt, rom.split()[2])))
        zx.key('Digit2', frames=6)
        zx.frames(300)
        ran = zx.peek(23296)[0] == 22
        print('  %s menu %s, chose 2 -> %s' % (fmt, 'ok' if menu else 'BAD', 'ran beta' if ran else 'FAIL (%d)' % zx.peek(23296)[0]))
        if not (menu and ran):
            print(txt); fails += 1
    with ZX(rom=rom, machine='48k') as zx:
        img, g = disk(fmt, [('gamma', 33)])
        zx.insert(img, geom=g)
        zx.frames(120)
        zx.poke(23296, [0])
        boot(zx, rom)
        zx.frames(500)
        ok = zx.peek(23296)[0] == 33
        print('  %s single program: %s' % (fmt, 'ran at once' if ok else 'FAIL'))
        fails += 0 if ok else 1
    return fails


if __name__ == '__main__':
    fails = 0
    for rom in sys.argv[1:] or ROMS:
        print('==', rom)
        for fmt in os.environ.get('SH_FORMATS', 'sd,dd').split(','):
            fails += one(rom, fmt)
    print('FAILURES:', fails)
