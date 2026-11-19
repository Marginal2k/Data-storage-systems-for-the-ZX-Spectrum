import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from zxharness import ZX
from run_libtest import ROMS
img = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'disks', 'Samples', 'Astrum.opd')
for rom in ROMS:
    with ZX(rom=rom) as zx:
        zx.frames(120); zx.insert(img)
        zx.basic('LOAD *"m";1;"mon"'); zx.frames(400)
        print(rom[:45], '| mon (block 226):', zx.screen_text().strip().split('\n')[-1][-30:])
