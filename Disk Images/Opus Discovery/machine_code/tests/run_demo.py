"""End-to-end: build examples/demo (full and --tiny), boot it, check that the
code got control (marker) and the loading screen is intact. Saves screenshots."""
import os, sys, subprocess
sys.stdout.reconfigure(line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from zxharness import ZX
from run_libtest import ROMS

DEMO = os.path.join(ROOT, 'examples', 'demo')
fails = 0
for opts in ([], ['--tiny'], ['--compact'], ['--catalog'], ['--tiny', '--fmt', 'dd'], ['--fmt', 'dd']):
    subprocess.run(['sh', os.path.join(DEMO, 'build.sh')] + opts, check=True, stdout=subprocess.DEVNULL)
    img = open(os.path.join(DEMO, 'demo.opd'), 'rb').read()
    scr = open(os.path.join(DEMO, 'screen.scr'), 'rb').read()
    code = open(os.path.join(DEMO, 'demo.bin'), 'rb').read()
    marker = 0x8000 + len(code) - 2
    for rom in (sys.argv[1:] or ROMS):
        boot = 'RUN' if 'v1.2' in rom else 'LOAD *"m";1;"run"'
        with ZX(rom=rom) as zx:
            zx.frames(120)
            zx.insert(img)
            zx.basic(boot)
            n = zx.run_until('zxDebug.peek(%d)===0x5A' % marker, 3000, 10)
            zx.frames(20)
            ok = n is not None and zx.peek(16384, 6912) == scr and zx.peek(marker + 1)[0] > 0
            fails += not ok
            tag = ('-'.join(o.lstrip('-') for o in opts) or 'fast')
            print('%-8s %-55s %s  frames=%s' % (tag, rom, 'ok' if ok else 'FAIL', n))
            zx.screenshot(os.path.join(HERE, 'demo_%s.png' % tag))
print('FAILURES:', fails)
sys.exit(1 if fails else 0)
