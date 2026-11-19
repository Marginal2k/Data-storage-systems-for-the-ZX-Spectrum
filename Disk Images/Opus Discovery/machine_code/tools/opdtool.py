#!/usr/bin/env python3
"""opdtool - Opus Discovery disk image tool (.opd raw images and CPCEMU .dsk).

Disk layout (as the Opus ROM sees it):
  * geometry comes from the anchor sector (track 0, side 0, sector 0 = "block -1"):
    byte 2 = tracks, 3 = sectors/track, 4 = flags
    (b7-6 sector size 01=256 10=512 11=1024, b5 FM, b4 two sides)
    formats in use:  SD = 40 x 1 x 18 x 256 (flags #40),  DD = 80 x 2 x 10 x 512 (flags #90)
  * sector IDs 0..SPT-1; a logical block is one sector of whatever size
  * block B -> real = B+1;  sector = real % SPT;  t = real // SPT
               track = t % TPS;  side = t // TPS        (side 0 is filled first!)
  * .opd raw image: offset = ((track*SIDES + side)*SPT + sector)*BPS
    (the standard is SD in .opd, 184320 bytes; DD is always kept in DSK)
  * catalog = blocks 0..N (N = last block of entry 0, normally 6), 16-byte entries:
        +0 DW bytes_in_last_block-1   +2 DW first block   +4 DW last block   +6 DS 10 name
    entry 0 = disk label; files follow sorted by first block;
    end marker: first = total blocks, last = FFFF.
  * every file starts with a 7-byte header: type, length, param1, param2
  * physical order written by the ROM formatter: slot i holds sector (start + 7*i) % SPT

Usage:
  opdtool.py new  IMG [--fmt sd|sdds|dd] [--label NAME]
  opdtool.py cat  IMG
  opdtool.py add  IMG NAME FILE --code ADDR       (raw binary as CODE)
  opdtool.py addbas IMG NAME FILE.bas [--line N]  (tokenise text BASIC)
  opdtool.py get  IMG NAME OUT                    (data without header)
  opdtool.py map  IMG BLOCK                       (block -> track/side/sector)
  opdtool.py todsk IMG OUT.dsk                    (CPCEMU .dsk, e.g. for Fuse)
  opdtool.py fromdsk IN.dsk OUT.opd
IMG may itself be a .dsk file for every command.
"""
import struct, sys, os, re, argparse, base64

HERE = os.path.dirname(os.path.abspath(__file__))
BOOT_SS = 'GAUoEkC6A37ddwAjft13Ad1+AuYvVyN+5tCy3XcCydXNYwh/ANoCCeEjZgYGPnHD5Q9GEkYSHACUHOUGIvcS8XfJzbIcd91OAt1GA91uBN1mBd1eBhYAyfUGJPcS8cnlzbIcd+HAw4AnKnhcERQA7VLYzVQVBiL3EjYBIzYDIRRA5QH3GE4MAAP1Af4BJwEAAQcBAQH3Fk4MAAP1AftA5UDlQOVA5QH3GE4MAAP1Af4BJwEAAQgBAQH3Fk4MAAP1AftA5UDlQOVA5QH3GE4MAAP1Af4BJwEAAQkBAQH3Fk4MAAP1AftA5UDlQOVA5QH3GE4MAAP1Af4BJwEAAQoBAQ=='
FORMATS = {   # name: (tracks per side, sides, sectors, bytes per sector, flags)
    'sd':   (40, 1, 18, 256, 0x40),
    'sdds': (80, 2, 18, 256, 0x50),
    'dd':   (80, 2, 10, 512, 0x90),
}


def load_image(path_or_bytes):
    d = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, 'rb').read()
    if d[:8] in (b'MV - CPC', b'EXTENDED'):
        return dsk_to_raw(d)
    return bytes(d)


class OPD:
    def __init__(self, data, geom=None):
        self.d = bytearray(load_image(data))
        if geom is None:
            geom = self.detect()
        self.tps, self.sides, self.spt, self.bps = geom
        if self.tps * self.sides * self.spt * self.bps != len(self.d):
            raise ValueError('image size %d does not match geometry %s' % (len(self.d), geom))
        self.blocks = self.tps * self.sides * self.spt - 1

    def detect(self):
        d = self.d
        if len(d) >= 5 and d[0] == 0x18 and d[2] and d[3] and (d[4] & 0xC0):
            tps, spt, fl = d[2], d[3], d[4]
            bps = 128 << (fl >> 6)
            sides = 2 if fl & 0x10 else 1
            if tps * sides * spt * bps == len(d):
                return tps, sides, spt, bps
        for tps, sides, spt, bps, fl in FORMATS.values():
            if tps * sides * spt * bps == len(d):
                return tps, sides, spt, bps
        if len(d) == 737280:
            return 80, 2, 18, 256
        raise ValueError('cannot tell the geometry of a %d-byte image' % len(d))

    @classmethod
    def new(cls, fmt='sd', label='', cat_blocks=7):
        if isinstance(fmt, bool):
            fmt = 'sdds' if fmt else 'sd'
        tps, sides, spt, bps, flags = FORMATS[fmt]
        o = cls(b'\xe5' * (tps * sides * spt * bps), (tps, sides, spt, bps))
        boot = bytearray(base64.b64decode(BOOT_SS)[:128])
        boot[2], boot[3], boot[4] = tps, spt, flags
        o.d[0:128] = boot                        # anchor: track 0, side 0, sector 0
        cat = bytearray(b'\xe5' * (cat_blocks * bps))
        cat[0:16] = o._entry(bps - 1, 0, cat_blocks - 1, label)
        cat[16:32] = o._entry(bps - 1, o.blocks, 0xFFFF, label)
        o.write_blocks(0, cat)
        return o

    @staticmethod
    def _entry(last, first, end, name):
        return struct.pack('<HHH', last, first, end) + name.encode('latin-1')[:10].ljust(10, b' ')

    # --- geometry
    def phys(self, block):
        real = block + 1
        sec, t = real % self.spt, real // self.spt
        return t % self.tps, t // self.tps, sec

    def offset(self, block):
        trk, side, sec = self.phys(block)
        return ((trk * self.sides + side) * self.spt + sec) * self.bps

    def read_blocks(self, block, n):
        b = self.bps
        return b''.join(bytes(self.d[self.offset(x):self.offset(x) + b]) for x in range(block, block + n))

    def write_blocks(self, block, data):
        b = self.bps
        data = bytes(data)
        if len(data) % b:
            data += b'\x00' * (b - len(data) % b)
        for i in range(len(data) // b):
            o = self.offset(block + i)
            self.d[o:o + b] = data[i * b:(i + 1) * b]

    # --- catalog
    def cat_blocks(self):
        end = struct.unpack_from('<H', self.read_blocks(0, 1), 4)[0]
        return end + 1 if 0 < end < 64 else 7

    def catalog(self):
        cat = self.read_blocks(0, self.cat_blocks())
        ents = []
        for i in range(len(cat) // 16):
            last, first, end = struct.unpack_from('<HHH', cat, i * 16)
            name = cat[i * 16 + 6:i * 16 + 16].decode('latin-1')
            ents.append(dict(idx=i, last=last, first=first, end=end, name=name))
            if end == 0xFFFF:
                break
        return ents

    def files(self):
        return [e for e in self.catalog()[1:] if e['end'] != 0xFFFF]

    def find(self, name):
        n = name.ljust(10)[:10]
        for e in self.files():
            if e['name'] == n:
                return e
        return None

    def file_bytes(self, e):
        n = e['end'] - e['first'] + 1
        raw = self.read_blocks(e['first'], n)
        return raw[:(n - 1) * self.bps + (e['last'] % self.bps) + 1]

    def add_raw(self, name, payload):
        """Add a file whose on-disk bytes (header included) are `payload`."""
        if self.find(name):
            raise ValueError('file exists: ' + name)
        b = self.bps
        need = (len(payload) + b - 1) // b
        ncat = self.cat_blocks()
        ents = self.catalog()
        prev_end = ents[0]['end']
        ins = None
        for i, e in enumerate(ents[1:], 1):
            start = e['first'] if e['end'] != 0xFFFF else self.blocks
            if start - prev_end - 1 >= need:
                ins = i; break
            prev_end = e['end']
        if ins is None:
            raise ValueError('disk full')
        if len(ents) + 1 > ncat * b // 16:
            raise ValueError('catalog full')
        first = prev_end + 1
        new = dict(last=(len(payload) - 1) % b, first=first, end=first + need - 1, name=name.ljust(10)[:10])
        ents.insert(ins, new)
        cat = bytearray(b'\xe5' * (ncat * b))
        for i, e in enumerate(ents):
            cat[i * 16:i * 16 + 16] = self._entry(e['last'], e['first'], e['end'], e['name'])
        self.write_blocks(0, cat)
        self.write_blocks(first, payload)
        return new

    def add_file(self, name, ftype, data, p1, p2):
        hdr = struct.pack('<BHHH', ftype, len(data), p1 & 0xFFFF, p2 & 0xFFFF)
        return self.add_raw(name, hdr + bytes(data))

    def add_code(self, name, data, addr):
        return self.add_file(name, 3, data, addr, 0x8000)

    def add_basic(self, name, prog, line=0x8000):
        return self.add_file(name, 0, prog, line, len(prog))

    def save(self, path):
        # Conventions: SD (40 x 1 x 18 x 256) is the standard 184320-byte .opd;
        # DD (512-byte sectors) only ever lives in DSK - no emulator reads it raw.
        if self.bps != 256 and not path.lower().endswith('.dsk'):
            raise ValueError('%d-byte-sector (DD) images are saved as .dsk only, not %s' % (self.bps, path))
        if path.lower().endswith('.dsk'):
            open(path, 'wb').write(self.to_dsk())
        else:
            open(path, 'wb').write(self.d)

    # --- CPCEMU .dsk
    def interleave(self, track):
        """Physical sector order as the Opus ROM formats it (step 7)."""
        start = (7 + track * (13 - 5)) % self.spt if self.spt == 18 else (7 if track % 2 == 0 else 2)
        if self.spt != 18 and self.spt != 10:
            start = 0
        return [(start + 7 * i) % self.spt for i in range(self.spt)]

    def to_dsk(self):
        n = {128: 0, 256: 1, 512: 2, 1024: 3}[self.bps]
        tsize = 256 + self.spt * self.bps
        out = bytearray(256)
        out[0:34] = b'MV - CPCEMU Disk-File\r\nDisk-Info\r\n'
        out[0x22:0x30] = b'opdtool'.ljust(14, b' ')
        out[0x30], out[0x31] = self.tps, self.sides
        struct.pack_into('<H', out, 0x32, tsize)
        for trk in range(self.tps):
            for side in range(self.sides):
                th = bytearray(256)
                th[0:12] = b'Track-Info\r\n'
                th[0x10], th[0x11], th[0x14], th[0x15], th[0x16], th[0x17] = trk, side, n, self.spt, 0x4E, 0xE5
                data = bytearray()
                for i, s in enumerate(self.interleave(trk)):
                    th[0x18 + i * 8:0x18 + i * 8 + 4] = bytes([trk, side, s, n])
                    o = ((trk * self.sides + side) * self.spt + s) * self.bps
                    data += self.d[o:o + self.bps]
                out += th + data
        return bytes(out)


def dsk_to_raw(d):
    ext = d.startswith(b'EXTENDED')
    tracks, sides = d[0x30], d[0x31]
    tsize = struct.unpack_from('<H', d, 0x32)[0]
    off, secs, geo = 0x100, {}, None
    for t in range(tracks * sides):
        sz = d[0x34 + t] * 256 if ext else tsize
        if not sz:
            continue
        th = d[off:off + 256]
        nsec = th[0x15]
        pos = off + 256
        for i in range(nsec):
            c, h, r, n = th[0x18 + i * 8:0x18 + i * 8 + 4]
            ln = struct.unpack_from('<H', th, 0x18 + i * 8 + 6)[0] if ext else 128 << n
            secs[(t // sides, t % sides, r)] = d[pos:pos + (128 << n)]
            geo = geo or (nsec, 128 << n)
            pos += ln
        off += sz
    spt, bps = geo
    raw = bytearray(b'\xe5' * (tracks * sides * spt * bps))
    for (trk, side, r), data in secs.items():
        if r < spt:
            o = ((trk * sides + side) * spt + r) * bps
            raw[o:o + bps] = data[:bps].ljust(bps, b'\xe5')
    return bytes(raw)


# ---------------------------------------------------------------- BASIC tokeniser
TOKENS = ['RND', 'INKEY$', 'PI', 'FN', 'POINT', 'SCREEN$', 'ATTR', 'AT', 'TAB', 'VAL$', 'CODE', 'VAL',
          'LEN', 'SIN', 'COS', 'TAN', 'ASN', 'ACS', 'ATN', 'LN', 'EXP', 'INT', 'SQR', 'SGN', 'ABS',
          'PEEK', 'IN', 'USR', 'STR$', 'CHR$', 'NOT', 'BIN', 'OR', 'AND', '<=', '>=', '<>', 'LINE',
          'THEN', 'TO', 'STEP', 'DEF FN', 'CAT', 'FORMAT', 'MOVE', 'ERASE', 'OPEN #', 'CLOSE #',
          'MERGE', 'VERIFY', 'BEEP', 'CIRCLE', 'INK', 'PAPER', 'FLASH', 'BRIGHT', 'INVERSE', 'OVER',
          'OUT', 'LPRINT', 'LLIST', 'STOP', 'READ', 'DATA', 'RESTORE', 'NEW', 'BORDER', 'CONTINUE',
          'DIM', 'REM', 'FOR', 'GO TO', 'GO SUB', 'INPUT', 'LOAD', 'LIST', 'LET', 'PAUSE', 'NEXT',
          'POKE', 'PRINT', 'PLOT', 'RUN', 'SAVE', 'RANDOMIZE', 'IF', 'CLS', 'DRAW', 'CLEAR', 'RETURN',
          'COPY']
TOKMAP = {t: 0xA5 + i for i, t in enumerate(TOKENS)}
TOKORDER = sorted(TOKENS, key=len, reverse=True)


def fp_number(v):
    """Spectrum 5-byte form (small integer form when possible)."""
    if float(v).is_integer() and -65535 <= v <= 65535:
        v = int(v)
        if v >= 0:
            return bytes([0, 0, v & 255, v >> 8, 0])
        v2 = (v + 65536) & 0xFFFF
        return bytes([0, 0xFF, v2 & 255, v2 >> 8, 0])
    import math
    v = float(v)
    if v == 0:
        return bytes(5)
    s = 0x80 if v < 0 else 0
    v = abs(v)
    e = math.floor(math.log2(v)) + 1
    m = v / (2 ** e)
    mi = int(round(m * (1 << 32)))
    if mi >= 1 << 32:
        mi >>= 1; e += 1
    return bytes([e + 128, ((mi >> 24) & 0x7F) | s, (mi >> 16) & 255, (mi >> 8) & 255, mi & 255])


def tokenize_line(text):
    out = bytearray()
    i, in_str, in_rem = 0, False, False
    while i < len(text):
        c = text[i]
        if in_rem:
            out += c.encode('latin-1'); i += 1; continue
        if in_str:
            out.append(ord(c)); i += 1
            if c == '"': in_str = False
            continue
        if c == '"':
            in_str = True; out.append(34); i += 1; continue
        if c == '{':  # {hex bytes} raw insert, e.g. {C9 00}
            j = text.index('}', i)
            out += bytes.fromhex(text[i + 1:j]); i = j + 1; continue
        up = text[i:].upper()
        tok = None
        for t in TOKORDER:
            if up.startswith(t):
                if t[-1].isalpha() and i + len(t) < len(text) and (text[i + len(t)].isalnum() or text[i + len(t)] == '$'):
                    continue
                if t[0].isalpha() and i > 0 and text[i - 1].isalpha():
                    continue
                tok = t; break
        if tok:
            out.append(TOKMAP[tok]); i += len(tok)
            if tok == 'REM': in_rem = True
            while i < len(text) and text[i] == ' ' and not in_rem: i += 1
            if in_rem and i < len(text) and text[i] == ' ': i += 1
            continue
        m = re.match(r'\d+\.?\d*(e[+-]?\d+)?|\.\d+', text[i:], re.I)
        if m and not (i > 0 and (text[i - 1].isalpha() or text[i - 1] == '$')):
            s = m.group(0)
            out += s.encode(); out.append(0x0E); out += fp_number(float(s)); i += len(s); continue
        if c == ' ':
            i += 1; continue
        out.append(ord(c)); i += 1
    return bytes(out)


def tokenize(src):
    """src: text with 'NN statement' lines. Returns program bytes."""
    prog = bytearray()
    for raw in src.splitlines():
        if not raw.strip():
            continue
        m = re.match(r'\s*(\d+)\s?(.*)$', raw)
        num, body = int(m.group(1)), m.group(2)
        body = tokenize_line(body) + b'\r'
        prog += struct.pack('>H', num) + struct.pack('<H', len(body)) + body
    return bytes(prog)


def basic_line(num, body_bytes):
    body = bytes(body_bytes) + b'\r'
    return struct.pack('>H', num) + struct.pack('<H', len(body)) + body


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('new'); p.add_argument('img'); p.add_argument('--fmt', default='sd', choices=sorted(FORMATS)); p.add_argument('--label', default='')
    p = sub.add_parser('todsk'); p.add_argument('img'); p.add_argument('out')
    p = sub.add_parser('fromdsk'); p.add_argument('img'); p.add_argument('out')
    p = sub.add_parser('cat'); p.add_argument('img')
    p = sub.add_parser('add'); p.add_argument('img'); p.add_argument('name'); p.add_argument('file'); p.add_argument('--code', type=lambda x: int(x, 0), required=True)
    p = sub.add_parser('addbas'); p.add_argument('img'); p.add_argument('name'); p.add_argument('file'); p.add_argument('--line', type=int, default=0x8000)
    p = sub.add_parser('get'); p.add_argument('img'); p.add_argument('name'); p.add_argument('out')
    p = sub.add_parser('map'); p.add_argument('img'); p.add_argument('block', type=int)
    a = ap.parse_args()
    if a.cmd == 'new':
        OPD.new(a.fmt, a.label).save(a.img); return
    o = OPD(a.img)
    if a.cmd in ('todsk', 'fromdsk'):
        o.save(a.out); return
    if a.cmd == 'cat':
        ents = o.catalog()
        print('Label: %r  geometry: %d tracks x %d side(s) x %d x %d bytes, %d blocks, catalog %d blocks' % (
            ents[0]['name'], o.tps, o.sides, o.spt, o.bps, o.blocks, o.cat_blocks()))
        for e in o.files():
            raw = o.file_bytes(e)
            t, ln, p1, p2 = struct.unpack_from('<BHHH', raw)
            kind = {0: 'BASIC', 1: 'NUM', 2: 'CHR', 3: 'CODE'}.get(t, '?%d' % t)
            print('%-10s %-5s len=%5d p1=%5d p2=%5d  blocks %4d-%4d (%d)  file bytes=%d' % (
                ''.join(ch if ' ' <= ch < '' else '?' for ch in e['name']), kind, ln, p1, p2, e['first'], e['end'], e['end'] - e['first'] + 1, len(raw)))
        free = ents[-1]['first'] - (ents[-2]['end'] + 1)
        print('end marker: first=%d  free at end: %d blocks' % (ents[-1]['first'], free))
    elif a.cmd == 'add':
        o.add_code(a.name, open(a.file, 'rb').read(), a.code); o.save(a.img)
    elif a.cmd == 'addbas':
        o.add_basic(a.name, tokenize(open(a.file, encoding='utf-8').read()), a.line); o.save(a.img)
    elif a.cmd == 'get':
        e = o.find(a.name)
        open(a.out, 'wb').write(o.file_bytes(e)[7:])
    elif a.cmd == 'map':
        print(o.phys(a.block), hex(o.offset(a.block)))


if __name__ == '__main__':
    main()
