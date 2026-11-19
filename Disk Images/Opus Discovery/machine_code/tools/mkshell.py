#!/usr/bin/env python3
"""The program launcher "run" for an Opus Discovery disk (src/shell.asm).

python tools/mkshell.py [--out build/run.opus] [--add disk.opd|disk.dsk ...]

--out  writes the bytes of the Opus file "run" (7-byte header included), e.g. for
       a game's build script (OPD.add_raw('run', data))
--add  puts "run" on existing images (SD .opd / DD .dsk), in place
The BASIC part:
  10 IF NOT USR VAL "PEEK 23627+256*PEEK 23628" THEN STOP
  20 LOAD *"m";VAL "1";"??????????"
its variables: an 18-byte stub (copies the code to #C000, jumps there) + the code.
Line 10 autostarts (RUN on Opus v1.2 boots "run").
"""
import os, sys, argparse, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import opdtool

SJASM = os.environ.get('SJASMPLUS', r'C:\sjasmplus\sjasmplus.exe')
ORG = 0xC000


def assemble():
    os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
    r = subprocess.run([SJASM, '--nologo', '-I', 'src', 'src/shell.asm'], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit('sjasmplus failed')
    return open(os.path.join(ROOT, 'build', 'shell.bin'), 'rb').read()


def line(num, body):
    body = bytes(body) + b'\r'
    return num.to_bytes(2, 'big') + len(body).to_bytes(2, 'little') + body


def run_file(code):
    q = b'"'
    l10 = line(10, bytes([0xFA, 0xC3, 0xC0, 0xB0]) + q + bytes([0xBE]) + b'23627+256*' + bytes([0xBE]) + b'23628' + q + bytes([0xCB, 0xE2]))
    l20 = line(20, bytes([0xEF]) + b'*' + q + b'm' + q + b';' + bytes([0xB0]) + q + b'1' + q + b';' + q + b'?' * 10 + q)
    basic = l10 + l20
    n = len(code)
    stub = bytes([0x2A, 0x4B, 0x5C,             # ld hl,(VARS)
                  0x11, 18, 0,                  # ld de,18 (the length of this stub)
                  0x19,                         # add hl,de
                  0x11, ORG & 255, ORG >> 8,    # ld de,ORG
                  0x01, n & 255, n >> 8,        # ld bc,n
                  0xED, 0xB0,                   # ldir
                  ])
    stub += bytes([0xC3, ORG & 255, ORG >> 8])  # jp ORG
    assert len(stub) == 18
    prog = basic + stub + code + bytes([0x80])
    assert 23755 + len(prog) + 512 < ORG
    header = bytes([0]) + len(prog).to_bytes(2, 'little') + (10).to_bytes(2, 'little') + len(basic).to_bytes(2, 'little')
    return header + prog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'build', 'run.opus'))
    ap.add_argument('--add', nargs='*', default=[])
    a = ap.parse_args()
    data = run_file(assemble())
    open(a.out, 'wb').write(data)
    print('%s: %d bytes' % (a.out, len(data)))
    for img in a.add:
        o = opdtool.OPD(opdtool.load_image(img))
        if o.find('run'):
            raise SystemExit('%s: there is a "run" already' % img)
        o.add_raw('run', data)
        o.save(img)
        print('added to', img)


if __name__ == '__main__':
    main()
