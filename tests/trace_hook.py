"""Trace (pc, opus-paged) from ENTER of a typed command, to see ROM hook handling."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from zxharness import ZX
from zxkeys import chords
rom, cmd = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 4000
with ZX(rom=rom) as zx:
    zx.frames(120)
    for ch in chords(cmd)[:-1]:
        for k in ch: zx.js(f'zxDebug.keyDown("{k}")')
        zx.frames(3)
        for k in ch: zx.js(f'zxDebug.keyUp("{k}")')
        zx.frames(3)
    zx.js('''(()=>{window._tr=[]; const s=zxDebug.spectrum;
      zxDebug.onAccess({onFetch:(a)=>{ if(window._tr.length<%d){
         const op=s.memory.opusActive; const t=window._tr; const k=(op?'O':'S')+a.toString(16);
         if(!t.length||t[t.length-1][0]!==k) t.push([k,1]); else t[t.length-1][1]++; }}}); return 1})()''' % N)
    zx.js('zxDebug.keyDown("Enter")'); zx.frames(3); zx.js('zxDebug.keyUp("Enter")'); zx.frames(20)
    tr = zx.js('window._tr')
    zx.js('zxDebug.offAccess(), 1')
    # collapse into "blocks": print addresses, mark ROM switches
    out, last = [], None
    for k, n in tr:
        side = k[0]
        if side != last:
            out.append('\n' + ('OPUS: ' if side == 'O' else 'SPEC: '))
            last = side
        out.append(k[1:] + ' ')
    print(''.join(out)[:int(sys.argv[4]) if len(sys.argv) > 4 else 20000])
