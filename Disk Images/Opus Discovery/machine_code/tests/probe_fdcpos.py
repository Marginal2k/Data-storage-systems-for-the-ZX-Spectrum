"""What does each Opus ROM leave in the FDC / PIA after loading a BASIC file?

Builds disks with a "run" BASIC whose REM holds a probe:
    CALL #1708 ; copy TR, SR, PIA_A, STATUS to #5B00.. ; CALL #1748 ; RET
then boots with RUN (Opus hook: LOAD *1;"run") and reads the values back.
Variants place the file so the BASIC part ends mid-track and at sector 17.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
from zxharness import ZX
from opdtool import OPD, tokenize, basic_line, tokenize_line

ROMS = ['Opus Discovery 1 v1.2 (1985)(Opus Supplies).rom',
        'Opus Discovery 1 v2.2 (1985)(Opus Supplies).rom',
        'Opus Discovery 1 v2.22 (1985)(Opus Supplies).rom',
        'Opus Discovery EXCOM v2.28 Paul Cheffing (19xx)(Opus).rom',
        'Opus Discovery QuickDOS v2.31 (19xx)(Opus).rom']

PROBE = bytes([0xCD, 0x08, 0x17,              # call #1708
               0x3A, 0x01, 0x28, 0x32, 0x00, 0x5B,   # ld a,(TR)  ; ld (#5B00),a
               0x3A, 0x02, 0x28, 0x32, 0x01, 0x5B,   # ld a,(SR)
               0x3A, 0x00, 0x30, 0x32, 0x02, 0x5B,   # ld a,(PIA_A)
               0x3A, 0x00, 0x28, 0x32, 0x03, 0x5B,   # ld a,(STATUS)
               0xCD, 0x48, 0x17,              # call #1748
               0x3E, 0xAA, 0x32, 0x04, 0x5B,  # ld a,#AA ; ld (#5B04),a
               0xC9])


def make(pad_blocks, rem_extra):
    o = OPD.new(False, 'PROBE')
    if pad_blocks:
        o.add_raw('pad', b'\0' * (pad_blocks * 256))
    prog = basic_line(10, bytes([0xEA]) + PROBE + b'\0' * rem_extra) + tokenize(
        '20 RANDOMIZE USR (PEEK 23635+256*PEEK 23636+5)\n30 STOP')
    payload = struct.pack('<BHHH', 0, len(prog), 10, len(prog)) + prog
    nb = (len(payload) + 255) // 256
    payload += b'\xEE' * (nb * 256 - len(payload)) + b'\x77' * 256 * 5   # 5 "code" blocks after
    e = o.add_raw('run', payload)
    o.write_blocks(0, o.read_blocks(0, 7))
    last = e['first'] + nb - 1
    return o, e, nb, last


if __name__ == '__main__':
    cmd = os.environ.get('BOOT', 'RUN')
    roms = sys.argv[1:] or ROMS
    for rom in roms:
        print('==', rom)
        for pad, extra in [(0, 0), (0, 600), (9, 0), (8, 300)]:
            o, e, nb, last = make(pad, extra)
            with ZX(rom=rom) as zx:
                zx.frames(120)
                zx.insert(bytes(o.d))
                zx.basic(cmd)
                n = zx.run_until('window.zxDebug.peek(0x5B04)===0xAA', 1500, 10)
                tr, sr, pia, st, ok = zx.peek(0x5B00, 5)
                prog = struct.unpack('<H', zx.peek(23635, 2))[0]
                print('  file blocks %d-%d basic part %d sect, last basic block %d = %s | '
                      'boot %s  TR=%d SR=%d PIA=%02X ST=%02X  PROG=%d' % (
                          e['first'], e['end'], nb, last, o.phys(last), 'ok' if n is not None else 'FAILED',
                          tr, sr, pia, st, prog))
                if n is None:
                    print(zx.screen_text())
