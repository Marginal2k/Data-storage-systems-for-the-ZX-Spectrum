import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from zxharness import ZX
rom = sys.argv[1]
with ZX(rom=rom) as zx:
    zx.frames(120)
    s = zx.js('''(()=>{const m=zxDebug.spectrum.memory, o=zxDebug.spectrum.opus;
        return {ram: Array.from(m.opusRam.slice(0,0x800)), cra:o.controlA, dra:o.dataRegA, ddr:o.dataDirA}})()''')
    print('CRA=%02X DRA=%02X DDR=%02X' % (s['cra'], s['dra'], s['ddr']))
    r = bytes(s['ram'])
    for i in range(0, 0x800, 32):
        if any(r[i:i+32]): print('%04X %s' % (0x2000 + i, r[i:i+32].hex()))
