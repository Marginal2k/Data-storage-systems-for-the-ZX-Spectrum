"""Dump a CPCEMU/extended DSK: per-track sector IDs in physical order."""
import sys, struct
d = open(sys.argv[1], 'rb').read()
ext = d.startswith(b'EXTENDED')
tracks, sides = d[0x30], d[0x31]
tsize = struct.unpack_from('<H', d, 0x32)[0]
print('ext' if ext else 'std', 'tracks', tracks, 'sides', sides, 'tracksize', tsize)
off = 0x100
info = []
for t in range(tracks * sides):
    sz = d[0x34 + t] * 256 if ext else tsize
    if not sz: info.append(None); continue
    th = d[off:off + 256]
    assert th.startswith(b'Track-Info'), (t, th[:12])
    nsec = th[0x15]; ssz = th[0x14]; gap = th[0x16]; fill = th[0x17]
    ids = [tuple(th[0x18 + i * 8:0x18 + i * 8 + 4]) for i in range(nsec)]
    info.append((th[0x10], th[0x11], ssz, nsec, gap, fill, ids, off + 256))
    off += sz
for t, x in enumerate(info[:int(sys.argv[2]) if len(sys.argv) > 2 else 6]):
    if x: print('trk %2d side %d N=%d nsec=%d gap=%02x fill=%02x  R:' % x[:6], [i[2] for i in x[6]], 'C/H:', {(i[0], i[1], i[3]) for i in x[6]})
# anchor + catalog
def sector(trk, side, r):
    x = info[trk * sides + side]
    pos = x[7]
    for i in x[6]:
        n = 128 << i[3]
        if i[2] == r: return d[pos:pos + n]
        pos += n
a = sector(0, 0, 0)
print('anchor', a[:16].hex(), 'len', len(a))
c = sector(0, 0, 1)
for i in range(0, 64, 16): print(c[i:i+6].hex(), c[i+6:i+16])
