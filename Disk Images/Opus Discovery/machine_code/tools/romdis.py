"""Disassemble an Opus ROM range via the emulator's disassembler."""
import sys; sys.path.insert(0, r'C:\Users\User\Documents\GitHub\opus_discovery\tools')
from zxharness import ZX
rom, ranges = sys.argv[1], sys.argv[2:]
with ZX(rom=rom) as zx:
    zx.js('zxDebug.spectrum.memory.opusActive=true')
    for r in ranges:
        a, n = r.split(':'); a = int(a, 16); n = int(n)
        for l in zx.js(f'zxDebug.disassemble({a},{n})'):
            print('%04X  %-12s %s' % (l['addr'], ''.join('%02X' % b for b in l['bytes']) if isinstance(l['bytes'], list) else l['bytes'], l['text']))
        print()
    zx.js('zxDebug.spectrum.memory.opusActive=false')
